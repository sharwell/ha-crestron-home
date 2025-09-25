"""Persistence helpers for predictive stop parameters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store


@dataclass
class PredictiveStoreData:
    version: int
    shades: Dict[str, Any]


class PredictiveStopStore:
    """Per-config-entry storage for predictive stop learning."""

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        entry_id: str,
        version: int,
        key_prefix: str,
    ) -> None:
        self._store = Store(hass, version, f"{key_prefix}_{entry_id}")
        self._version = version

    async def async_load(self) -> PredictiveStoreData:
        raw = await self._store.async_load()
        if not raw or not isinstance(raw, dict):
            return PredictiveStoreData(version=self._version, shades={})
        shades = raw.get("shades")
        if not isinstance(shades, dict):
            shades = {}
        return PredictiveStoreData(version=self._version, shades=dict(shades))

    async def async_save(self, data: PredictiveStoreData) -> None:
        await self._store.async_save({"version": data.version, "shades": data.shades})

    async def async_clear_shade(self, shade_id: str) -> None:
        data = await self.async_load()
        if shade_id in data.shades:
            data.shades.pop(shade_id)
            await self.async_save(data)

