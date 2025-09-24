"""Config flow for the Crestron Home integration."""
from __future__ import annotations

from homeassistant import config_entries

from .const import DOMAIN


class CrestronHomeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Crestron Home."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step of the flow."""
        return self.async_abort(reason="not_implemented")

