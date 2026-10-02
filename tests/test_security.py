"""Security and boundary tests for Dog Assistant."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
import voluptuous as vol

from custom_components.dogassistant.http import _safe_filename
from custom_components.dogassistant.storage import DogAssistantManager
from custom_components.dogassistant.validation import EVENT_DATA_SCHEMAS, PROFILE_SCHEMA, RECORD_SCHEMAS, finite_number
from custom_components.dogassistant.websocket import _public_event, _redact_dog_for_non_admin


def test_filename_is_portable() -> None:
    assert _safe_filename("../../medical.pdf") == "medical.pdf"
    assert _safe_filename(r"..\..\medical.pdf") == "medical.pdf"
    assert _safe_filename('bad"\r\nname.pdf') == "badname.pdf"


def test_schemas_reject_unknown_fields_and_unsafe_ids() -> None:
    with pytest.raises(vol.Invalid):
        PROFILE_SCHEMA({"unexpected": "value"})
    with pytest.raises(vol.Invalid):
        RECORD_SCHEMAS["foods"]({"id": 'bad" onclick="alert(1)', "name": "Food", "portion_grams": 100})


def test_numeric_values_must_be_finite_and_bounded() -> None:
    validator = finite_number(maximum=100)
    with pytest.raises(vol.Invalid):
        validator(float("nan"))
    with pytest.raises(vol.Invalid):
        validator(float("inf"))
    with pytest.raises(vol.Invalid):
        validator(101)


def test_water_event_accepts_only_an_empty_payload() -> None:
    assert EVENT_DATA_SCHEMAS["water"]({}) == {}
    with pytest.raises(vol.Invalid):
        EVENT_DATA_SCHEMAS["water"]({"amount": 1})


def test_training_command_requires_a_command_and_meaning() -> None:
    assert RECORD_SCHEMAS["commands"]({"command": "Place", "meaning": "Go to your bed"}) == {
        "command": "Place",
        "meaning": "Go to your bed",
    }
    with pytest.raises(vol.Invalid):
        RECORD_SCHEMAS["commands"]({"command": "Place"})


def test_event_ownership_is_not_public() -> None:
    event = {"id": "event", "type": "water", "created_by_user_id": "private-user-id"}
    assert _public_event(event) == {"id": "event", "type": "water"}


def test_non_admin_response_omits_sensitive_records() -> None:
    dog = {
        "profile": {"breed": "Labrador", "insurance_policy": "secret", "photo_document_id": "photo"},
        "vaccinations": [{"name": "Booster"}],
        "appointments": [{"title": "Vet"}],
        "documents": [{"label": "Policy"}],
        "commands": [{"command": "Place", "meaning": "Go to your bed"}],
        "attention": [{"kind": "insurance"}, {"kind": "medication"}],
    }
    redacted = _redact_dog_for_non_admin(dog)
    assert redacted["profile"] == {"breed": "Labrador", "photo_document_id": "photo"}
    assert redacted["vaccinations"] == []
    assert redacted["appointments"] == []
    assert redacted["documents"] == []
    assert redacted["commands"] == [{"command": "Place", "meaning": "Go to your bed"}]
    assert redacted["attention"] == [{"kind": "medication"}]


async def test_new_record_ids_are_generated_server_side() -> None:
    manager = object.__new__(DogAssistantManager)
    manager.data = {"dogs": {"dog": {"foods": [], "updated_at": ""}}}
    manager._lock = asyncio.Lock()

    async def commit(change: dict) -> None:
        return None

    manager._async_commit = commit
    stored = await manager.async_upsert_record(
        "dog", "foods", {"id": "client-selected", "name": "Food", "portion_grams": 100}
    )
    assert stored["id"] != "client-selected"
    assert len(stored["id"]) == 32


async def test_recent_event_can_only_be_undone_by_its_creator() -> None:
    manager = object.__new__(DogAssistantManager)
    manager.data = {
        "events": [
            {
                "id": "recent",
                "type": "water",
                "dog_ids": ["dog"],
                "created_by_user_id": "user-a",
                "created_at": datetime.now(UTC).isoformat(),
            }
        ]
    }
    manager._lock = asyncio.Lock()

    async def commit(change: dict) -> None:
        return None

    manager._async_commit = commit
    assert await manager.async_undo_event("recent", "user-b") == "forbidden"
    assert await manager.async_undo_event("recent", "user-a") == "deleted"
    assert manager.data["events"] == []


async def test_undo_rejects_expired_and_unknown_events() -> None:
    manager = object.__new__(DogAssistantManager)
    manager.data = {
        "events": [
            {
                "id": "old",
                "type": "meal",
                "dog_ids": ["dog"],
                "created_by_user_id": "user-a",
                "created_at": (datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
            }
        ]
    }
    manager._lock = asyncio.Lock()
    assert await manager.async_undo_event("old", "user-a") == "expired"
    assert await manager.async_undo_event("missing", "user-a") == "not_found"
