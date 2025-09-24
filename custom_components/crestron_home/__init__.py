"""Crestron Home integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_VERIFY_SSL
from homeassistant.core import HomeAssistant

from .api import ApiClient
from .const import CONF_API_TOKEN, DEFAULT_VERIFY_SSL, DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Crestron Home from a config entry."""

    hass.data.setdefault(DOMAIN, {})

    host = entry.data[CONF_HOST]
    api_token = entry.data[CONF_API_TOKEN]
    verify_ssl = entry.data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)

    _LOGGER.debug("Creating API client for %s", host)
    client = ApiClient(hass, host, api_token, verify_ssl=verify_ssl)

    hass.data[DOMAIN][entry.entry_id] = client
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Crestron Home config entry."""

    _LOGGER.debug("Unload requested for config entry %s", entry.entry_id)

    domain_data = hass.data.get(DOMAIN)
    if domain_data is None:
        return True

    client: ApiClient | None = domain_data.pop(entry.entry_id, None)
    if client is not None:
        await client.async_logout()

    if not domain_data:
        hass.data.pop(DOMAIN)

    return True
