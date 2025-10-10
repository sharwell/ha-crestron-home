"""Diagnostics support for the Crestron Home integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    DATA_CALIBRATIONS,
    DATA_PREDICTIVE_MANAGER,
    DATA_PREDICTIVE_STORAGE,
    DATA_SHADES_COORDINATOR,
    DOMAIN,
)
from .coordinator import ShadesCoordinator
from .visual_groups import VisualGroupsConfig
from .predictive_stop import PredictiveRuntime
from .storage import PredictiveStopStore


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, object]:
    domain_data = hass.data.get(DOMAIN, {})
    entry_data = domain_data.get(entry.entry_id, {})

    coordinator: ShadesCoordinator | None = entry_data.get(DATA_SHADES_COORDINATOR)
    predictive: PredictiveRuntime | None = entry_data.get(DATA_PREDICTIVE_MANAGER)
    store: PredictiveStopStore | None = entry_data.get(DATA_PREDICTIVE_STORAGE)
    calibrations = entry_data.get(DATA_CALIBRATIONS)

    payload: dict[str, object] = {
        "predictive_enabled": predictive.enabled if predictive else None,
        "learning": predictive.diagnostics() if predictive else {},
    }

    if store is not None:
        stored = await store.async_load()
        payload["stored_learning"] = stored.shades

    if coordinator is not None:
        visual_groups: VisualGroupsConfig = coordinator.visual_groups
        payload["visual_groups"] = visual_groups.diagnostics()
        payload["plan_events"] = coordinator.plan_history
        payload["flush_events"] = coordinator.flush_history
        payload["assisted_calibration_runs"] = coordinator.assisted_history

    if coordinator is not None and coordinator.data:
        payload["shades"] = {
            shade_id: {
                "name": shade.name,
                "position": shade.position,
                "room_id": shade.room_id,
                "updated_at": shade.updated_at.isoformat(),
            }
            for shade_id, shade in coordinator.data.items()
        }

    if calibrations is not None:
        payload["calibrations"] = {
            "global_invert": getattr(calibrations, "global_invert", None),
        }

    return payload
