"""WebSocket API used by the Dog Assistant card."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from .const import CARE_EVENT_TYPES, DOMAIN, RECORD_KINDS
from .models import attention_items, parse_datetime
from .storage import DogAssistantManager
from .validation import (
    EVENT_DATA_SCHEMAS,
    LONG_TEXT,
    PROFILE_SCHEMA,
    RECORD_SCHEMAS,
    SAFE_ID,
    SHORT_TEXT,
    datetime_text,
)


def _manager(hass: HomeAssistant) -> DogAssistantManager:
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries or not getattr(entries[0], "runtime_data", None):
        raise RuntimeError("Dog Assistant is not loaded")
    return entries[0].runtime_data.manager


def _send_not_found(connection: websocket_api.ActiveConnection, msg_id: int, noun: str) -> None:
    connection.send_error(msg_id, "not_found", f"{noun} was not found")


def _redact_dog_for_non_admin(dog: dict[str, Any]) -> dict[str, Any]:
    """Remove sensitive structured data from a household-care response."""
    profile = dog.get("profile", {})
    dog["profile"] = {key: profile[key] for key in ("breed", "sex", "photo_document_id") if key in profile}
    dog["vaccinations"] = []
    dog["appointments"] = []
    dog["documents"] = []
    dog["attention"] = [item for item in dog.get("attention", []) if item.get("kind") == "medication"]
    return dog


@websocket_api.websocket_command({vol.Required("type"): "dogassistant/list_dogs"})
@websocket_api.async_response
async def ws_list_dogs(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """List compact dog records."""
    manager = _manager(hass)
    connection.send_result(
        msg["id"],
        [{"id": dog["id"], "name": dog["name"]} for dog in manager.data["dogs"].values()],
    )


@websocket_api.websocket_command({vol.Required("type"): "dogassistant/get_dog", vol.Required("dog_id"): SAFE_ID})
@websocket_api.async_response
async def ws_get_dog(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Return the complete structured dog record."""
    dog = _manager(hass).get_dog(msg["dog_id"])
    if not dog:
        _send_not_found(connection, msg["id"], "Dog")
        return
    manager = _manager(hass)
    dog["attention"] = attention_items(dog, manager.data["events"], manager.data["settings"])
    if not connection.user.is_admin:
        dog = _redact_dog_for_non_admin(dog)
    connection.send_result(msg["id"], dog)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "dogassistant/list_events",
        vol.Required("dog_id"): SAFE_ID,
        vol.Optional("event_types"): [vol.In(CARE_EVENT_TYPES)],
        vol.Optional("cursor", default=0): vol.All(int, vol.Range(min=0)),
        vol.Optional("limit", default=50): vol.All(int, vol.Range(min=1, max=200)),
    }
)
@websocket_api.async_response
async def ws_list_events(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Return a newest-first page of events."""
    manager = _manager(hass)
    if msg["dog_id"] not in manager.data["dogs"]:
        _send_not_found(connection, msg["id"], "Dog")
        return
    filters = set(msg.get("event_types", []))
    events = [
        event
        for event in manager.data["events"]
        if msg["dog_id"] in event.get("dog_ids", []) and (not filters or event.get("type") in filters)
    ]
    events.sort(key=lambda event: event.get("occurred_at", ""), reverse=True)
    start = msg["cursor"]
    page = events[start : start + msg["limit"]]
    connection.send_result(
        msg["id"], {"items": page, "next_cursor": start + len(page) if start + len(page) < len(events) else None}
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "dogassistant/update_profile",
        vol.Required("dog_id"): SAFE_ID,
        vol.Optional("name"): SHORT_TEXT,
        vol.Required("profile"): dict,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_update_profile(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Update a dog profile."""
    manager = _manager(hass)
    if msg["dog_id"] not in manager.data["dogs"]:
        _send_not_found(connection, msg["id"], "Dog")
        return
    try:
        profile = PROFILE_SCHEMA(msg["profile"])
    except vol.Invalid as err:
        connection.send_error(msg["id"], "invalid_format", str(err))
        return
    dog = await manager.async_update_profile(msg["dog_id"], msg.get("name"), profile)
    connection.send_result(msg["id"], dog)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "dogassistant/upsert_event",
        vol.Optional("event_id"): SAFE_ID,
        vol.Required("event_type"): vol.In(CARE_EVENT_TYPES),
        vol.Required("dog_ids"): vol.All([SAFE_ID], vol.Length(min=1, max=10)),
        vol.Required("occurred_at"): datetime_text,
        vol.Optional("caregiver"): vol.Any(SHORT_TEXT, None),
        vol.Optional("notes", default=""): LONG_TEXT,
        vol.Optional("data", default={}): dict,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_upsert_event(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Create or correct a care event."""
    manager = _manager(hass)
    if any(dog_id not in manager.data["dogs"] for dog_id in msg["dog_ids"]):
        _send_not_found(connection, msg["id"], "Dog")
        return
    try:
        validated_data = EVENT_DATA_SCHEMAS[msg["event_type"]](msg["data"])
    except vol.Invalid as err:
        connection.send_error(msg["id"], "invalid_format", str(err))
        return
    occurred_at = parse_datetime(msg["occurred_at"])
    if occurred_at is None:
        connection.send_error(msg["id"], "invalid_format", "invalid occurred_at")
        return
    event_data = {
        "dog_ids": msg["dog_ids"],
        "occurred_at": occurred_at.isoformat(),
        "caregiver": msg.get("caregiver") or connection.user.name,
        "notes": msg["notes"],
        "data": validated_data,
    }
    if event_id := msg.get("event_id"):
        try:
            result = await manager.async_update_event(event_id, event_data)
        except StopIteration:
            _send_not_found(connection, msg["id"], "Event")
            return
    else:
        result = await manager.async_add_event({"type": msg["event_type"], **event_data})
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command({vol.Required("type"): "dogassistant/delete_event", vol.Required("event_id"): SAFE_ID})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_delete_event(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Delete a care event."""
    if not await _manager(hass).async_delete_event(msg["event_id"]):
        _send_not_found(connection, msg["id"], "Event")
        return
    connection.send_result(msg["id"], {"deleted": True})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "dogassistant/upsert_record",
        vol.Required("dog_id"): SAFE_ID,
        vol.Required("kind"): vol.In(RECORD_KINDS),
        vol.Required("record"): dict,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_upsert_record(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Create or update a structured dog record."""
    manager = _manager(hass)
    if msg["dog_id"] not in manager.data["dogs"]:
        _send_not_found(connection, msg["id"], "Dog")
        return
    try:
        record = RECORD_SCHEMAS[msg["kind"]](msg["record"])
    except vol.Invalid as err:
        connection.send_error(msg["id"], "invalid_format", str(err))
        return
    result = await manager.async_upsert_record(msg["dog_id"], msg["kind"], record)
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "dogassistant/delete_record",
        vol.Required("dog_id"): SAFE_ID,
        vol.Required("kind"): vol.In(RECORD_KINDS),
        vol.Required("record_id"): SAFE_ID,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_delete_record(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Delete a structured record."""
    if not await _manager(hass).async_delete_record(msg["dog_id"], msg["kind"], msg["record_id"]):
        _send_not_found(connection, msg["id"], "Record")
        return
    connection.send_result(msg["id"], {"deleted": True})


@websocket_api.websocket_command({vol.Required("type"): "dogassistant/subscribe", vol.Optional("dog_id"): SAFE_ID})
@callback
def ws_subscribe(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Push mutation notices to a card."""
    manager = _manager(hass)
    dog_id = msg.get("dog_id")

    @callback
    def forward(change: dict[str, Any]) -> None:
        if dog_id is None or dog_id in change.get("dog_ids", []):
            connection.send_event(msg["id"], change)

    connection.subscriptions[msg["id"]] = manager.async_subscribe(forward)
    connection.send_result(msg["id"])


def async_register_websocket_commands(hass: HomeAssistant) -> None:
    """Register card commands."""
    for command in (
        ws_list_dogs,
        ws_get_dog,
        ws_list_events,
        ws_update_profile,
        ws_upsert_event,
        ws_delete_event,
        ws_upsert_record,
        ws_delete_record,
        ws_subscribe,
    ):
        websocket_api.async_register_command(hass, command)
