"""Crestron Home integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_VERIFY_SSL, Platform
from homeassistant.core import HomeAssistant

from .api import ApiClient
from .const import (
    CONF_API_TOKEN,
    DATA_API_CLIENT,
    DATA_SHADES_COORDINATOR,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
)
from .coordinator import ShadesCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.COVER]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Crestron Home from a config entry."""

    hass.data.setdefault(DOMAIN, {})

    host = entry.data[CONF_HOST]
    api_token = entry.data[CONF_API_TOKEN]
    verify_ssl = entry.data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)

    _LOGGER.debug("Creating API client for %s", host)
    client = ApiClient(hass, host, api_token, verify_ssl=verify_ssl)

    coordinator = ShadesCoordinator(hass, client, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = {
        DATA_API_CLIENT: client,
        DATA_SHADES_COORDINATOR: coordinator,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Crestron Home config entry."""

    _LOGGER.debug("Unload requested for config entry %s", entry.entry_id)

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False

    domain_data: dict[str, Any] | None = hass.data.get(DOMAIN)
    if domain_data is None:
        return True

    stored = domain_data.pop(entry.entry_id, {})
    client: ApiClient | None = stored.get(DATA_API_CLIENT)
    if client is not None:
        await client.async_logout()

    if not domain_data:
        hass.data.pop(DOMAIN)

    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle config entry updates (options)."""

    await hass.config_entries.async_reload(entry.entry_id)
