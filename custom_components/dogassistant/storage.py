"""Persistent data manager for Dog Assistant."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any
from uuid import uuid4

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    DEFAULT_SETTINGS,
    MAX_DOCUMENT_STORAGE_BYTES,
    MAX_DOCUMENTS,
    MAX_EVENTS,
    STORAGE_KEY,
    STORAGE_MINOR_VERSION,
    STORAGE_VERSION,
)
from .models import new_dog, parse_datetime, utcnow_iso


class DogAssistantManager:
    """Own structured data and notify entities/card subscribers."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, STORAGE_KEY, minor_version=STORAGE_MINOR_VERSION
        )
        self.data: dict[str, Any] = {}
        self._lock = asyncio.Lock()
        self._listeners: set[Callable[[dict[str, Any]], None]] = set()

    @property
    def document_directory(self) -> Path:
        """Return the private document directory."""
        return Path(self.hass.config.path(".storage", "dogassistant", "documents"))

    async def async_load(self) -> None:
        """Load or initialize the store."""
        loaded = await self.store.async_load()
        self.data = loaded or {
            "settings": deepcopy(DEFAULT_SETTINGS),
            "dogs": {},
            "events": [],
        }
        self.data.setdefault("settings", deepcopy(DEFAULT_SETTINGS))
        self.data.setdefault("dogs", {})
        self.data.setdefault("events", [])
        migrated = False
        for dog in self.data["dogs"].values():
            for kind in ("foods", "treats", "commands"):
                if kind not in dog:
                    dog[kind] = []
                    migrated = True
        if migrated:
            await self.store.async_save(self.data)
        await self.hass.async_add_executor_job(self.document_directory.mkdir, 0o700, True, True)

    async def _async_commit(self, change: dict[str, Any]) -> None:
        await self.store.async_save(self.data)
        for listener in tuple(self._listeners):
            listener(change)

    @callback
    def async_subscribe(self, listener: Callable[[dict[str, Any]], None]) -> Callable[[], None]:
        """Subscribe to data mutations."""
        self._listeners.add(listener)

        @callback
        def unsubscribe() -> None:
            self._listeners.discard(listener)

        return unsubscribe

    def snapshot(self) -> dict[str, Any]:
        """Return a safe copy for APIs and export."""
        return deepcopy(self.data)

    def get_dog(self, dog_id: str) -> dict[str, Any] | None:
        """Return a dog by stable ID."""
        dog = self.data["dogs"].get(dog_id)
        return deepcopy(dog) if dog else None

    def document_usage(self) -> tuple[int, int]:
        """Return the stored document count and declared byte total."""
        documents = [document for dog in self.data["dogs"].values() for document in dog.get("documents", [])]
        return len(documents), sum(int(document.get("size", 0)) for document in documents)

    def can_store_document(self, size: int) -> bool:
        """Return whether another document fits within household limits."""
        count, used = self.document_usage()
        return count < MAX_DOCUMENTS and used + size <= MAX_DOCUMENT_STORAGE_BYTES

    async def async_ensure_dog(self, dog_id: str, name: str, profile: dict[str, Any] | None = None) -> dict[str, Any]:
        """Create the storage record for a config subentry."""
        async with self._lock:
            if dog_id not in self.data["dogs"]:
                self.data["dogs"][dog_id] = new_dog(dog_id, name, profile)
                await self._async_commit({"kind": "dog_created", "dog_ids": [dog_id]})
            return deepcopy(self.data["dogs"][dog_id])

    async def async_update_profile(self, dog_id: str, name: str | None, profile: dict[str, Any]) -> dict[str, Any]:
        """Update the dog profile."""
        async with self._lock:
            dog = self.data["dogs"][dog_id]
            if name is not None and name.strip():
                dog["name"] = name.strip()
            dog["profile"] = deepcopy(profile)
            dog["updated_at"] = utcnow_iso()
            await self._async_commit({"kind": "profile", "dog_ids": [dog_id]})
            return deepcopy(dog)

    async def async_add_event(self, event: dict[str, Any]) -> dict[str, Any]:
        """Create a care event."""
        async with self._lock:
            now = utcnow_iso()
            stored = deepcopy(event)
            stored.setdefault("id", uuid4().hex)
            stored.setdefault("occurred_at", now)
            stored["created_at"] = now
            stored["updated_at"] = now
            self.data["events"].append(stored)
            if len(self.data["events"]) > MAX_EVENTS:
                self.data["events"] = sorted(self.data["events"], key=lambda item: item.get("occurred_at", ""))[
                    -MAX_EVENTS:
                ]
            await self._async_commit({"kind": f"event:{stored['type']}", "dog_ids": stored["dog_ids"]})
            return deepcopy(stored)

    async def async_update_event(self, event_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        """Update a care event."""
        async with self._lock:
            event = next(item for item in self.data["events"] if item["id"] == event_id)
            allowed = {"dog_ids", "occurred_at", "caregiver", "notes", "data"}
            event.update({key: deepcopy(value) for key, value in changes.items() if key in allowed})
            event["updated_at"] = utcnow_iso()
            await self._async_commit({"kind": f"event:{event['type']}", "dog_ids": event["dog_ids"]})
            return deepcopy(event)

    async def async_delete_event(self, event_id: str) -> bool:
        """Delete a care event."""
        async with self._lock:
            for index, event in enumerate(self.data["events"]):
                if event["id"] == event_id:
                    removed = self.data["events"].pop(index)
                    await self._async_commit({"kind": f"event:{removed['type']}", "dog_ids": removed["dog_ids"]})
                    return True
            return False

    async def async_undo_event(self, event_id: str, user_id: str, max_age_seconds: int = 30) -> str:
        """Undo a newly created event owned by a household user."""
        async with self._lock:
            for index, event in enumerate(self.data["events"]):
                if event["id"] != event_id:
                    continue
                if event.get("created_by_user_id") != user_id:
                    return "forbidden"
                created_at = parse_datetime(event.get("created_at"))
                if created_at is None or (dt_util.utcnow() - created_at).total_seconds() > max_age_seconds:
                    return "expired"
                removed = self.data["events"].pop(index)
                await self._async_commit({"kind": f"event:{removed['type']}", "dog_ids": removed["dog_ids"]})
                return "deleted"
            return "not_found"

    async def async_upsert_record(self, dog_id: str, kind: str, record: dict[str, Any]) -> dict[str, Any]:
        """Create or update a structured dog record."""
        async with self._lock:
            records = self.data["dogs"][dog_id][kind]
            stored = deepcopy(record)
            stored.setdefault("created_at", utcnow_iso())
            stored["updated_at"] = utcnow_iso()
            requested_id = stored.get("id")
            for index, existing in enumerate(records):
                if requested_id and existing["id"] == requested_id:
                    stored["created_at"] = existing.get("created_at", stored["created_at"])
                    records[index] = stored
                    break
            else:
                stored["id"] = uuid4().hex
                records.append(stored)
            self.data["dogs"][dog_id]["updated_at"] = utcnow_iso()
            await self._async_commit({"kind": kind, "dog_ids": [dog_id]})
            return deepcopy(stored)

    async def async_delete_record(self, dog_id: str, kind: str, record_id: str) -> bool:
        """Delete a structured record."""
        async with self._lock:
            records = self.data["dogs"][dog_id][kind]
            for index, record in enumerate(records):
                if record["id"] == record_id:
                    records.pop(index)
                    await self._async_commit({"kind": kind, "dog_ids": [dog_id]})
                    return True
            return False

    async def async_add_document(self, dog_id: str, metadata: dict[str, Any]) -> dict[str, Any]:
        """Add document metadata after its file is safely written."""
        async with self._lock:
            stored = deepcopy(metadata)
            stored.setdefault("id", uuid4().hex)
            stored.setdefault("uploaded_at", utcnow_iso())
            self.data["dogs"][dog_id]["documents"].append(stored)
            await self._async_commit({"kind": "documents", "dog_ids": [dog_id]})
            return deepcopy(stored)

    def find_document(self, document_id: str) -> tuple[str, dict[str, Any]] | None:
        """Find document metadata and its owner."""
        for dog_id, dog in self.data["dogs"].items():
            for document in dog.get("documents", []):
                if document["id"] == document_id:
                    return dog_id, deepcopy(document)
        return None

    async def async_delete_document(self, document_id: str) -> dict[str, Any] | None:
        """Remove document metadata."""
        async with self._lock:
            for dog_id, dog in self.data["dogs"].items():
                for index, document in enumerate(dog.get("documents", [])):
                    if document["id"] == document_id:
                        removed = dog["documents"].pop(index)
                        await self._async_commit({"kind": "documents", "dog_ids": [dog_id]})
                        return removed
            return None
