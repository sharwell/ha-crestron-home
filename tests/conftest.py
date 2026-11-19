"""Shared fixtures for Crestron Home tests."""

from contextlib import AsyncExitStack
from pathlib import Path
from types import MappingProxyType

import pytest_asyncio


class _FakeCrestronController:
    async def async_get_shades(self) -> list[dict[str, object]]:
        return []


@pytest_asyncio.fixture
async def make_coordinator(tmp_path: Path):
    """Construct and shut down coordinators with real Home Assistant objects."""
    # Keep the real Home Assistant imports out of lightweight test collection.
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from custom_components.crestron_home.calibration import parse_calibration_options
    from custom_components.crestron_home.const import DOMAIN
    from custom_components.crestron_home.coordinator import ShadesCoordinator
    from custom_components.crestron_home.learning import LearningManager
    from custom_components.crestron_home.predictive_stop import PredictiveRuntime
    from custom_components.crestron_home.visual_groups import parse_visual_groups

    hass = HomeAssistant(str(tmp_path))
    async with AsyncExitStack() as cleanup:
        cleanup.push_async_callback(hass.async_stop, force=True)

        def make(options: dict[str, object] | None = None) -> ShadesCoordinator:
            entry = ConfigEntry(
                domain=DOMAIN,
                title="Test shades",
                data={},
                options=options or {},
                source="user",
                version=1,
                minor_version=1,
                unique_id=None,
                subentries_data=None,
                discovery_keys=MappingProxyType({}),
            )
            predictive = PredictiveRuntime(
                learning=LearningManager(defaults={}),
                tau_acc=1.0,
                tau_dec=1.0,
                tau_resp_init=0.15,
                min_confidence_scale=0.25,
                history_size=5,
            )
            coordinator = ShadesCoordinator(
                hass,
                _FakeCrestronController(),
                entry,
                predictive,
                parse_calibration_options(entry.options),
                parse_visual_groups(entry.options),
            )
            cleanup.push_async_callback(coordinator.async_shutdown)
            return coordinator

        yield make
