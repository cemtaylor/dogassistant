"""Dog profile image entities."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.image import ImageEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import DogAssistantConfigEntry
from .entity import DogAssistantEntity, dog_subentries
from .models import parse_datetime


class DogProfileImage(DogAssistantEntity, ImageEntity):
    """Profile image backed by an uploaded document."""

    _attr_translation_key = "profile_image"
    _update_kinds = frozenset({"profile", "documents"})

    def __init__(self, hass: HomeAssistant, *args, **kwargs) -> None:
        ImageEntity.__init__(self, hass)
        DogAssistantEntity.__init__(self, *args, **kwargs)

    @property
    def image_last_updated(self) -> datetime | None:
        document_id = self.dog.get("profile", {}).get("photo_document_id")
        found = self.manager.find_document(document_id) if document_id else None
        return parse_datetime(found[1].get("uploaded_at")) if found else None

    @property
    def content_type(self) -> str:
        document_id = self.dog.get("profile", {}).get("photo_document_id")
        found = self.manager.find_document(document_id) if document_id else None
        return found[1].get("content_type", "image/jpeg") if found else "image/jpeg"

    async def async_image(self) -> bytes | None:
        document_id = self.dog.get("profile", {}).get("photo_document_id")
        found = self.manager.find_document(document_id) if document_id else None
        if not found:
            return None
        _, metadata = found
        path = self.manager.document_directory / metadata["stored_name"]
        if not path.is_file():
            return None
        return await self.hass.async_add_executor_job(path.read_bytes)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DogAssistantConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create profile image entities."""
    manager = entry.runtime_data.manager
    for subentry, dog_id in dog_subentries(entry):
        async_add_entities(
            [DogProfileImage(hass, entry, subentry.subentry_id, dog_id, manager, key="profile_image")],
            config_subentry_id=subentry.subentry_id,
        )
