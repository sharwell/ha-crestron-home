"""Import the integration with lightweight Home Assistant stubs for unit tests."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
import sys
from types import ModuleType

import pytest


_COMPONENT = "custom_components.crestron_home"
_COMPONENTS_PATH = Path(__file__).resolve().parents[1] / "custom_components"


class _ConfigFlow:
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__()


class _DataUpdateCoordinator:
    def __class_getitem__(cls, _item):
        return cls


def _unexpected_session(*_args, **_kwargs):
    raise NotImplementedError("Lightweight tests must supply a fake Crestron client")


def _module(name: str, **members: object) -> ModuleType:
    module = ModuleType(name)
    vars(module).update(members)
    return module


def _home_assistant_modules() -> tuple[ModuleType, ...]:
    config_entries = _module(
        "homeassistant.config_entries",
        ConfigEntry=type("ConfigEntry", (), {}),
        ConfigFlow=_ConfigFlow,
        OptionsFlow=type("OptionsFlow", (), {}),
    )
    const = _module(
        "homeassistant.const",
        CONF_HOST="host",
        CONF_VERIFY_SSL="verify_ssl",
        Platform=type("Platform", (), {"COVER": "cover"}),
    )
    core = _module(
        "homeassistant.core",
        HomeAssistant=type("HomeAssistant", (), {}),
        callback=lambda function: function,
    )
    data_entry_flow = _module("homeassistant.data_entry_flow", FlowResult=dict)
    exceptions = _module(
        "homeassistant.exceptions",
        HomeAssistantError=type("HomeAssistantError", (Exception,), {}),
    )
    aiohttp_client = _module(
        "homeassistant.helpers.aiohttp_client",
        async_create_clientsession=_unexpected_session,
        async_get_clientsession=_unexpected_session,
    )
    selector = _module("homeassistant.helpers.selector", selector=lambda config: config)
    storage = _module("homeassistant.helpers.storage", Store=type("Store", (), {}))
    translation = _module(
        "homeassistant.helpers.translation",
        async_get_cached_translations=lambda hass, language, category, domain: {},
    )
    update_coordinator = _module(
        "homeassistant.helpers.update_coordinator",
        DataUpdateCoordinator=_DataUpdateCoordinator,
        UpdateFailed=type("UpdateFailed", (Exception,), {}),
    )
    helpers = _module(
        "homeassistant.helpers",
        __path__=[],
        aiohttp_client=aiohttp_client,
        selector=selector,
        storage=storage,
        translation=translation,
        update_coordinator=update_coordinator,
    )
    dt = _module("homeassistant.util.dt", utcnow=lambda: datetime.now(UTC))
    util = _module("homeassistant.util", __path__=[], dt=dt)
    home_assistant = _module(
        "homeassistant",
        __path__=[],
        config_entries=config_entries,
        const=const,
        core=core,
        data_entry_flow=data_entry_flow,
        exceptions=exceptions,
        helpers=helpers,
        util=util,
    )
    return (
        home_assistant, config_entries, const, core, data_entry_flow, exceptions,
        helpers, aiohttp_client, selector, storage, translation, update_coordinator,
        util, dt,
    )


def _isolated_modules() -> list[str]:
    packages = (_COMPONENT, "voluptuous")
    submodule_prefixes = tuple(f"{package}." for package in packages)
    return [
        name for name in sys.modules
        if name in packages or name.startswith(submodule_prefixes)
    ]


@contextmanager
def home_assistant_stubs() -> Iterator[None]:
    """Keep stubs and imports that use them local to the requesting test module."""
    with pytest.MonkeyPatch.context() as patch:
        # Keep standalone voluptuous inside the stubbed imports so it cannot
        # interfere with Home Assistant installing its compatibility shim.
        for name in _isolated_modules():
            patch.delitem(sys.modules, name)

        # Use a fresh parent so Python attaches the stub-backed integration to it.
        components = _module("custom_components", __path__=[str(_COMPONENTS_PATH)])
        patch.setitem(sys.modules, components.__name__, components)
        for module in _home_assistant_modules():
            patch.setitem(sys.modules, module.__name__, module)

        try:
            yield
        finally:
            for name in _isolated_modules():
                del sys.modules[name]
