"""Security and boundary tests for Dog Assistant."""

from __future__ import annotations

import asyncio

import pytest
import voluptuous as vol

from custom_components.dogassistant.http import _safe_filename
from custom_components.dogassistant.storage import DogAssistantManager
from custom_components.dogassistant.validation import PROFILE_SCHEMA, RECORD_SCHEMAS, finite_number
from custom_components.dogassistant.websocket import _redact_dog_for_non_admin


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


def test_non_admin_response_omits_sensitive_records() -> None:
    dog = {
        "profile": {"breed": "Labrador", "insurance_policy": "secret", "photo_document_id": "photo"},
        "vaccinations": [{"name": "Booster"}],
        "appointments": [{"title": "Vet"}],
        "documents": [{"label": "Policy"}],
        "attention": [{"kind": "insurance"}, {"kind": "medication"}],
    }
    redacted = _redact_dog_for_non_admin(dog)
    assert redacted["profile"] == {"breed": "Labrador", "photo_document_id": "photo"}
    assert redacted["vaccinations"] == []
    assert redacted["appointments"] == []
    assert redacted["documents"] == []
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
