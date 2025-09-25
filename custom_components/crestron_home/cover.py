"""Cover platform for Crestron Home shades."""

from __future__ import annotations

import asyncio
import logging
import time

from typing import Any, cast

from homeassistant.components.cover import (
    ATTR_POSITION,
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .calibration import CalibrationCollection, pct_to_raw, raw_to_pct
from .const import (
    DATA_CALIBRATIONS,
    DATA_PREDICTIVE_STORAGE,
    DATA_WRITE_BATCHER,
    DATA_SHADES_COORDINATOR,
    DOMAIN,
    PREDICTIVE_STORAGE_VERSION,
)
from .coordinator import Shade, ShadesCoordinator
from .storage import PredictiveStopStore, PredictiveStoreData
from .write import ShadeWriteBatcher

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Crestron Home cover entities from a config entry."""

    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: ShadesCoordinator = data[DATA_SHADES_COORDINATOR]

    known_ids: set[str] = set()

    @callback
    def _add_new_entities() -> None:
        entities: list[CrestronHomeShade] = []
        data = coordinator.data or {}
        for shade_id in data:
            unique_id = CrestronHomeShade.compute_unique_id(entry, shade_id)
            if unique_id in known_ids:
                continue
            entities.append(CrestronHomeShade(coordinator, entry, shade_id))
            known_ids.add(unique_id)
        if entities:
            async_add_entities(entities)

    _add_new_entities()
    remove_listener = coordinator.async_add_listener(_add_new_entities)
    entry.async_on_unload(remove_listener)


class CrestronHomeShade(CoordinatorEntity[ShadesCoordinator], CoverEntity):
    """Representation of a Crestron Home shade as a Home Assistant cover."""

    _attr_device_class = CoverDeviceClass.SHADE
    _attr_should_poll = False
    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.SET_POSITION
        | CoverEntityFeature.STOP
    )

    def __init__(self, coordinator: ShadesCoordinator, entry: ConfigEntry, shade_id: str) -> None:
        super().__init__(coordinator)
        self.config_entry = entry
        self._shade_id = shade_id
        self._attr_unique_id = self.compute_unique_id(entry, shade_id)
        self._write_batcher = cast(
            ShadeWriteBatcher,
            coordinator.hass.data[DOMAIN][entry.entry_id][DATA_WRITE_BATCHER],
        )
        self._predictive_store = cast(
            PredictiveStopStore,
            coordinator.hass.data[DOMAIN][entry.entry_id][DATA_PREDICTIVE_STORAGE],
        )
        calibration_collection = cast(
            CalibrationCollection,
            coordinator.hass.data[DOMAIN][entry.entry_id][DATA_CALIBRATIONS],
        )
        self._calibration_collection = calibration_collection
        self._shade_calibration = calibration_collection.for_shade(shade_id)
        self._invert_axis = self._shade_calibration.resolved_invert(
            calibration_collection.global_invert
        )
        _LOGGER.debug(
            "Shade %s applying calibration with %d anchors (invert=%s)",
            shade_id,
            len(self._shade_calibration.anchors),
            self._invert_axis,
        )

    @staticmethod
    def compute_unique_id(entry: ConfigEntry, shade_id: str) -> str:
        host = entry.data.get(CONF_HOST, entry.unique_id or entry.entry_id)
        if host is None:
            host = entry.entry_id
        host_str = str(host).lower()
        return f"shade:{host_str}:{shade_id}"

    @property
    def shade(self) -> Shade | None:
        data = self.coordinator.data or {}
        return data.get(self._shade_id)

    @property
    def name(self) -> str | None:
        if shade := self.shade:
            return shade.name
        return None

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        shade = self.shade
        if shade is None:
            return False
        return shade.is_connected

    @property
    def device_info(self) -> DeviceInfo:
        host_value = self.config_entry.data.get(CONF_HOST)
        host = host_value or "Crestron Home"
        if host_value:
            host_identifier = str(host_value).lower()
        else:
            host_identifier = self.config_entry.entry_id
        entry_identifier = self.config_entry.unique_id or host_identifier
        return DeviceInfo(
            identifiers={(DOMAIN, entry_identifier)},
            manufacturer="Crestron",
            name=f"Crestron Home ({host})",
        )

    @property
    def current_cover_position(self) -> int | None:
        shade = self.shade
        if shade is None:
            return None
        position = raw_to_pct(shade.position, self._shade_calibration.anchors, self._invert_axis)
        return position

    @property
    def is_closed(self) -> bool | None:
        """Return whether the shade is closed."""

        position = self.current_cover_position
        if position is None:
            return None

        return position <= 0

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        shade = self.shade
        if shade is None:
            return None

        attributes: dict[str, Any] = {}
        if shade.connection_status is not None:
            attributes["connection_status"] = shade.connection_status
        if shade.room_id is not None:
            attributes["room_id"] = shade.room_id
        attributes["updated_at"] = shade.updated_at.isoformat()
        return attributes

    async def async_open_cover(self, **kwargs: Any) -> None:
        await self._async_enqueue_position(100)

    def open_cover(self, **kwargs: Any) -> None:
        asyncio.run_coroutine_threadsafe(
            self.async_open_cover(**kwargs),
            self.hass.loop,
        ).result()

    async def async_close_cover(self, **kwargs: Any) -> None:
        await self._async_enqueue_position(0)

    def close_cover(self, **kwargs: Any) -> None:
        asyncio.run_coroutine_threadsafe(
            self.async_close_cover(**kwargs),
            self.hass.loop,
        ).result()

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        if (position := kwargs.get(ATTR_POSITION)) is None:
            raise HomeAssistantError("Position value is required")
        await self._async_enqueue_position(int(position))

    def set_cover_position(self, **kwargs: Any) -> None:
        asyncio.run_coroutine_threadsafe(
            self.async_set_cover_position(**kwargs),
            self.hass.loop,
        ).result()

    async def async_stop_cover(self, **kwargs: Any) -> None:
        predictive = self.coordinator.predictive
        if predictive.enabled:
            shade_ids = predictive.moving_shades()
            if self._shade_id not in shade_ids:
                shade_ids.append(self._shade_id)
            plan = self.coordinator.plan_stop(shade_ids)
            calibrations = self._calibration_collection
            commands: list[tuple[str, int]] = []
            for target in plan.targets:
                cal = calibrations.for_shade(target.shade_id)
                invert = cal.resolved_invert(calibrations.global_invert)
                pct = int(round(max(0.0, min(1.0, target.position)) * 100))
                raw = pct_to_raw(pct, cal.anchors, invert)
                commands.append((target.shade_id, raw))
            if not commands:
                _LOGGER.debug("Shade %s predictive stop produced no targets", self._shade_id)
                return
            for shade_id, raw in commands:
                await self._write_batcher.enqueue(shade_id, raw)
            if plan.flush:
                await self._write_batcher.async_flush()
            self.coordinator.burst()
            await self._predictive_store.async_save(
                PredictiveStoreData(
                    version=PREDICTIVE_STORAGE_VERSION,
                    shades=predictive.serialize_learning(),
                )
            )
            return

        if (raw := self._resolve_current_raw_position()) is None:
            _LOGGER.debug(
                "Shade %s stop request skipped because position is unknown",
                self._shade_id,
            )
            return

        await self._write_batcher.enqueue(self._shade_id, raw)

    def stop_cover(self, **kwargs: Any) -> None:
        asyncio.run_coroutine_threadsafe(
            self.async_stop_cover(**kwargs),
            self.hass.loop,
        ).result()

    async def _async_enqueue_position(self, percentage: int) -> None:
        raw = pct_to_raw(percentage, self._shade_calibration.anchors, self._invert_axis)
        predictive = self.coordinator.predictive
        predictive.record_command(self._shade_id, time.monotonic())
        await self._write_batcher.enqueue(self._shade_id, raw)

    def _resolve_current_raw_position(self) -> int | None:
        shade = self.shade
        if shade is not None and shade.position is not None:
            return shade.position

        percent: int | None = self.current_cover_position
        if percent is None:
            if state := self.hass.states.get(self.entity_id):
                value = state.attributes.get("current_position")
                if value is not None:
                    try:
                        percent = int(value)
                    except (TypeError, ValueError):
                        percent = None

        if percent is None:
            return None

        return pct_to_raw(percent, self._shade_calibration.anchors, self._invert_axis)
