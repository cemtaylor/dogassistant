"""Small, side-effect free helpers for Dog Assistant."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any

from homeassistant.util import dt as dt_util


def utcnow_iso() -> str:
    """Return a stable UTC timestamp."""
    return dt_util.utcnow().isoformat()


def parse_datetime(value: str | datetime | None) -> datetime | None:
    """Parse and normalize a datetime to UTC."""
    if value is None:
        return None
    parsed = value if isinstance(value, datetime) else dt_util.parse_datetime(value)
    if parsed is None and isinstance(value, str):
        parsed_date = dt_util.parse_date(value)
        if parsed_date is not None:
            parsed = datetime.combine(parsed_date, datetime.min.time(), dt_util.DEFAULT_TIME_ZONE)
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
    return dt_util.as_utc(parsed)


def normalize_weight(value: float, unit: str) -> float:
    """Normalize weight to kilograms."""
    normalized = unit.lower().strip()
    if normalized in {"lb", "lbs", "pound", "pounds"}:
        return round(float(value) * 0.45359237, 4)
    if normalized in {"g", "gram", "grams"}:
        return round(float(value) / 1000, 4)
    return round(float(value), 4)


def normalize_distance(value: float, unit: str) -> float:
    """Normalize distance to kilometres."""
    normalized = unit.lower().strip()
    if normalized in {"mi", "mile", "miles"}:
        return round(float(value) * 1.609344, 4)
    if normalized in {"m", "meter", "meters", "metre", "metres"}:
        return round(float(value) / 1000, 4)
    return round(float(value), 4)


def new_dog(dog_id: str, name: str, profile: dict[str, Any] | None = None) -> dict[str, Any]:
    """Create a complete dog record."""
    now = utcnow_iso()
    return {
        "id": dog_id,
        "name": name.strip(),
        "profile": profile or {},
        "medications": [],
        "vaccinations": [],
        "appointments": [],
        "foods": [],
        "treats": [],
        "documents": [],
        "created_at": now,
        "updated_at": now,
    }


def events_for_dog(events: Iterable[dict[str, Any]], dog_id: str) -> list[dict[str, Any]]:
    """Return newest-first events belonging to a dog."""
    matches = [event for event in events if dog_id in event.get("dog_ids", [])]
    return sorted(matches, key=lambda item: item.get("occurred_at", ""), reverse=True)


def last_event(events: Iterable[dict[str, Any]], dog_id: str, event_type: str) -> dict[str, Any] | None:
    """Return the newest matching event."""
    return next(
        (event for event in events_for_dog(events, dog_id) if event.get("type") == event_type),
        None,
    )


def active_walk(events: Iterable[dict[str, Any]], dog_id: str) -> dict[str, Any] | None:
    """Return the newest open walk."""
    return next(
        (
            event
            for event in events_for_dog(events, dog_id)
            if event.get("type") == "walk" and not event.get("data", {}).get("ended_at")
        ),
        None,
    )


def exercise_minutes_today(events: Iterable[dict[str, Any]], dog_id: str, now: datetime | None = None) -> int:
    """Calculate completed and active exercise minutes for the local day."""
    now = now or dt_util.utcnow()
    local_now = dt_util.as_local(now)
    total = 0.0
    for event in events_for_dog(events, dog_id):
        if event.get("type") != "walk":
            continue
        started = parse_datetime(event.get("data", {}).get("started_at") or event.get("occurred_at"))
        if started is None or dt_util.as_local(started).date() != local_now.date():
            continue
        ended = parse_datetime(event.get("data", {}).get("ended_at")) or now
        total += max(0.0, (ended - started).total_seconds() / 60)
    return round(total)


def _schedule_candidates(medication: dict[str, Any], now: datetime) -> list[datetime]:
    schedule = medication.get("schedule", {})
    times = schedule.get("times", [])
    weekdays = set(schedule.get("weekdays", range(7)))
    local_now = dt_util.as_local(now)
    candidates: list[datetime] = []
    for day_delta in range(-7, 8):
        day = local_now.date() + timedelta(days=day_delta)
        if day.weekday() not in weekdays:
            continue
        for raw_time in times:
            try:
                hour, minute = (int(part) for part in raw_time.split(":", 1))
            except (TypeError, ValueError):
                continue
            local_value = datetime.combine(day, datetime.min.time(), dt_util.DEFAULT_TIME_ZONE).replace(
                hour=hour, minute=minute
            )
            candidate = dt_util.as_utc(local_value)
            start = parse_datetime(medication.get("start_date"))
            end = parse_datetime(medication.get("end_date"))
            if start and candidate < start:
                continue
            if end and candidate > end + timedelta(days=1):
                continue
            candidates.append(candidate)
    return sorted(candidates)


def next_medication(dog: dict[str, Any], now: datetime | None = None) -> tuple[dict[str, Any], datetime] | None:
    """Return the next active scheduled medication."""
    now = now or dt_util.utcnow()
    choices: list[tuple[dict[str, Any], datetime]] = []
    for medication in dog.get("medications", []):
        if not medication.get("active", True) or medication.get("as_needed"):
            continue
        choices.extend((medication, value) for value in _schedule_candidates(medication, now) if value >= now)
    return min(choices, key=lambda choice: choice[1]) if choices else None


def matching_medication_occurrence(
    dog: dict[str, Any], medication_id: str, now: datetime | None = None
) -> datetime | None:
    """Match an unscheduled dose log to the nearest sensible occurrence."""
    now = now or dt_util.utcnow()
    medication = next(
        (item for item in dog.get("medications", []) if item.get("id") == medication_id),
        None,
    )
    if not medication or medication.get("as_needed"):
        return None
    candidates = _schedule_candidates(medication, now)
    if not candidates:
        return None
    grace = timedelta(minutes=int(medication.get("grace_minutes", 60)))
    nearby = [candidate for candidate in candidates if abs(candidate - now) <= grace]
    if nearby:
        return min(nearby, key=lambda candidate: abs(candidate - now))
    past = [candidate for candidate in candidates if candidate <= now]
    return max(past) if past else min(candidates)


def overdue_medications(
    dog: dict[str, Any], events: Iterable[dict[str, Any]], now: datetime | None = None
) -> list[dict[str, Any]]:
    """Return unacknowledged scheduled medication occurrences beyond their grace window."""
    now = now or dt_util.utcnow()
    results: list[dict[str, Any]] = []
    dog_events = events_for_dog(events, dog["id"])
    for medication in dog.get("medications", []):
        if not medication.get("active", True) or medication.get("as_needed"):
            continue
        grace = int(medication.get("grace_minutes", 60))
        past = [value for value in _schedule_candidates(medication, now) if value < now - timedelta(minutes=grace)]
        if not past:
            continue
        scheduled_for = max(past)
        acknowledged = any(
            event.get("type") == "medication"
            and event.get("data", {}).get("medication_id") == medication.get("id")
            and parse_datetime(event.get("data", {}).get("scheduled_for")) == scheduled_for
            for event in dog_events
        )
        if not acknowledged:
            results.append(
                {
                    "medication_id": medication.get("id"),
                    "name": medication.get("name", "Medication"),
                    "scheduled_for": scheduled_for.isoformat(),
                }
            )
    return results


def attention_items(
    dog: dict[str, Any], events: Iterable[dict[str, Any]], settings: dict[str, Any], now: datetime | None = None
) -> list[dict[str, Any]]:
    """Build the compact needs-attention list."""
    now = now or dt_util.utcnow()
    items = [{"kind": "medication", "severity": "overdue", **item} for item in overdue_medications(dog, events, now)]
    appointment_cutoff = now + timedelta(hours=int(settings.get("appointment_attention_hours", 24)))
    vaccination_cutoff = now + timedelta(days=int(settings.get("vaccination_attention_days", 30)))
    expiry_cutoff = now + timedelta(days=int(settings.get("expiry_attention_days", 30)))
    for appointment in dog.get("appointments", []):
        start = parse_datetime(appointment.get("start"))
        if start and now <= start <= appointment_cutoff:
            items.append(
                {"kind": "appointment", "severity": "due", "name": appointment.get("title"), "at": start.isoformat()}
            )
    for vaccination in dog.get("vaccinations", []):
        due = parse_datetime(vaccination.get("due_at") or vaccination.get("due_date"))
        if due and due <= vaccination_cutoff:
            items.append(
                {
                    "kind": "vaccination",
                    "severity": "overdue" if due < now else "due",
                    "name": vaccination.get("name"),
                    "at": due.isoformat(),
                }
            )
    profile = dog.get("profile", {})
    for kind, value in (
        ("insurance", profile.get("insurance_renewal")),
        ("registration", profile.get("registration_expiry")),
    ):
        due = parse_datetime(value)
        if due and due <= expiry_cutoff:
            items.append(
                {
                    "kind": kind,
                    "severity": "overdue" if due < now else "due",
                    "name": kind.title(),
                    "at": due.isoformat(),
                }
            )
    return sorted(items, key=lambda item: item.get("at") or item.get("scheduled_for") or "")
