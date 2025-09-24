"""Tests for the Crestron Home config and options flow helpers."""

from __future__ import annotations

from dataclasses import dataclass
import sys
import types


# ---------------------------------------------------------------------------
# Minimal Home Assistant stubs so we can import the config flow without the
# full Home Assistant test infrastructure.
# ---------------------------------------------------------------------------

homeassistant = types.ModuleType("homeassistant")
homeassistant.__path__ = []  # mark as package
sys.modules.setdefault("homeassistant", homeassistant)


class _ConfigFlow:  # pragma: no cover - behavior not exercised in tests
    def __init_subclass__(cls, **_kwargs):
        return super().__init_subclass__()


class _OptionsFlow:  # pragma: no cover - behavior not exercised in tests
    def __init_subclass__(cls, **_kwargs):
        return super().__init_subclass__()


class _ConfigEntry:  # pragma: no cover - behavior not exercised in tests
    pass


config_entries = types.ModuleType("homeassistant.config_entries")
config_entries.ConfigFlow = _ConfigFlow
config_entries.OptionsFlow = _OptionsFlow
config_entries.ConfigEntry = _ConfigEntry
homeassistant.config_entries = config_entries
sys.modules["homeassistant.config_entries"] = config_entries

const_module = types.ModuleType("homeassistant.const")
const_module.CONF_HOST = "host"
const_module.CONF_VERIFY_SSL = "verify_ssl"
homeassistant.const = const_module
sys.modules["homeassistant.const"] = const_module


def _callback(func):  # pragma: no cover - helper used only at import time
    return func


core_module = types.ModuleType("homeassistant.core")
core_module.HomeAssistant = type("HomeAssistant", (), {})
core_module.callback = _callback
homeassistant.core = core_module
sys.modules["homeassistant.core"] = core_module

data_entry_flow_module = types.ModuleType("homeassistant.data_entry_flow")
data_entry_flow_module.FlowResult = dict
homeassistant.data_entry_flow = data_entry_flow_module
sys.modules["homeassistant.data_entry_flow"] = data_entry_flow_module

util_module = types.ModuleType("homeassistant.util")
util_module.__path__ = []
dt_module = types.ModuleType("homeassistant.util.dt")


def _utcnow():  # pragma: no cover - helper used only at import time
    raise NotImplementedError


dt_module.utcnow = _utcnow
util_module.dt = dt_module
homeassistant.util = util_module
sys.modules["homeassistant.util"] = util_module
sys.modules["homeassistant.util.dt"] = dt_module

helpers_module = types.ModuleType("homeassistant.helpers")
helpers_module.__path__ = []  # mark as a package for submodule imports
selector_module = types.ModuleType("homeassistant.helpers.selector")
aiohttp_client_module = types.ModuleType("homeassistant.helpers.aiohttp_client")
update_coordinator_module = types.ModuleType(
    "homeassistant.helpers.update_coordinator"
)


def _async_client_session(*_args, **_kwargs):  # pragma: no cover - import stub
    raise NotImplementedError


aiohttp_client_module.async_create_clientsession = _async_client_session
aiohttp_client_module.async_get_clientsession = _async_client_session
class _DataUpdateCoordinator:
    """Minimal stand-in for Home Assistant's DataUpdateCoordinator."""

    def __init__(self, *_args, **_kwargs):  # pragma: no cover - import stub
        pass

    def __class_getitem__(cls, _item):  # pragma: no cover - import stub
        return cls


update_coordinator_module.DataUpdateCoordinator = _DataUpdateCoordinator
update_coordinator_module.UpdateFailed = type("UpdateFailed", (Exception,), {})


def _selector(value):  # pragma: no cover - helper used only at import time
    return value


selector_module.selector = _selector
helpers_module.selector = selector_module
helpers_module.aiohttp_client = aiohttp_client_module
helpers_module.update_coordinator = update_coordinator_module
homeassistant.helpers = helpers_module
sys.modules["homeassistant.helpers"] = helpers_module
sys.modules["homeassistant.helpers.selector"] = selector_module
sys.modules["homeassistant.helpers.aiohttp_client"] = aiohttp_client_module
sys.modules["homeassistant.helpers.update_coordinator"] = update_coordinator_module


from custom_components.crestron_home.config_flow import (  # noqa: E402
    CrestronHomeOptionsFlowHandler,
)


@dataclass
class _SelectorValue:
    """Simple stand-in for Home Assistant selector option objects."""

    value: str
    label: str


def test_normalize_shade_id_from_string() -> None:
    """A plain string should be returned unchanged after stripping."""

    assert (
        CrestronHomeOptionsFlowHandler._normalize_shade_id("  shade-123  ")
        == "shade-123"
    )


def test_normalize_shade_id_from_mapping() -> None:
    """Mappings from selectors should prefer the 'value' entry."""

    assert (
        CrestronHomeOptionsFlowHandler._normalize_shade_id(
            {"value": "shade-456", "label": "Living Room"}
        )
        == "shade-456"
    )


def test_normalize_shade_id_from_object_value_attribute() -> None:
    """Selector option objects expose the identifier via the value attribute."""

    assert (
        CrestronHomeOptionsFlowHandler._normalize_shade_id(
            _SelectorValue("shade-789", "Kitchen")
        )
        == "shade-789"
    )


def test_normalize_shade_id_from_none() -> None:
    """None should be treated as an empty selection."""

    assert CrestronHomeOptionsFlowHandler._normalize_shade_id(None) == ""
