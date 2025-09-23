"""Crestron Home custom integration (Milestone 0 scaffold)."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

# No platforms yet for Milestone 0 (will add "cover" in later milestones)
PLATFORMS: list[str] = []


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up integration via YAML (unsupported). Always return True."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Crestron Home from a ConfigEntry (scaffold)."""
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {}
    # Intentionally not forwarding platforms in Milestone 0.
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a ConfigEntry."""
    hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return True
