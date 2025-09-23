from __future__ import annotations

from typing import Any, Dict

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant

from .const import (
    DOMAIN,
    CONF_HOST,
    CONF_API_TOKEN,
    CONF_VERIFY_SSL,
    DEFAULT_VERIFY_SSL,
)


DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_API_TOKEN): str,
        vol.Optional(CONF_VERIFY_SSL, default=DEFAULT_VERIFY_SSL): bool,
    }
)


async def validate_input(_: HomeAssistant, data: Dict[str, Any]) -> Dict[str, Any]:
    """Milestone 0: no network calls; just basic validation."""
    host = data[CONF_HOST].strip()
    if not host:
        raise ValueError("Host must not be empty.")
    return {"title": f"Crestron Home @ {host}"}


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Crestron Home."""

    VERSION = 1
    MINOR_VERSION = 0

    async def async_step_user(self, user_input: Dict[str, Any] | None = None):
        errors: Dict[str, str] = {}

        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)

                # Use host as unique ID; prevents duplicates
                await self.async_set_unique_id(user_input[CONF_HOST].strip())
                self._abort_if_unique_id_configured()

                return self.async_create_entry(title=info["title"], data=user_input)
            except Exception:
                errors["base"] = "unknown"

        return self.async_show_form(step_id="user", data_schema=DATA_SCHEMA, errors=errors)
