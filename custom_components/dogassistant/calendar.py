"""Dog care calendar."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from homeassistant.components.calendar import CalendarEntity, CalendarEntityFeature, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import DogAssistantConfigEntry
from .entity import DogAssistantEntity, dog_subentries
from .models import parse_datetime


class DogCareCalendar(DogAssistantEntity, CalendarEntity):
    """Appointments, vaccinations, and renewal dates for a dog."""

    _attr_translation_key = "care_calendar"
    _attr_supported_features = CalendarEntityFeature.CREATE_EVENT | CalendarEntityFeature.DELETE_EVENT
    _update_kinds = frozenset({"appointments", "vaccinations"})

    @property
    def event(self) -> CalendarEvent | None:
        """Return the next event."""
        events = self._events(dt_util.utcnow(), dt_util.utcnow() + timedelta(days=3660))
        return events[0] if events else None

    def _events(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        results: list[CalendarEvent] = []
        for appointment in self.dog.get("appointments", []):
            event_start = parse_datetime(appointment.get("start"))
            if event_start is None or not start <= event_start <= end:
                continue
            event_end = parse_datetime(appointment.get("end")) or event_start + timedelta(hours=1)
            results.append(
                CalendarEvent(
                    start=event_start,
                    end=event_end,
                    summary=appointment.get("title", "Dog appointment"),
                    description=appointment.get("notes"),
                    location=appointment.get("location"),
                    uid=appointment.get("id"),
                )
            )
        for vaccination in self.dog.get("vaccinations", []):
            due = parse_datetime(vaccination.get("due_at") or vaccination.get("due_date"))
            if due and start <= due <= end:
                results.append(
                    CalendarEvent(
                        start=due,
                        end=due + timedelta(hours=1),
                        summary=f"{vaccination.get('name', 'Vaccination')} due",
                        description=vaccination.get("notes"),
                        uid=f"vaccination:{vaccination.get('id')}",
                    )
                )
        return sorted(results, key=lambda item: item.start)

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        """Return events in a requested range."""
        return self._events(start_date, end_date)

    async def async_create_event(self, **kwargs: Any) -> None:
        """Create an appointment through the calendar UI."""
        start = kwargs["dtstart"]
        end = kwargs.get("dtend")
        await self.manager.async_upsert_record(
            self.dog_id,
            "appointments",
            {
                "id": uuid4().hex,
                "title": kwargs.get("summary", "Dog appointment"),
                "start": start.isoformat(),
                "end": end.isoformat() if end else None,
                "description": kwargs.get("description"),
                "location": kwargs.get("location"),
            },
        )
        self.async_update_event_listeners()

    async def async_delete_event(
        self, uid: str, recurrence_id: str | None = None, recurrence_range: str | None = None
    ) -> None:
        """Delete an appointment through the calendar UI."""
        await self.manager.async_delete_record(self.dog_id, "appointments", uid)
        self.async_update_event_listeners()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DogAssistantConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create a care calendar per dog."""
    manager = entry.runtime_data.manager
    for subentry, dog_id in dog_subentries(entry):
        async_add_entities(
            [DogCareCalendar(entry, subentry.subentry_id, dog_id, manager, key="care_calendar")],
            config_subentry_id=subentry.subentry_id,
        )
