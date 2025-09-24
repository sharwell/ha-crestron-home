"""Config flow for the Crestron Home integration."""

from __future__ import annotations

from typing import Any

from homeassistant import config_entries

from .const import DOMAIN


class CrestronHomeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Crestron Home."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> config_entries.FlowResult:
        """Handle the initial step initiated by the user."""
        return self.async_abort(reason="setup_not_implemented")
