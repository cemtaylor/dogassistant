"""Automation-facing actions for Dog Assistant."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import voluptuous as vol
from homeassistant.const import ATTR_DEVICE_ID
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .models import (
    active_walk,
    matching_medication_occurrence,
    normalize_distance,
    normalize_weight,
    utcnow_iso,
)
from .validation import LONG_TEXT, SAFE_ID, SHORT_TEXT, finite_number

COMMON_SCHEMA = {
    vol.Optional("dog_id"): SAFE_ID,
    vol.Optional("dog_ids"): vol.All(cv.ensure_list, [SAFE_ID], vol.Length(max=10)),
    vol.Optional(ATTR_DEVICE_ID): vol.Any(cv.string, vol.All(cv.ensure_list, [cv.string])),
    vol.Optional("occurred_at"): cv.datetime,
    vol.Optional("notes", default=""): LONG_TEXT,
    vol.Optional("caregiver"): SHORT_TEXT,
}


def _manager(hass: HomeAssistant):
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries or not getattr(entries[0], "runtime_data", None):
        raise HomeAssistantError("Dog Assistant is not loaded")
    return entries[0].runtime_data.manager


def _resolve_dogs(hass: HomeAssistant, data: dict[str, Any]) -> list[str]:
    manager = _manager(hass)
    dog_ids = list(data.get("dog_ids", []))
    if data.get("dog_id"):
        dog_ids.append(data["dog_id"])
    device_ids = data.get(ATTR_DEVICE_ID, [])
    if isinstance(device_ids, str):
        device_ids = [device_ids]
    registry = dr.async_get(hass)
    for device_id in device_ids:
        device = registry.async_get(device_id)
        if device:
            dog_ids.extend(identifier[1] for identifier in device.identifiers if identifier[0] == DOMAIN)
    dog_ids = list(dict.fromkeys(dog_ids))
    if not dog_ids or any(dog_id not in manager.data["dogs"] for dog_id in dog_ids):
        raise HomeAssistantError("Select at least one valid Dog Assistant dog")
    return dog_ids


async def _caregiver(hass: HomeAssistant, call: ServiceCall) -> str | None:
    if value := call.data.get("caregiver"):
        return value
    if not call.context.user_id:
        return None
    user = await hass.auth.async_get_user(call.context.user_id)
    return user.name if user else None


async def _add_event(
    hass: HomeAssistant,
    call: ServiceCall,
    event_type: str,
    payload: dict[str, Any],
    occurred_at_override: Any = None,
) -> None:
    dog_ids = _resolve_dogs(hass, call.data)
    if event_type not in {"walk", "note"} and len(dog_ids) != 1:
        raise HomeAssistantError(f"{event_type.title()} events must target exactly one dog")
    occurred_at = occurred_at_override or call.data.get("occurred_at")
    if occurred_at:
        occurred_at_utc = dt_util.as_utc(occurred_at)
        now = dt_util.utcnow()
        if occurred_at_utc < now - timedelta(hours=24) or occurred_at_utc > now + timedelta(minutes=5):
            raise HomeAssistantError("Care events can only be logged within the last 24 hours")
        occurred_at = occurred_at_utc.isoformat()
    await _manager(hass).async_add_event(
        {
            "type": event_type,
            "dog_ids": dog_ids,
            "occurred_at": occurred_at or utcnow_iso(),
            "caregiver": await _caregiver(hass, call),
            "created_by_user_id": call.context.user_id,
            "notes": call.data.get("notes", ""),
            "data": payload,
        }
    )


async def _log_meal(hass: HomeAssistant, call: ServiceCall) -> None:
    payload = {
        key: call.data.get(key) for key in ("food", "meal_type", "amount", "unit") if call.data.get(key) is not None
    }
    if "amount" in payload and "unit" not in payload:
        payload["unit"] = "g"
    await _add_event(
        hass,
        call,
        "meal",
        payload,
    )


async def _log_treat(hass: HomeAssistant, call: ServiceCall) -> None:
    payload = {key: call.data.get(key) for key in ("treat", "amount", "unit") if call.data.get(key) is not None}
    await _add_event(hass, call, "treat", payload)


async def _log_water(hass: HomeAssistant, call: ServiceCall) -> None:
    await _add_event(hass, call, "water", {})


async def _start_walk(hass: HomeAssistant, call: ServiceCall) -> None:
    dogs = _resolve_dogs(hass, call.data)
    manager = _manager(hass)
    if any(active_walk(manager.data["events"], dog_id) for dog_id in dogs):
        raise HomeAssistantError("One or more selected dogs already has a walk in progress")
    occurred_at = call.data.get("occurred_at") or dt_util.utcnow()
    await _add_event(
        hass,
        call,
        "walk",
        {"started_at": dt_util.as_utc(occurred_at).isoformat(), "activity": call.data.get("activity", "walk")},
    )


async def _end_walk(hass: HomeAssistant, call: ServiceCall) -> None:
    dogs = _resolve_dogs(hass, call.data)
    manager = _manager(hass)
    candidates = {event["id"]: event for dog_id in dogs if (event := active_walk(manager.data["events"], dog_id))}
    if not candidates:
        raise HomeAssistantError("No walk is in progress for the selected dog")
    ended_at = call.data.get("occurred_at") or dt_util.utcnow()
    for event in candidates.values():
        data = dict(event.get("data", {}))
        data["ended_at"] = dt_util.as_utc(ended_at).isoformat()
        if call.data.get("distance") is not None:
            data["distance_km"] = normalize_distance(call.data["distance"], call.data.get("distance_unit", "km"))
        await manager.async_update_event(
            event["id"], {"data": data, "notes": call.data.get("notes") or event.get("notes", "")}
        )


async def _log_walk(hass: HomeAssistant, call: ServiceCall) -> None:
    ended_at = call.data.get("ended_at") or call.data.get("occurred_at") or dt_util.utcnow()
    started_at = call.data.get("started_at")
    if started_at is None:
        started_at = ended_at - timedelta(minutes=float(call.data.get("duration", 0)))
    if started_at > ended_at:
        raise HomeAssistantError("The walk must end after it starts")
    payload: dict[str, Any] = {
        "started_at": dt_util.as_utc(started_at).isoformat(),
        "ended_at": dt_util.as_utc(ended_at).isoformat(),
        "activity": call.data.get("activity", "walk"),
    }
    if call.data.get("distance") is not None:
        payload["distance_km"] = normalize_distance(call.data["distance"], call.data.get("distance_unit", "km"))
    await _add_event(hass, call, "walk", payload, ended_at)


async def _log_toilet(hass: HomeAssistant, call: ServiceCall) -> None:
    await _add_event(hass, call, "toilet", {"kind": call.data["kind"], "condition": call.data.get("condition")})


async def _record_medication(hass: HomeAssistant, call: ServiceCall) -> None:
    payload = {
        key: call.data.get(key) for key in ("medication_id", "status", "dose", "unit") if call.data.get(key) is not None
    }
    if scheduled := call.data.get("scheduled_for"):
        payload["scheduled_for"] = dt_util.as_utc(scheduled).isoformat()
    elif occurred_at := call.data.get("occurred_at"):
        payload["scheduled_for"] = dt_util.as_utc(occurred_at).isoformat()
    else:
        dog_ids = _resolve_dogs(hass, call.data)
        if len(dog_ids) == 1:
            dog = _manager(hass).data["dogs"][dog_ids[0]]
            if occurrence := matching_medication_occurrence(dog, call.data["medication_id"]):
                payload["scheduled_for"] = occurrence.isoformat()
    await _add_event(hass, call, "medication", payload)


async def _log_weight(hass: HomeAssistant, call: ServiceCall) -> None:
    weight_kg = normalize_weight(call.data["weight"], call.data.get("unit", "kg"))
    if weight_kg > 500:
        raise HomeAssistantError("Weight must not exceed 500 kg")
    await _add_event(
        hass,
        call,
        "weight",
        {
            "weight_kg": weight_kg,
            "entered_unit": call.data.get("unit", "kg"),
        },
    )


async def _add_note(hass: HomeAssistant, call: ServiceCall) -> None:
    await _add_event(hass, call, "note", {"category": call.data.get("category", "general"), "text": call.data["text"]})


def async_register_services(hass: HomeAssistant) -> None:
    """Register all integration actions once."""
    definitions = {
        "log_meal": (
            _log_meal,
            {
                vol.Optional("food"): SHORT_TEXT,
                vol.Optional("meal_type"): SHORT_TEXT,
                vol.Optional("amount"): finite_number(maximum=100_000),
                vol.Optional("unit"): SHORT_TEXT,
            },
        ),
        "log_treat": (
            _log_treat,
            {
                vol.Optional("treat"): SHORT_TEXT,
                vol.Optional("amount"): finite_number(maximum=100_000),
                vol.Optional("unit", default="pieces"): vol.In(["pieces", "g"]),
            },
        ),
        "log_water": (_log_water, {}),
        "start_walk": (
            _start_walk,
            {vol.Optional("activity", default="walk"): vol.In(["walk", "run", "hike", "play", "training"])},
        ),
        "end_walk": (
            _end_walk,
            {
                vol.Optional("distance"): finite_number(maximum=10_000),
                vol.Optional("distance_unit", default="km"): vol.In(["km", "mi", "m"]),
            },
        ),
        "log_walk": (
            _log_walk,
            {
                vol.Optional("started_at"): cv.datetime,
                vol.Optional("ended_at"): cv.datetime,
                vol.Optional("duration"): finite_number(maximum=1_440),
                vol.Optional("distance"): finite_number(maximum=10_000),
                vol.Optional("distance_unit", default="km"): vol.In(["km", "mi", "m"]),
                vol.Optional("activity", default="walk"): vol.In(["walk", "run", "hike", "play", "training"]),
            },
        ),
        "log_toilet": (
            _log_toilet,
            {
                vol.Required("kind"): vol.In(["urine", "stool", "both"]),
                vol.Optional("condition"): vol.In(
                    [
                        "normal",
                        "frequent",
                        "dark",
                        "blood",
                        "difficulty",
                        "accident",
                        "soft",
                        "diarrhoea",
                        "constipated",
                        "mucus",
                    ]
                ),
            },
        ),
        "record_medication": (
            _record_medication,
            {
                vol.Required("medication_id"): SAFE_ID,
                vol.Optional("status", default="given"): vol.In(["given", "skipped", "refused"]),
                vol.Optional("dose"): finite_number(maximum=100_000),
                vol.Optional("unit"): SHORT_TEXT,
                vol.Optional("scheduled_for"): cv.datetime,
            },
        ),
        "log_weight": (
            _log_weight,
            {
                vol.Required("weight"): finite_number(maximum=500_000),
                vol.Optional("unit", default="kg"): vol.In(["kg", "lb", "g"]),
            },
        ),
        "add_note": (
            _add_note,
            {
                vol.Required("text"): LONG_TEXT,
                vol.Optional("category", default="general"): vol.In(
                    ["general", "health", "behaviour", "diet", "training", "incident"]
                ),
            },
        ),
    }
    for name, (handler, extra_schema) in definitions.items():
        if not hass.services.has_service(DOMAIN, name):

            async def service_handler(call: ServiceCall, action=handler) -> None:
                await action(hass, call)

            hass.services.async_register(DOMAIN, name, service_handler, vol.Schema({**COMMON_SCHEMA, **extra_schema}))


def async_unregister_services(hass: HomeAssistant) -> None:
    """Remove actions when the final household entry unloads."""
    if hass.config_entries.async_loaded_entries(DOMAIN):
        return
    for name in (
        "log_meal",
        "log_treat",
        "log_water",
        "start_walk",
        "end_walk",
        "log_walk",
        "log_toilet",
        "record_medication",
        "log_weight",
        "add_note",
    ):
        hass.services.async_remove(DOMAIN, name)
