"""Shared entity support for Dog Assistant."""

from __future__ import annotations

from typing import Any

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from . import DogAssistantConfigEntry
from .const import DOMAIN
from .storage import DogAssistantManager


class DogAssistantEntity(Entity):
    """Base entity bound to a dog device."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _update_kinds: frozenset[str] | None = None

    def __init__(
        self,
        entry: DogAssistantConfigEntry,
        subentry_id: str,
        dog_id: str,
        manager: DogAssistantManager,
        key: str,
    ) -> None:
        self.entry = entry
        self.subentry_id = subentry_id
        self._attr_config_subentry_id = subentry_id
        self.dog_id = dog_id
        self.manager = manager
        self._attr_unique_id = f"{dog_id}_{key}"

    @property
    def dog(self) -> dict[str, Any]:
        """Return the live dog record."""
        return self.manager.data["dogs"][self.dog_id]

    @property
    def device_info(self) -> DeviceInfo:
        """Return device registry information."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.dog_id)},
            name=self.dog.get("name", "Dog"),
            manufacturer="Dog Assistant",
            model="Pet profile",
            entry_type=None,
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose only the stable identifier needed by the card."""
        return {"dog_id": self.dog_id}

    async def async_added_to_hass(self) -> None:
        """Subscribe to manager updates."""
        self.async_on_remove(self.manager.async_subscribe(self._handle_manager_update))

    @callback
    def _handle_manager_update(self, change: dict[str, Any]) -> None:
        if self.dog_id in change.get("dog_ids", []) and (
            self._update_kinds is None or change.get("kind") in self._update_kinds
        ):
            self.async_write_ha_state()


def dog_subentries(entry: DogAssistantConfigEntry):
    """Yield valid dog subentries and IDs."""
    for subentry in entry.subentries.values():
        dog_id = subentry.unique_id or subentry.subentry_id
        if dog_id in entry.runtime_data.manager.data["dogs"]:
            yield subentry, dog_id
