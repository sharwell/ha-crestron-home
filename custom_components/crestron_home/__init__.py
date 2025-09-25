"""Crestron Home integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_VERIFY_SSL, Platform
from homeassistant.core import HomeAssistant

from .api import ApiClient
from .calibration import parse_calibration_options
from .const import (
    CONF_API_TOKEN,
    DATA_API_CLIENT,
    DATA_CALIBRATIONS,
    DATA_PREDICTIVE_MANAGER,
    DATA_PREDICTIVE_STORAGE,
    DATA_SHADES_COORDINATOR,
    DATA_WRITE_BATCHER,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
    OPT_PREDICTIVE_STOP,
    PREDICTIVE_DEFAULT_ENABLED,
    PREDICTIVE_DIAGNOSTIC_HISTORY,
    PREDICTIVE_MIN_CONFIDENCE_SCALE,
    PREDICTIVE_RLS_FORGETTING,
    PREDICTIVE_STORAGE_KEY_PREFIX,
    PREDICTIVE_STORAGE_VERSION,
    PREDICTIVE_TAU_ACC,
    PREDICTIVE_TAU_DEC,
    PREDICTIVE_TAU_RESP_ALPHA,
    PREDICTIVE_TAU_RESP_INIT,
)
from .coordinator import ShadesCoordinator
from .learning import LearningManager
from .predictive_stop import PredictiveRuntime
from .storage import PredictiveStopStore, PredictiveStoreData
from .write import ShadeWriteBatcher

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

    predictive_store = PredictiveStopStore(
        hass,
        entry_id=entry.entry_id,
        version=PREDICTIVE_STORAGE_VERSION,
        key_prefix=PREDICTIVE_STORAGE_KEY_PREFIX,
    )
    stored = await predictive_store.async_load()
    learning_defaults = {
        "v0": 0.4,
        "v1": 0.0,
        "tau_resp": PREDICTIVE_TAU_RESP_INIT,
        "forgetting": PREDICTIVE_RLS_FORGETTING,
        "tau_resp_alpha": PREDICTIVE_TAU_RESP_ALPHA,
    }
    learning_manager = LearningManager.from_dict(stored.shades, defaults=learning_defaults)
    predictive_runtime = PredictiveRuntime(
        learning=learning_manager,
        tau_acc=PREDICTIVE_TAU_ACC,
        tau_dec=PREDICTIVE_TAU_DEC,
        tau_resp_init=PREDICTIVE_TAU_RESP_INIT,
        min_confidence_scale=PREDICTIVE_MIN_CONFIDENCE_SCALE,
        history_size=PREDICTIVE_DIAGNOSTIC_HISTORY,
    )
    predictive_runtime.enabled = entry.options.get(OPT_PREDICTIVE_STOP, PREDICTIVE_DEFAULT_ENABLED)

    calibrations = parse_calibration_options(entry.options)

    coordinator = ShadesCoordinator(
        hass,
        client,
        entry,
        predictive_runtime,
        calibrations,
    )
    await coordinator.async_config_entry_first_refresh()

    batcher = ShadeWriteBatcher(
        hass,
        client,
        on_success=lambda: coordinator.bump_fast_poll(),
    )

    hass.data[DOMAIN][entry.entry_id] = {
        DATA_API_CLIENT: client,
        DATA_SHADES_COORDINATOR: coordinator,
        DATA_WRITE_BATCHER: batcher,
        DATA_CALIBRATIONS: calibrations,
        DATA_PREDICTIVE_MANAGER: predictive_runtime,
        DATA_PREDICTIVE_STORAGE: predictive_store,
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
    batcher: ShadeWriteBatcher | None = stored.get(DATA_WRITE_BATCHER)
    if batcher is not None:
        await batcher.async_shutdown()

    predictive_store: PredictiveStopStore | None = stored.get(DATA_PREDICTIVE_STORAGE)
    predictive_runtime: PredictiveRuntime | None = stored.get(DATA_PREDICTIVE_MANAGER)
    if predictive_store and predictive_runtime:
        await predictive_store.async_save(
            PredictiveStoreData(
                version=PREDICTIVE_STORAGE_VERSION,
                shades=predictive_runtime.serialize_learning(),
            )
        )

    client: ApiClient | None = stored.get(DATA_API_CLIENT)
    if client is not None:
        await client.async_logout()

    if not domain_data:
        hass.data.pop(DOMAIN)

    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle config entry updates (options)."""

    await hass.config_entries.async_reload(entry.entry_id)
