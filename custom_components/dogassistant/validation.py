"""Shared validation helpers for Dog Assistant API surfaces."""

from __future__ import annotations

import math
from typing import Any

import voluptuous as vol
from homeassistant.helpers import config_validation as cv
from homeassistant.util import dt as dt_util

from .const import MAX_LONG_TEXT, MAX_SHORT_TEXT

SAFE_ID = vol.All(cv.string, vol.Length(min=1, max=64), vol.Match(r"^[A-Za-z0-9_-]+$"))
SHORT_TEXT = vol.All(cv.string, vol.Length(max=MAX_SHORT_TEXT))
LONG_TEXT = vol.All(cv.string, vol.Length(max=MAX_LONG_TEXT))
TIME_TEXT = vol.All(cv.string, vol.Match(r"^(?:[01]\d|2[0-3]):[0-5]\d$"))


def finite_number(*, minimum: float = 0, maximum: float) -> Any:
    """Return a validator for a bounded, finite floating-point number."""

    def validate(value: Any) -> float:
        number = float(value)
        if not math.isfinite(number) or not minimum <= number <= maximum:
            raise vol.Invalid(f"value must be between {minimum} and {maximum}")
        return number

    return validate


def date_text(value: Any) -> str:
    """Validate a date without changing its representation."""
    text = cv.string(value)
    if dt_util.parse_date(text) is None:
        raise vol.Invalid("invalid date")
    return text


def datetime_text(value: Any) -> str:
    """Validate a date-time without changing its representation."""
    text = cv.string(value)
    if dt_util.parse_datetime(text) is None:
        raise vol.Invalid("invalid date-time")
    return text


PROFILE_SCHEMA = vol.Schema(
    {
        vol.Optional("birth_date"): date_text,
        vol.Optional("adoption_date"): date_text,
        vol.Optional("breed"): SHORT_TEXT,
        vol.Optional("sex"): SHORT_TEXT,
        vol.Optional("neutered"): SHORT_TEXT,
        vol.Optional("colour"): SHORT_TEXT,
        vol.Optional("target_weight_kg"): finite_number(maximum=500),
        vol.Optional("diet"): LONG_TEXT,
        vol.Optional("allergies"): LONG_TEXT,
        vol.Optional("conditions"): LONG_TEXT,
        vol.Optional("vet"): LONG_TEXT,
        vol.Optional("emergency_contact"): LONG_TEXT,
        vol.Optional("microchip"): SHORT_TEXT,
        vol.Optional("microchip_registry"): SHORT_TEXT,
        vol.Optional("registration"): SHORT_TEXT,
        vol.Optional("registration_expiry"): date_text,
        vol.Optional("insurance_provider"): SHORT_TEXT,
        vol.Optional("insurance_policy"): SHORT_TEXT,
        vol.Optional("insurance_renewal"): date_text,
        vol.Optional("photo_document_id"): SAFE_ID,
    }
)

SCHEDULE_SCHEMA = vol.Schema(
    {
        vol.Optional("times", default=[]): vol.All([TIME_TEXT], vol.Length(max=24)),
        vol.Optional("weekdays", default=list(range(7))): vol.All(
            [vol.All(int, vol.Range(min=0, max=6))], vol.Length(max=7)
        ),
    }
)

RECORD_SCHEMAS = {
    "commands": vol.Schema(
        {
            vol.Optional("id"): SAFE_ID,
            vol.Required("command"): SHORT_TEXT,
            vol.Required("meaning"): LONG_TEXT,
            vol.Optional("notes"): LONG_TEXT,
        }
    ),
    "foods": vol.Schema(
        {
            vol.Optional("id"): SAFE_ID,
            vol.Required("name"): SHORT_TEXT,
            vol.Required("portion_grams"): finite_number(minimum=1, maximum=10_000),
        }
    ),
    "treats": vol.Schema(
        {
            vol.Optional("id"): SAFE_ID,
            vol.Required("name"): SHORT_TEXT,
            vol.Required("amount"): finite_number(maximum=10_000),
            vol.Required("unit"): vol.In(["pieces", "g"]),
        }
    ),
    "medications": vol.Schema(
        {
            vol.Optional("id"): SAFE_ID,
            vol.Required("name"): SHORT_TEXT,
            vol.Optional("dose"): finite_number(maximum=100_000),
            vol.Optional("unit"): SHORT_TEXT,
            vol.Optional("instructions"): LONG_TEXT,
            vol.Optional("active", default=True): cv.boolean,
            vol.Optional("as_needed", default=False): cv.boolean,
            vol.Optional("schedule", default={}): SCHEDULE_SCHEMA,
            vol.Optional("start_date"): date_text,
            vol.Optional("end_date"): date_text,
            vol.Optional("grace_minutes", default=60): vol.All(int, vol.Range(min=0, max=10_080)),
        }
    ),
    "vaccinations": vol.Schema(
        {
            vol.Optional("id"): SAFE_ID,
            vol.Required("name"): SHORT_TEXT,
            vol.Optional("administered_at"): date_text,
            vol.Optional("due_at"): date_text,
            vol.Optional("provider"): SHORT_TEXT,
            vol.Optional("batch"): SHORT_TEXT,
            vol.Optional("notes"): LONG_TEXT,
        }
    ),
    "appointments": vol.Schema(
        {
            vol.Optional("id"): SAFE_ID,
            vol.Required("title"): SHORT_TEXT,
            vol.Optional("appointment_type"): SHORT_TEXT,
            vol.Required("start"): datetime_text,
            vol.Optional("end"): vol.Any(datetime_text, None),
            vol.Optional("location"): SHORT_TEXT,
            vol.Optional("notes"): LONG_TEXT,
            vol.Optional("description"): LONG_TEXT,
        }
    ),
}

EVENT_DATA_SCHEMAS = {
    "meal": vol.Schema(
        {
            vol.Optional("food"): SHORT_TEXT,
            vol.Optional("meal_type"): SHORT_TEXT,
            vol.Optional("amount"): finite_number(maximum=100_000),
            vol.Optional("unit"): SHORT_TEXT,
        }
    ),
    "water": vol.Schema({}),
    "treat": vol.Schema(
        {
            vol.Optional("treat"): SHORT_TEXT,
            vol.Optional("amount"): finite_number(maximum=100_000),
            vol.Optional("unit"): SHORT_TEXT,
        }
    ),
    "walk": vol.Schema(
        {
            vol.Required("started_at"): datetime_text,
            vol.Optional("ended_at"): datetime_text,
            vol.Optional("activity"): SHORT_TEXT,
            vol.Optional("distance_km"): finite_number(maximum=10_000),
        }
    ),
    "toilet": vol.Schema(
        {
            vol.Required("kind"): vol.In(["urine", "stool", "both"]),
            vol.Optional("condition"): SHORT_TEXT,
        }
    ),
    "medication": vol.Schema(
        {
            vol.Required("medication_id"): SAFE_ID,
            vol.Optional("status"): vol.In(["given", "skipped", "refused"]),
            vol.Optional("dose"): finite_number(maximum=100_000),
            vol.Optional("unit"): SHORT_TEXT,
            vol.Optional("scheduled_for"): datetime_text,
        }
    ),
    "weight": vol.Schema(
        {
            vol.Required("weight_kg"): finite_number(maximum=500),
            vol.Optional("entered_unit"): vol.In(["kg", "lb", "g"]),
        }
    ),
    "note": vol.Schema(
        {
            vol.Optional("category"): vol.In(["general", "health", "behaviour", "diet", "training", "incident"]),
            vol.Required("text"): LONG_TEXT,
        }
    ),
}
