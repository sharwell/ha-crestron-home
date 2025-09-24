"""Config flow for the Crestron Home integration."""
from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import urlparse

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_VERIFY_SSL
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .api import ApiClient, CannotConnectError, CrestronHomeApiError, InvalidAuthError
from .const import (
    CONFIG_FLOW_TIMEOUT,
    CONF_API_TOKEN,
    CONF_INVERT,
    DEFAULT_INVERT,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
)


_LOGGER = logging.getLogger(__name__)


class CrestronHomeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Crestron Home."""

    VERSION = 1

    def __init__(self) -> None:
        self._user_input: dict[str, Any] | None = None
        self._rooms_count: int = 0

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle the initial step of the config flow."""

        errors: dict[str, str] = {}
        submitted: dict[str, Any] | None = None

        if user_input is not None:
            submitted = dict(user_input)
            host = submitted.get(CONF_HOST, "").strip()
            if "://" in host:
                parsed = urlparse(host)
                if parsed.hostname:
                    host = parsed.hostname
                    if parsed.port:
                        host = f"{host}:{parsed.port}"
                else:
                    host = host.split("//", 1)[1]
            host = host.strip("/")
            submitted[CONF_HOST] = host
            submitted[CONF_API_TOKEN] = submitted.get(CONF_API_TOKEN, "").strip()
            submitted[CONF_VERIFY_SSL] = bool(
                submitted.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)
            )

            if self._host_already_configured(host):
                return self.async_abort(reason="already_configured")

            client = ApiClient(
                self.hass,
                host,
                submitted[CONF_API_TOKEN],
                verify_ssl=submitted[CONF_VERIFY_SSL],
            )

            request_details = {
                "host": host,
                "verify_ssl": submitted[CONF_VERIFY_SSL],
            }
            log_level = logging.DEBUG
            response_details: Any | Exception | None = None

            try:
                async with asyncio.timeout(CONFIG_FLOW_TIMEOUT):
                    rooms = await client.async_get_rooms()
            except asyncio.TimeoutError as err:
                log_level = logging.WARNING
                response_details = err
                errors["base"] = "cannot_connect"
            except InvalidAuthError as err:
                log_level = logging.WARNING
                response_details = err
                errors["base"] = "invalid_auth"
            except CannotConnectError as err:
                log_level = logging.WARNING
                response_details = err
                errors["base"] = "cannot_connect"
            except CrestronHomeApiError as err:
                log_level = logging.WARNING
                response_details = err
                errors["base"] = "unknown"
            else:
                response_details = rooms
                self._rooms_count = len(rooms)
                self._user_input = submitted
                return await self.async_step_confirm()
            finally:
                _LOGGER.log(log_level, "Connection test request: %s", request_details)
                _LOGGER.log(log_level, "Connection test response: %s", response_details)
                await client.async_logout()

        defaults = submitted or user_input or {}

        data_schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): str,
                vol.Required(CONF_API_TOKEN, default=""): str,
                vol.Optional(
                    CONF_VERIFY_SSL,
                    default=defaults.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
                ): bool,
            }
        )

        return self.async_show_form(step_id="user", data_schema=data_schema, errors=errors)

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Show confirmation step before creating the entry."""

        assert self._user_input is not None
        host = self._user_input[CONF_HOST]

        if user_input is None:
            return self.async_show_form(
                step_id="confirm",
                description_placeholders={
                    "host": host,
                    "rooms": str(self._rooms_count),
                },
            )

        await self.async_set_unique_id(host)
        self._abort_if_unique_id_configured()

        return self.async_create_entry(
            title=f"Crestron Home ({host})",
            data={
                CONF_HOST: host,
                CONF_API_TOKEN: self._user_input[CONF_API_TOKEN],
                CONF_VERIFY_SSL: bool(self._user_input.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)),
            },
            options={CONF_INVERT: DEFAULT_INVERT},
        )

    def _host_already_configured(self, host: str) -> bool:
        """Return True if the host already has a config entry."""

        normalized_host = host.lower()
        for entry in self._async_current_entries():
            existing_host = entry.data.get(CONF_HOST, "").lower()
            if existing_host == normalized_host:
                return True
        return False


class CrestronHomeOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options for the Crestron Home integration."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        return await self.async_step_options(user_input)

    async def async_step_options(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = self.config_entry.options
        data_schema = vol.Schema(
            {
                vol.Optional(
                    CONF_INVERT,
                    default=options.get(CONF_INVERT, DEFAULT_INVERT),
                ): bool,
            }
        )

        return self.async_show_form(
            step_id="options",
            data_schema=data_schema,
        )


@callback
def async_get_options_flow(config_entry: ConfigEntry) -> config_entries.OptionsFlow:
    """Create the options flow."""

    return CrestronHomeOptionsFlowHandler(config_entry)
