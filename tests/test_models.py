"""Tests for side-effect-free data calculations."""

from custom_components.dogassistant.models import (
    active_walk,
    events_for_dog,
    normalize_distance,
    normalize_weight,
)


def test_unit_normalization() -> None:
    assert normalize_weight(10, "lb") == 4.5359
    assert normalize_weight(500, "g") == 0.5
    assert normalize_weight(12.5, "kg") == 12.5
    assert normalize_distance(1, "mi") == 1.6093
    assert normalize_distance(500, "m") == 0.5


def test_events_are_filtered_and_sorted() -> None:
    events = [
        {"id": "old", "dog_ids": ["a"], "occurred_at": "2026-01-01T00:00:00+00:00"},
        {"id": "other", "dog_ids": ["b"], "occurred_at": "2026-03-01T00:00:00+00:00"},
        {"id": "new", "dog_ids": ["a", "b"], "occurred_at": "2026-02-01T00:00:00+00:00"},
    ]
    assert [event["id"] for event in events_for_dog(events, "a")] == ["new", "old"]


def test_active_walk() -> None:
    events = [
        {
            "id": "done",
            "type": "walk",
            "dog_ids": ["a"],
            "occurred_at": "2026-01-01T00:00:00+00:00",
            "data": {"ended_at": "2026-01-01T01:00:00+00:00"},
        },
        {
            "id": "open",
            "type": "walk",
            "dog_ids": ["a"],
            "occurred_at": "2026-02-01T00:00:00+00:00",
            "data": {"started_at": "2026-02-01T00:00:00+00:00"},
        },
    ]
    assert active_walk(events, "a")["id"] == "open"
