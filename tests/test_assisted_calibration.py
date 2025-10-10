from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import sys
import types
from collections import deque

# ruff: noqa: E402

if "homeassistant" not in sys.modules:
    homeassistant = types.ModuleType("homeassistant")
    sys.modules["homeassistant"] = homeassistant
else:
    homeassistant = sys.modules["homeassistant"]

config_entries = types.ModuleType("homeassistant.config_entries")
config_entries.ConfigEntry = type("ConfigEntry", (), {})


class _ConfigFlow:
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__()


class _OptionsFlow:
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__()


config_entries.ConfigFlow = _ConfigFlow
config_entries.OptionsFlow = _OptionsFlow
homeassistant.config_entries = config_entries
sys.modules["homeassistant.config_entries"] = config_entries

core_module = types.ModuleType("homeassistant.core")
core_module.HomeAssistant = type("HomeAssistant", (), {})
homeassistant.core = core_module
sys.modules["homeassistant.core"] = core_module

helpers_module = types.ModuleType("homeassistant.helpers")
helpers_module.__path__ = []
update_coordinator_module = types.ModuleType(
    "homeassistant.helpers.update_coordinator"
)


class _DataUpdateCoordinator:
    def __init__(self, *_args, **_kwargs):
        pass

    def __class_getitem__(cls, _item):
        return cls


update_coordinator_module.DataUpdateCoordinator = _DataUpdateCoordinator
update_coordinator_module.UpdateFailed = type("UpdateFailed", (Exception,), {})
helpers_module.update_coordinator = update_coordinator_module
aiohttp_client_module = types.ModuleType("homeassistant.helpers.aiohttp_client")
aiohttp_client_module.async_create_clientsession = (
    lambda hass, *args, **kwargs: None
)
aiohttp_client_module.async_get_clientsession = (
    lambda hass, *args, **kwargs: None
)
helpers_module.aiohttp_client = aiohttp_client_module
translation_module = types.ModuleType("homeassistant.helpers.translation")
translation_module.async_get_cached_translations = (
    lambda hass, language, category, domain: {}
)
helpers_module.translation = translation_module
storage_module = types.ModuleType("homeassistant.helpers.storage")


class _Store:
    def __init__(self, *_args, **_kwargs):
        self._data = None

    async def async_load(self):
        return self._data

    async def async_save(self, data):
        self._data = data


storage_module.Store = _Store
helpers_module.storage = storage_module
homeassistant.helpers = helpers_module
sys.modules["homeassistant.helpers"] = helpers_module
sys.modules["homeassistant.helpers.update_coordinator"] = update_coordinator_module
sys.modules["homeassistant.helpers.translation"] = translation_module
sys.modules["homeassistant.helpers.storage"] = storage_module
sys.modules["homeassistant.helpers.aiohttp_client"] = aiohttp_client_module

util_module = types.ModuleType("homeassistant.util")
dt_module = types.ModuleType("homeassistant.util.dt")
dt_module.utcnow = lambda: datetime.now(timezone.utc)
util_module.dt = dt_module
homeassistant.util = util_module
sys.modules["homeassistant.util"] = util_module
sys.modules["homeassistant.util.dt"] = dt_module

exceptions_module = types.ModuleType("homeassistant.exceptions")
exceptions_module.HomeAssistantError = type("HomeAssistantError", (Exception,), {})
homeassistant.exceptions = exceptions_module
sys.modules["homeassistant.exceptions"] = exceptions_module

const_module = types.ModuleType("homeassistant.const")
const_module.CONF_HOST = "host"
const_module.CONF_VERIFY_SSL = "verify_ssl"
const_module.Platform = type("Platform", (), {"COVER": "cover"})
homeassistant.const = const_module
sys.modules["homeassistant.const"] = const_module

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = PROJECT_ROOT / "custom_components" / "crestron_home"
PACKAGE_NAME = "custom_components.crestron_home"

if "custom_components" not in sys.modules:
    custom_components_pkg = types.ModuleType("custom_components")
    custom_components_pkg.__path__ = [str(PROJECT_ROOT / "custom_components")]
    sys.modules["custom_components"] = custom_components_pkg

if PACKAGE_NAME not in sys.modules:
    spec = importlib.util.spec_from_file_location(
        PACKAGE_NAME, PACKAGE_ROOT / "__init__.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[PACKAGE_NAME] = module
    spec.loader.exec_module(module)


from custom_components.crestron_home.assisted_calibration import (
    AssistedCalibrationRun,
    apply_assisted_anchor,
    largest_gap_target,
)
from custom_components.crestron_home.calibration import ShadeCalibration
from custom_components.crestron_home.coordinator import ShadesCoordinator


def test_largest_gap_default_endpoints() -> None:
    """With only 0% and 100% anchors the midpoint should be selected."""

    calibration = ShadeCalibration()
    assert largest_gap_target([calibration]) == 50


def test_largest_gap_union_midpoint() -> None:
    """Mixed anchors should pick the midpoint of the largest combined gap."""

    group_a = ShadeCalibration(anchors=((0, 0), (20, 2000), (100, 65535)))
    group_b = ShadeCalibration(anchors=((0, 0), (60, 4000), (100, 65535)))

    assert largest_gap_target([group_a, group_b]) == 40


def test_apply_assisted_anchor_skips_unchanged() -> None:
    """Raw differences inside the epsilon should not modify the curve."""

    calibration = ShadeCalibration(anchors=((0, 0), (50, 3000), (100, 65535)))
    anchors, changed = apply_assisted_anchor(calibration, 50, 3002)

    assert not changed
    assert anchors == calibration.anchors


def test_apply_assisted_anchor_inserts() -> None:
    """New anchors should be inserted when outside existing percent slots."""

    calibration = ShadeCalibration(anchors=((0, 0), (100, 65535)))
    anchors, changed = apply_assisted_anchor(calibration, 40, 2000)

    assert changed
    assert (40, 2000) in anchors


def test_assisted_run_diagnostics_payload() -> None:
    """Runs should serialize into diagnostics-friendly dictionaries."""

    timestamp = datetime(2024, 1, 1, tzinfo=timezone.utc)
    run = AssistedCalibrationRun(
        group_id="group-1",
        target_percent=55,
        saved=("shade-1", "shade-2"),
        skipped=("shade-3",),
        timestamp=timestamp,
    )

    payload = run.as_diagnostics()
    assert payload == {
        "group_id": "group-1",
        "target_percent": 55,
        "saved": ["shade-1", "shade-2"],
        "skipped": ["shade-3"],
        "timestamp": timestamp.isoformat(),
    }


def test_coordinator_records_assisted_runs() -> None:
    """Coordinator history should expose assisted calibration runs."""

    coordinator = object.__new__(ShadesCoordinator)
    coordinator._assisted_history = deque(maxlen=10)  # type: ignore[attr-defined]

    timestamp = datetime(2024, 2, 2, tzinfo=timezone.utc)
    run = AssistedCalibrationRun(
        group_id="group-2",
        target_percent=42,
        saved=("shade-9",),
        skipped=(),
        timestamp=timestamp,
    )

    ShadesCoordinator.record_assisted_calibration(coordinator, run)

    assert coordinator.assisted_history == [run.as_diagnostics()]
