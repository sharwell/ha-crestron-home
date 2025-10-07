import asyncio
import importlib.util
from pathlib import Path
import sys
import types
from typing import Any, Coroutine

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = PROJECT_ROOT / "custom_components" / "crestron_home"
PACKAGE_NAME = "custom_components.crestron_home"

# Ensure package namespace exists for dynamic imports.
if "custom_components" not in sys.modules:
    custom_components_pkg = types.ModuleType("custom_components")
    custom_components_pkg.__path__ = [str(PROJECT_ROOT / "custom_components")]
    sys.modules["custom_components"] = custom_components_pkg

if PACKAGE_NAME not in sys.modules:
    crestron_home_pkg = types.ModuleType(PACKAGE_NAME)
    crestron_home_pkg.__path__ = [str(PACKAGE_ROOT)]
    sys.modules[PACKAGE_NAME] = crestron_home_pkg

# Minimal Home Assistant stubs required by the batcher module.
homeassistant = sys.modules.setdefault("homeassistant", types.ModuleType("homeassistant"))

core_module = types.ModuleType("homeassistant.core")
core_module.HomeAssistant = type("HomeAssistant", (), {})
core_module.callback = lambda func: func
homeassistant.core = core_module
sys.modules["homeassistant.core"] = core_module

exceptions_module = types.ModuleType("homeassistant.exceptions")
exceptions_module.HomeAssistantError = type("HomeAssistantError", (Exception,), {})
homeassistant.exceptions = exceptions_module
sys.modules["homeassistant.exceptions"] = exceptions_module

helpers_module = types.ModuleType("homeassistant.helpers")
helpers_module.__path__ = []
translation_module = types.ModuleType("homeassistant.helpers.translation")
translation_module.async_get_cached_translations = (
    lambda hass, language, category, domain: {}
)
helpers_module.translation = translation_module
homeassistant.helpers = helpers_module
sys.modules["homeassistant.helpers"] = helpers_module
sys.modules["homeassistant.helpers.translation"] = translation_module

write_spec = importlib.util.spec_from_file_location(
    f"{PACKAGE_NAME}.write", PACKAGE_ROOT / "write.py"
)
write = importlib.util.module_from_spec(write_spec)
assert write_spec and write_spec.loader
sys.modules[write_spec.name] = write
write_spec.loader.exec_module(write)

api_spec = importlib.util.spec_from_file_location(
    f"{PACKAGE_NAME}.api", PACKAGE_ROOT / "api.py"
)
api = importlib.util.module_from_spec(api_spec)
assert api_spec and api_spec.loader
sys.modules[api_spec.name] = api
api_spec.loader.exec_module(api)

ShadeWriteBatcher = write.ShadeWriteBatcher
HomeAssistantError = exceptions_module.HomeAssistantError
ShadeCommandResponse = api.ShadeCommandResponse
ShadeCommandResult = api.ShadeCommandResult


class FakeHass:
    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop
        self.config = types.SimpleNamespace(language="en")

    def async_create_task(self, coro: Coroutine[Any, Any, Any]) -> asyncio.Task:
        return self.loop.create_task(coro)


def test_batcher_deduplicates_latest_position() -> None:
    """The batcher should send only the latest command per shade."""

    async def _async_test() -> None:
        loop = asyncio.get_running_loop()
        hass = FakeHass(loop)
        calls: list[list[dict[str, int]]] = []
        callback_calls: list[int] = []

        class _Client:
            async def async_set_shade_positions(self, items, *, retry: bool = True):
                calls.append(list(items))
                return ShadeCommandResponse(status="success", results={})

        def _on_success() -> None:
            callback_calls.append(1)

        batcher = ShadeWriteBatcher(hass, _Client(), debounce_ms=50, on_success=_on_success)

        await asyncio.gather(
            batcher.enqueue("shade-1", 1000),
            batcher.enqueue("shade-1", 2000),
        )

        assert calls == [[{"id": "shade-1", "position": 2000}]]
        assert len(callback_calls) == 1

    asyncio.run(_async_test())


def test_batcher_partial_failure_propagates() -> None:
    """Partial failures should raise only for the affected shade."""

    async def _async_test() -> None:
        loop = asyncio.get_running_loop()
        hass = FakeHass(loop)

        class _Client:
            async def async_set_shade_positions(self, items, *, retry: bool = True):
                return ShadeCommandResponse(
                    status="partial",
                    results={
                        "shade-1": ShadeCommandResult(status="success"),
                        "shade-2": ShadeCommandResult(status="failure", message="offline"),
                    },
                )

        batcher = ShadeWriteBatcher(hass, _Client(), debounce_ms=0)

        first = asyncio.create_task(batcher.enqueue("shade-1", 1000))
        second = asyncio.create_task(batcher.enqueue("shade-2", 2000))

        results = await asyncio.gather(first, second, return_exceptions=True)

        assert results[0] is None
        assert isinstance(results[1], HomeAssistantError)
        assert "shade-2" in str(results[1])

    asyncio.run(_async_test())


def test_batcher_flush_callback_receives_payload() -> None:
    """Flush callbacks should receive the payload and final status."""

    async def _async_test() -> None:
        loop = asyncio.get_running_loop()
        hass = FakeHass(loop)
        flush_calls: list[tuple[list[dict[str, int]], str | None]] = []

        class _Client:
            async def async_set_shade_positions(self, items, *, retry: bool = True):
                return ShadeCommandResponse(status="success", results={})

        def _on_flush(items, status):
            flush_calls.append((list(items), status))

        batcher = ShadeWriteBatcher(
            hass,
            _Client(),
            debounce_ms=0,
            on_flush=_on_flush,
        )

        await batcher.enqueue("shade-1", 1234)
        await batcher.async_flush()

        assert flush_calls
        payload, status = flush_calls[0]
        assert payload == [{"id": "shade-1", "position": 1234}]
        assert status == "success"

    asyncio.run(_async_test())


def test_batcher_splits_large_payload() -> None:
    """Batches larger than the controller limit should split into multiple posts."""

    async def _async_test() -> None:
        loop = asyncio.get_running_loop()
        hass = FakeHass(loop)
        calls: list[list[dict[str, int]]] = []

        class _Client:
            async def async_set_shade_positions(self, items, *, retry: bool = True):
                calls.append(list(items))
                return ShadeCommandResponse(status="success", results={})

        batcher = ShadeWriteBatcher(hass, _Client(), debounce_ms=80)

        for index in range(20):
            await batcher.enqueue(f"shade-{index}", index)
        await asyncio.sleep(0.2)
        await batcher.async_flush()

        assert len(calls) >= 2
        assert all(len(call) <= 16 for call in calls)
        all_ids = [item["id"] for call in calls for item in call]
        assert all_ids.count("shade-0") == 1
        assert all_ids.count("shade-19") == 1

    asyncio.run(_async_test())
