"""Per-dog care buttons for dashboards and automations."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import DogAssistantConfigEntry
from .const import DOMAIN
from .entity import DogAssistantEntity, dog_subentries

# Keep logging in the existing actions so validation and attribution stay shared.
CARE_BUTTONS = (
    ("fed", "log_meal", {}, "mdi:food-drumstick"),
    ("water", "log_water", {}, "mdi:water"),
    ("treat", "log_treat", {}, "mdi:bone"),
    ("pee", "log_toilet", {"kind": "urine"}, "mdi:water-outline"),
    ("poo", "log_toilet", {"kind": "stool"}, "mdi:emoticon-poop"),
    ("start_walk", "start_walk", {}, "mdi:walk"),
    ("end_walk", "end_walk", {}, "mdi:flag-checkered"),
    ("log_walk", "log_walk", {}, "mdi:paw"),
)


class DogCareButton(DogAssistantEntity, ButtonEntity):
    """Log care for this dog using the integration's validated actions."""

    def __init__(self, *args, service: str, payload: dict, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._service = service
        self._payload = payload

    async def async_press(self) -> None:
        """Record care, preserving the calling automation's context."""
        await self.hass.services.async_call(
            DOMAIN,
            self._service,
            {"dog_id": self.dog_id, **self._payload},
            blocking=True,
            context=self._context,
        )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DogAssistantConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the care buttons on each dog's device."""
    for subentry, dog_id in dog_subentries(entry):
        entities = []
        for key, service, payload, icon in CARE_BUTTONS:
            button = DogCareButton(
                entry, subentry.subentry_id, dog_id, entry.runtime_data.manager,
                key=f"button_{key}", service=service, payload=payload,
            )
            button.entity_description = ButtonEntityDescription(key=key, translation_key=key, icon=icon)
            entities.append(button)
        async_add_entities(entities, config_subentry_id=subentry.subentry_id)
