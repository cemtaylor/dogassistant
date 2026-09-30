"""Dog Assistant sensors."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import UnitOfMass, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import DogAssistantConfigEntry
from .entity import DogAssistantEntity, dog_subentries
from .models import exercise_minutes_today, last_event, next_medication, parse_datetime


class DogTimestampSensor(DogAssistantEntity, SensorEntity):
    """A timestamp derived from Dog Assistant data."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(
        self,
        *args,
        key: str,
        translation_key: str,
        update_kinds: frozenset[str],
        value_fn: Callable[[dict[str, Any], list[dict[str, Any]]], datetime | None],
    ) -> None:
        super().__init__(*args, key=key)
        self._attr_translation_key = translation_key
        self._update_kinds = update_kinds
        self.value_fn = value_fn

    @property
    def native_value(self) -> datetime | None:
        return self.value_fn(self.dog, self.manager.data["events"])


class CurrentWeightSensor(DogAssistantEntity, SensorEntity):
    """Latest recorded weight."""

    _attr_translation_key = "current_weight"
    _attr_device_class = SensorDeviceClass.WEIGHT
    _attr_native_unit_of_measurement = UnitOfMass.KILOGRAMS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _update_kinds = frozenset({"event:weight"})

    @property
    def native_value(self) -> float | None:
        event = last_event(self.manager.data["events"], self.dog_id, "weight")
        return event.get("data", {}).get("weight_kg") if event else None


class ExerciseTodaySensor(DogAssistantEntity, SensorEntity):
    """Exercise duration for the current local day."""

    _attr_translation_key = "exercise_today"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _update_kinds = frozenset({"event:walk"})

    @property
    def native_value(self) -> int:
        return exercise_minutes_today(self.manager.data["events"], self.dog_id)


def _last(event_type: str):
    def value(dog: dict[str, Any], events: list[dict[str, Any]]) -> datetime | None:
        event = last_event(events, dog["id"], event_type)
        return parse_datetime(event.get("occurred_at")) if event else None

    return value


def _next_medication(dog: dict[str, Any], events: list[dict[str, Any]]) -> datetime | None:
    result = next_medication(dog)
    return result[1] if result else None


def _last_walk(dog: dict[str, Any], events: list[dict[str, Any]]) -> datetime | None:
    event = last_event(events, dog["id"], "walk")
    if not event:
        return None
    return parse_datetime(event.get("data", {}).get("ended_at") or event.get("occurred_at"))


def _next_record(kind: str, field: str):
    def value(dog: dict[str, Any], events: list[dict[str, Any]]) -> datetime | None:
        now = dt_util.utcnow()
        choices = [
            parsed for item in dog.get(kind, []) if (parsed := parse_datetime(item.get(field))) and parsed >= now
        ]
        return min(choices) if choices else None

    return value


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DogAssistantConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create sensors for every dog subentry."""
    manager = entry.runtime_data.manager
    timestamp_definitions = [
        ("last_meal", "last_meal", frozenset({"event:meal"}), _last("meal")),
        ("last_walk", "last_walk", frozenset({"event:walk"}), _last_walk),
        ("last_toilet", "last_toilet", frozenset({"event:toilet"}), _last("toilet")),
        ("last_medication", "last_medication", frozenset({"event:medication"}), _last("medication")),
        ("next_medication", "next_medication", frozenset({"medications"}), _next_medication),
        (
            "next_appointment",
            "next_appointment",
            frozenset({"appointments"}),
            _next_record("appointments", "start"),
        ),
        (
            "next_vaccination",
            "next_vaccination",
            frozenset({"vaccinations"}),
            _next_record("vaccinations", "due_at"),
        ),
    ]
    for subentry, dog_id in dog_subentries(entry):
        common = (entry, subentry.subentry_id, dog_id, manager)
        entities: list[SensorEntity] = []
        entities.extend(
            DogTimestampSensor(
                *common,
                key=key,
                translation_key=translation_key,
                update_kinds=update_kinds,
                value_fn=value_fn,
            )
            for key, translation_key, update_kinds, value_fn in timestamp_definitions
        )
        entities.extend(
            [
                CurrentWeightSensor(*common, key="current_weight"),
                ExerciseTodaySensor(*common, key="exercise_today"),
            ]
        )
        async_add_entities(entities, config_subentry_id=subentry.subentry_id)
