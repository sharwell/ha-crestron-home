"""Data coordinator for Crestron Home shades."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util.dt import utcnow

from .api import ApiClient, CannotConnectError, CrestronHomeApiError
from .const import (
    DOMAIN,
    SHADE_BOOST_SECONDS,
    SHADE_POLL_INTERVAL_FAST,
    SHADE_POLL_INTERVAL_IDLE,
    SHADE_POSITION_MAX,
)

__all__ = ["Shade", "ShadesCoordinator"]

_LOGGER = logging.getLogger(__name__)


def _normalize_room_id(raw: Any) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        value = raw.strip()
        return value or None
    return str(raw)


def _normalize_name(raw: Any, shade_id: str) -> str:
    if isinstance(raw, str):
        value = raw.strip()
        if value:
            return value
    return f"Shade {shade_id}"


def _normalize_position(raw: Any) -> int | None:
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        value = int(raw)
    elif isinstance(raw, str):
        stripped = raw.strip()
        if not stripped:
            return None
        try:
            value = int(float(stripped))
        except ValueError:
            return None
    else:
        return None

    if 0 <= value <= SHADE_POSITION_MAX:
        return value
    return None


def _is_connected(status: Any) -> bool:
    if status is None:
        return False
    if isinstance(status, bool):
        return status
    if isinstance(status, (int, float)):
        return status != 0
    if isinstance(status, str):
        value = status.strip().lower()
        if not value:
            return False
        if value in {"connected", "online", "true", "1"}:
            return True
        if value in {"disconnected", "offline", "false", "0"}:
            return False
        # Unknown string values should be treated as unavailable.
        return False
    return bool(status)


@dataclass
class Shade:
    """Representation of a Crestron Home shade."""

    id: str
    name: str
    position: int | None
    connection_status: Any
    room_id: str | None
    updated_at: datetime
    raw: dict[str, Any]

    @property
    def is_connected(self) -> bool:
        return _is_connected(self.connection_status)


class ShadesCoordinator(DataUpdateCoordinator[dict[str, Shade]]):
    """Coordinate shade state updates from the Crestron Home controller."""

    def __init__(self, hass: HomeAssistant, client: ApiClient, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} shades",
            update_interval=timedelta(seconds=SHADE_POLL_INTERVAL_IDLE),
        )
        self._client = client
        self.config_entry = entry
        self._idle_interval = timedelta(seconds=SHADE_POLL_INTERVAL_IDLE)
        self._fast_interval = timedelta(seconds=SHADE_POLL_INTERVAL_FAST)
        self._boost_until: datetime | None = None
        self._last_payload: list[Any] = []

    @property
    def client(self) -> ApiClient:
        """Return the API client."""

        return self._client

    @property
    def last_payload(self) -> list[Any]:
        """Return the last raw payload returned by the controller."""

        return self._last_payload

    def boost(self, seconds: float = SHADE_BOOST_SECONDS) -> None:
        """Temporarily poll faster for shade updates."""

        if seconds <= 0:
            return

        until = utcnow() + timedelta(seconds=seconds)
        if self._boost_until is None or until > self._boost_until:
            self._boost_until = until
        self._refresh_polling_interval()
        self.async_request_refresh()

    async def _async_update_data(self) -> dict[str, Shade]:
        """Fetch shade data from the controller."""

        self._refresh_polling_interval()

        try:
            payload = await self._client.async_get_shades()
        except (CannotConnectError, CrestronHomeApiError) as err:
            raise UpdateFailed(str(err)) from err

        now = utcnow()
        shades: dict[str, Shade] = {}
        previous_data: dict[str, Shade] = self.data or {}
        position_changed = False

        if not isinstance(payload, list):
            raise UpdateFailed("Shades payload was not a list")

        for item in payload:
            if not isinstance(item, dict):
                _LOGGER.debug("Skipping shade entry because it is not a dict: %s", item)
                continue

            raw_id = item.get("id")
            if raw_id is None:
                _LOGGER.debug("Skipping shade entry without an id: %s", item)
                continue

            shade_id = str(raw_id)
            name = _normalize_name(item.get("name"), shade_id)
            position = _normalize_position(item.get("position"))
            if "connectionStatus" in item:
                connection_status = item.get("connectionStatus")
            else:
                connection_status = item.get("connection_status")
            if "roomId" in item:
                room_raw = item.get("roomId")
            else:
                room_raw = item.get("room_id")
            room_id = _normalize_room_id(room_raw)

            shade = Shade(
                id=shade_id,
                name=name,
                position=position,
                connection_status=connection_status,
                room_id=room_id,
                updated_at=now,
                raw=item,
            )

            shades[shade.id] = shade

            if not position_changed:
                previous = previous_data.get(shade.id)
                if previous is not None and previous.position != shade.position:
                    position_changed = True

        self._last_payload = payload
        if position_changed:
            self.boost()
        self._refresh_polling_interval()
        return shades

    def _refresh_polling_interval(self) -> None:
        if self._boost_until is not None and self._boost_until <= utcnow():
            self._boost_until = None

        target = self._fast_interval if self._boost_until else self._idle_interval
        if self.update_interval != target:
            self.update_interval = target
