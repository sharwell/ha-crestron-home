"""Build support diagnostics with aliases scoped to each download."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from math import isfinite
from time import monotonic
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.util.dt import utcnow

from .const import (
    DATA_CALIBRATIONS,
    DATA_PREDICTIVE_MANAGER,
    DATA_PREDICTIVE_STORAGE,
    DATA_SHADES_COORDINATOR,
    DOMAIN,
)
from .coordinator import ShadesCoordinator
from .predictive_stop import PredictiveRuntime
from .privacy import IdentifierAliases, write_status_label
from .storage import PredictiveStopStore


def _numeric_fields(values: Mapping[str, Any], *fields: str) -> dict[str, int | float]:
    result = {}
    for field in fields:
        value = values.get(field)
        if type(value) is int or (type(value) is float and isfinite(value)):
            result[field] = value
    return result


def _stored_summary(value: object) -> dict[str, int | float]:
    if not isinstance(value, Mapping):
        return {}
    result = _numeric_fields(value, "tau_resp", "confidence", "sample_count", "rmse")
    if isinstance(rls := value.get("rls"), Mapping):
        for field, number in _numeric_fields(rls, "theta0", "theta1").items():
            result["v0" if field == "theta0" else "v1"] = number
    return result


def _event_time(event: Mapping[str, Any], exported_at: datetime) -> float:
    return (datetime.fromisoformat(event["timestamp"]) - exported_at).total_seconds()


def _learning_summary(
    state: Mapping[str, Any], exported_monotonic: float
) -> dict[str, object]:
    return {
        **_numeric_fields(state, "v0", "v1", "tau_resp", "confidence"),
        "history": [
            {
                "seconds_from_export": event["timestamp"] - exported_monotonic,
                **_numeric_fields(event, "position", "velocity", "target", "distance"),
                "settled": event["settled"],
            }
            for event in state["history"]
        ],
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, object]:
    """Return support data with fresh aliases and event times relative to export.

    Negative seconds indicate events before collection. Aliases correlate records
    within this result and their mapping is discarded after collection.
    """
    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    coordinator: ShadesCoordinator | None = entry_data.get(DATA_SHADES_COORDINATOR)
    predictive: PredictiveRuntime | None = entry_data.get(DATA_PREDICTIVE_MANAGER)
    store: PredictiveStopStore | None = entry_data.get(DATA_PREDICTIVE_STORAGE)
    calibrations = entry_data.get(DATA_CALIBRATIONS)

    stored = await store.async_load() if store is not None else None
    exported_at = utcnow()
    exported_monotonic = monotonic()
    aliases = IdentifierAliases()
    payload: dict[str, object] = {
        "predictive_enabled": predictive.enabled if predictive else None,
        "learning": {
            aliases.shade(shade_id): _learning_summary(state, exported_monotonic)
            for shade_id, state in (predictive.diagnostics().items() if predictive else ())
        },
    }

    if stored is not None:
        payload["stored_learning"] = {
            aliases.shade(shade_id): summary
            for shade_id, value in stored.shades.items()
            if (summary := _stored_summary(value))
        }

    if coordinator is not None:
        groups = coordinator.visual_groups
        payload["visual_groups"] = {
            "version": groups.version,
            "groups": [aliases.group(group_id) for group_id in groups.groups],
            "membership": {
                aliases.shade(shade_id): aliases.group(group_id)
                for shade_id, group_id in groups.membership.items()
            },
        }
        payload["plan_events"] = [
            {
                "seconds_from_export": _event_time(event, exported_at),
                "group_id": aliases.group(event["group_id"]),
                "shade_ids": [aliases.shade(shade_id) for shade_id in event["shade_ids"]],
                "targets": [
                    {
                        "shade_id": aliases.shade(target["shade_id"]),
                        "position": target["position"],
                        "clamped": target["clamped"],
                        "distance": target["distance"],
                    }
                    for target in event["targets"]
                ],
                "flush": event["flush"],
            }
            for event in coordinator.plan_history
        ]
        payload["flush_events"] = [
            {
                "seconds_from_export": _event_time(event, exported_at),
                "status": (
                    write_status_label(event["status"])
                    if event["status"] is not None
                    else None
                ),
                "count": event["count"],
                "targets": [
                    {
                        "shade_id": aliases.shade(item["id"]),
                        "position": item["position"],
                    }
                    for item in event["items"]
                ],
                "groups": [
                    {
                        "group_id": aliases.group(group["group_id"]),
                        "shade_ids": [aliases.shade(shade_id) for shade_id in group["shade_ids"]],
                    }
                    for group in event["groups"]
                ],
            }
            for event in coordinator.flush_history
        ]
        payload["assisted_calibration_runs"] = [
            {
                "seconds_from_export": _event_time(event, exported_at),
                "group_id": aliases.group(event["group_id"]),
                "target_percent": event["target_percent"],
                "saved": [aliases.shade(shade_id) for shade_id in event["saved"]],
                "skipped": [aliases.shade(shade_id) for shade_id in event["skipped"]],
            }
            for event in coordinator.assisted_history
        ]
        if coordinator.data:
            payload["shades"] = {
                aliases.shade(shade_id): {
                    "position": shade.position,
                    "seconds_from_export": (shade.updated_at - exported_at).total_seconds(),
                }
                for shade_id, shade in coordinator.data.items()
            }

    if calibrations is not None:
        payload["calibrations"] = {"global_invert": calibrations.global_invert}

    return payload
