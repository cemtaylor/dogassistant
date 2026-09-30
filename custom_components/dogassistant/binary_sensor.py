"""Dog Assistant binary sensors."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import DogAssistantConfigEntry
from .entity import DogAssistantEntity, dog_subentries
from .models import active_walk, attention_items, overdue_medications


class WalkActiveSensor(DogAssistantEntity, BinarySensorEntity):
    """Whether a walk timer is open."""

    _attr_translation_key = "walk_active"
    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _update_kinds = frozenset({"event:walk"})

    @property
    def is_on(self) -> bool:
        return active_walk(self.manager.data["events"], self.dog_id) is not None


class MedicationOverdueSensor(DogAssistantEntity, BinarySensorEntity):
    """Whether any scheduled medication is overdue."""

    _attr_translation_key = "medication_overdue"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _update_kinds = frozenset({"medications", "event:medication"})

    @property
    def is_on(self) -> bool:
        return bool(overdue_medications(self.dog, self.manager.data["events"]))


class CareAttentionSensor(DogAssistantEntity, BinarySensorEntity):
    """Whether any care item needs attention."""

    _attr_translation_key = "care_attention"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _update_kinds = frozenset({"medications", "appointments", "vaccinations", "profile", "event:medication"})

    @property
    def is_on(self) -> bool:
        return bool(attention_items(self.dog, self.manager.data["events"], self.manager.data["settings"]))


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DogAssistantConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create binary sensors."""
    manager = entry.runtime_data.manager
    for subentry, dog_id in dog_subentries(entry):
        common = (entry, subentry.subentry_id, dog_id, manager)
        entities: list[BinarySensorEntity] = [
            WalkActiveSensor(*common, key="walk_active"),
            MedicationOverdueSensor(*common, key="medication_overdue"),
            CareAttentionSensor(*common, key="care_attention"),
        ]
        async_add_entities(
            entities,
            config_subentry_id=subentry.subentry_id,
        )
