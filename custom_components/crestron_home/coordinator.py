from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator


class CrestronHomeCoordinator(DataUpdateCoordinator):
    """Placeholder DataUpdateCoordinator (Milestone 0)."""

    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(hass, logger=hass.logger, name="Crestron Home", update_interval=None)

    async def _async_update_data(self):
        # Will be implemented in later milestones
        return {}
