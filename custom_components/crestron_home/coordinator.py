"""Data coordinator for Crestron Home shades."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
import time
from typing import Any, Sequence

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util.dt import utcnow

from .api import ApiClient, CannotConnectError, CrestronHomeApiError
from .calibration import CalibrationCollection, raw_to_pct
from .const import (
    DOMAIN,
    SHADE_BOOST_SECONDS,
    SHADE_BURST_SECONDS,
    SHADE_POLL_INTERVAL_BURST,
    SHADE_POLL_INTERVAL_FAST,
    SHADE_POLL_INTERVAL_IDLE,
    SHADE_POSITION_MAX,
)
from .predictive_stop import PlanResult, PredictiveRuntime

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

    def __init__(
        self,
        hass: HomeAssistant,
        client: ApiClient,
        entry: ConfigEntry,
        predictive: PredictiveRuntime,
        calibrations: CalibrationCollection,
    ) -> None:
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
        self._burst_interval = timedelta(seconds=SHADE_POLL_INTERVAL_BURST)
        self._boost_until: datetime | None = None
        self._burst_until: datetime | None = None
        self._last_payload: list[Any] = []
        self._predictive = predictive
        self._calibrations = calibrations

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
        self.hass.async_create_task(self.async_request_refresh())

    def burst(self, seconds: float = SHADE_BURST_SECONDS) -> None:
        if seconds <= 0:
            return

        until = utcnow() + timedelta(seconds=seconds)
        if self._burst_until is None or until > self._burst_until:
            self._burst_until = until
        self._refresh_polling_interval()
        self.hass.async_create_task(self.async_request_refresh())

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

        monotonic_now = time.monotonic()
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

            if shade.position is not None:
                calibration = self._calibrations.for_shade(shade.id)
                invert = calibration.resolved_invert(self._calibrations.global_invert)
                pct = raw_to_pct(shade.position, calibration.anchors, invert)
                if pct is not None:
                    self._predictive.record_poll(
                        shade_id=shade.id,
                        timestamp=monotonic_now,
                        position=pct / 100.0,
                    )

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
        now = utcnow()
        if self._boost_until is not None and self._boost_until <= now:
            self._boost_until = None
        if self._burst_until is not None and self._burst_until <= now:
            self._burst_until = None

        if self._burst_until:
            target = self._burst_interval
        elif self._boost_until:
            target = self._fast_interval
        else:
            target = self._idle_interval
        if self.update_interval != target:
            self.update_interval = target

    def bump_fast_poll(self, seconds: float = SHADE_BOOST_SECONDS) -> None:
        """Public helper to temporarily poll faster after a write."""

        self.boost(seconds)

    @property
    def predictive(self) -> PredictiveRuntime:
        return self._predictive

    def plan_stop(self, shade_ids: Sequence[str]) -> PlanResult:
        now = time.monotonic()
        return self._predictive.plan_stop(shade_ids, timestamp=now)
