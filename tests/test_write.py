import asyncio
from collections import Counter
import types
from typing import Any, Coroutine

from home_assistant_stubs import home_assistant_stubs

with home_assistant_stubs():
    from homeassistant.exceptions import HomeAssistantError

    from custom_components.crestron_home.api import (
        ShadeCommandFailedError,
        ShadeCommandResponse,
        ShadeCommandResult,
    )
    from custom_components.crestron_home.const import BATCH_MAX_ITEMS
    from custom_components.crestron_home.write import ShadeWriteBatcher


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


def test_batcher_coalesces_group_stage() -> None:
    """Enqueuing multiple shades together should flush as one payload."""

    async def _async_test() -> None:
        loop = asyncio.get_running_loop()
        hass = FakeHass(loop)
        calls: list[list[dict[str, int]]] = []

        class _Client:
            async def async_set_shade_positions(self, items, *, retry: bool = True):
                calls.append(list(items))
                return ShadeCommandResponse(status="success", results={})

        batcher = ShadeWriteBatcher(hass, _Client(), debounce_ms=80)

        try:
            await asyncio.wait_for(
                asyncio.gather(
                    *(batcher.enqueue(f"shade-{index}", index * 1000) for index in range(6))
                ),
                timeout=5,
            )
        finally:
            await batcher.async_shutdown()

        assert len(calls) == 1
        payload = calls[0]
        assert len(payload) == 6
        ids = [item["id"] for item in payload]
        assert ids == [f"shade-{index}" for index in range(6)]

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

        shade_ids = [f"shade-{index}" for index in range(BATCH_MAX_ITEMS + 4)]
        try:
            await asyncio.wait_for(
                asyncio.gather(
                    *(
                        batcher.enqueue(shade_id, index)
                        for index, shade_id in enumerate(shade_ids)
                    )
                ),
                timeout=5,
            )
        finally:
            await batcher.async_shutdown()

        assert len(calls) >= 2
        assert max(map(len, calls)) == BATCH_MAX_ITEMS
        assert Counter(item["id"] for call in calls for item in call) == Counter(shade_ids)

    asyncio.run(_async_test())


def test_batcher_sends_remaining_writes_after_a_split_request_fails() -> None:
    """Only callers in the rejected request should receive its error."""

    async def _async_test() -> None:
        hass = FakeHass(asyncio.get_running_loop())
        calls: list[list[str]] = []

        class _Client:
            async def async_set_shade_positions(self, items, *, retry: bool = True):
                calls.append([item["id"] for item in items])
                if len(calls) == 1:
                    raise ShadeCommandFailedError("rejected")
                return ShadeCommandResponse(status="success", results={})

        batcher = ShadeWriteBatcher(hass, _Client(), max_items=2)
        try:
            results = await asyncio.wait_for(
                asyncio.gather(
                    *(batcher.enqueue(f"shade-{index}", index) for index in range(3)),
                    return_exceptions=True,
                ),
                timeout=5,
            )
        finally:
            await batcher.async_shutdown()

        assert calls == [["shade-0", "shade-1"], ["shade-2"]]
        assert all(isinstance(result, HomeAssistantError) for result in results[:2])
        assert results[2] is None

    asyncio.run(_async_test())
