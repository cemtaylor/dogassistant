"""Config and dog subentry flows for Dog Assistant."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, ConfigSubentryFlow, SubentryFlowResult
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.selector import DateSelector, SelectSelector, SelectSelectorConfig, TextSelector

from .const import DOMAIN, NAME, SUBENTRY_TYPE_DOG


class DogAssistantConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Create the single household-level entry."""

    VERSION = 1
    MINOR_VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Set up Dog Assistant."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        if user_input is not None:
            return self.async_create_entry(title=NAME, data={})
        return self.async_show_form(step_id="user", data_schema=vol.Schema({}))

    @classmethod
    @callback
    def async_get_supported_subentry_types(cls, config_entry: ConfigEntry) -> dict[str, type[ConfigSubentryFlow]]:
        """Return supported subentry flows."""
        return {SUBENTRY_TYPE_DOG: DogSubentryFlowHandler}


class DogSubentryFlowHandler(ConfigSubentryFlow):
    """Add dogs beneath the household entry."""

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        """Create a dog."""
        if user_input is not None:
            dog_id = uuid4().hex
            profile = {
                key: value for key, value in user_input.items() if key not in {"name"} and value not in (None, "")
            }
            return self.async_create_entry(
                title=user_input["name"],
                data={"name": user_input["name"], "profile": profile},
                unique_id=dog_id,
            )
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("name"): TextSelector(),
                    vol.Optional("birth_date"): DateSelector(),
                    vol.Optional("adoption_date"): DateSelector(),
                    vol.Optional("breed"): TextSelector(),
                    vol.Optional("sex"): SelectSelector(
                        SelectSelectorConfig(options=["female", "male", "unknown"], mode="dropdown")
                    ),
                }
            ),
        )
