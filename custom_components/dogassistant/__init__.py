"""Dog Assistant integration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN as DOMAIN
from .const import FRONTEND_URL, PLATFORMS, SUBENTRY_TYPE_DOG
from .http import register_http_views
from .services import async_register_services, async_unregister_services
from .storage import DogAssistantManager
from .websocket import async_register_websocket_commands

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


@dataclass
class DogAssistantData:
    """Runtime data for the household entry."""

    manager: DogAssistantManager


type DogAssistantConfigEntry = ConfigEntry[DogAssistantData]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register global API surfaces."""
    frontend_path = Path(__file__).parent / "frontend"
    await hass.http.async_register_static_paths(
        [StaticPathConfig(FRONTEND_URL, str(frontend_path / "dogassistant-card.js"), True)]
    )
    register_http_views(hass)
    async_register_websocket_commands(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: DogAssistantConfigEntry) -> bool:
    """Set up the household and its dogs."""
    manager = DogAssistantManager(hass)
    await manager.async_load()
    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_TYPE_DOG:
            continue
        await manager.async_ensure_dog(
            subentry.unique_id or subentry.subentry_id,
            subentry.data.get("name", subentry.title),
            subentry.data.get("profile", {}),
        )
    entry.runtime_data = DogAssistantData(manager)
    entry.async_on_unload(entry.add_update_listener(_async_update_entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    async_register_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: DogAssistantConfigEntry) -> bool:
    """Unload the integration."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        async_unregister_services(hass)
    return unloaded


async def _async_update_entry(hass: HomeAssistant, entry: DogAssistantConfigEntry) -> None:
    """Reload after a dog subentry is added, changed, or removed."""
    await hass.config_entries.async_reload(entry.entry_id)
