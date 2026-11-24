import asyncio
from collections import Counter
import logging
import types
from typing import Any, Coroutine

import pytest

from home_assistant_stubs import home_assistant_stubs

with home_assistant_stubs():
    from homeassistant.exceptions import HomeAssistantError

    from custom_components.crestron_home import api
    from custom_components.crestron_home.api import (
        ShadeCommandFailedError,
        ShadeCommandResponse,
        ShadeCommandResult,
    )
    from custom_components.crestron_home.calibration import parse_calibration_options
    from custom_components.crestron_home.const import BATCH_MAX_ITEMS, OPT_MINIMUM_POSITIONS
    from custom_components.crestron_home.write import ShadeWriteBatcher


class FakeHass:
    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop
        self.config = types.SimpleNamespace(language="en")

    def async_create_task(self, coro: Coroutine[Any, Any, Any]) -> asyncio.Task:
        return self.loop.create_task(coro)


class _HttpReply:
    def __init__(self, status, data=None, *, on_enter=None):
        self.status = status
        self._data = data
        self._on_enter = on_enter

    async def __aenter__(self):
        if self._on_enter is not None:
            await self._on_enter()
        return self

    async def __aexit__(self, *_args):
        return None

    def raise_for_status(self):
        assert self.status == 200

    async def json(self):
        return self._data


class _ReauthController:
    def __init__(self):
        self.reauth_started = asyncio.Event()
        self.reauth_complete = asyncio.Event()
        self.logins = 0
        self.writes = []

    async def _pause_reauthentication(self):
        self.reauth_started.set()
        await self.reauth_complete.wait()

    def get(self, _url, **_kwargs):
        self.logins += 1
        return _HttpReply(
            200,
            {"authkey": f"fictional-key-{self.logins}"},
            on_enter=self._pause_reauthentication if self.logins == 2 else None,
        )

    def post(self, _url, *, json, headers, **_kwargs):
        self.writes.append((json["shades"], headers["Crestron-RestAPI-AuthKey"]))
        if len(self.writes) == 1:
            return _HttpReply(401)
        return _HttpReply(200, {"status": "success"})


@pytest.mark.parametrize("raise_minimum", [False, True], ids=["unchanged", "raised"])
def test_write_retry_rechecks_current_minimum(monkeypatch, caplog, raise_minimum):
    async def _async_test():
        hass = FakeHass(asyncio.get_running_loop())
        controller = _ReauthController()
        monkeypatch.setattr(api, "async_get_clientsession", lambda _hass: controller)
        options = {"invert": False}
        batcher = ShadeWriteBatcher(
            hass, api.ApiClient(hass, "controller.invalid", "fictional-token"),
            debounce_ms=0, get_calibrations=lambda: parse_calibration_options(options),
        )
        queued = asyncio.create_task(batcher.enqueue("shade-1", 0))
        requested = [{"id": "shade-1", "position": 0}]
        try:
            await asyncio.wait_for(controller.reauth_started.wait(), timeout=5)
            if raise_minimum:
                options[OPT_MINIMUM_POSITIONS] = {"shade-1": 10}
                controller.reauth_complete.set()
                with pytest.raises(HomeAssistantError, match="minimum position changed"):
                    await asyncio.wait_for(queued, timeout=5)
                assert controller.writes == [(requested, "fictional-key-1")]
                await asyncio.wait_for(batcher.enqueue("shade-1", 0), timeout=5)
                expected = [{"id": "shade-1", "position": 6554}]
            else:
                controller.reauth_complete.set()
                await asyncio.wait_for(queued, timeout=5)
                expected = requested
            assert controller.writes == [
                (requested, "fictional-key-1"), (expected, "fictional-key-2"),
            ]
        finally:
            controller.reauth_complete.set()
            await asyncio.wait_for(batcher.async_shutdown(), timeout=5)

    with caplog.at_level(logging.DEBUG, logger="custom_components.crestron_home"):
        asyncio.run(_async_test())
    assert "SetState returned HTTP 401" in caplog.text
    assert "SetState returned HTTP 200" in caplog.text
    for private in ("controller.invalid", "fictional-token", "fictional-key-", "'shade-1'"):
        assert private not in caplog.text


@pytest.mark.parametrize("require_exact", [False, True], ids=["coalesced", "exact"])
def test_batcher_deduplicates_latest_position(require_exact: bool) -> None:
    """Send the latest target and report superseded exact requests as failures."""

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
        try:
            results = await asyncio.wait_for(
                asyncio.gather(
                    batcher.enqueue("shade-1", 1000, require_exact=require_exact),
                    batcher.enqueue("shade-1", 2000),
                    return_exceptions=True,
                ),
                timeout=5,
            )
        finally:
            await asyncio.wait_for(batcher.async_shutdown(), timeout=5)

        assert calls == [[{"id": "shade-1", "position": 2000}]]
        assert len(callback_calls) == 1
        assert results[1] is None
        if require_exact:
            assert isinstance(results[0], HomeAssistantError)
            assert "Another command changed the shade target" in str(results[0])
        else:
            assert results[0] is None

    asyncio.run(_async_test())


def test_batcher_partial_failure_propagates_with_safe_details(caplog) -> None:
    """Partial failures should raise only for the affected shade."""

    async def _async_test() -> None:
        loop = asyncio.get_running_loop()
        hass = FakeHass(loop)

        class _Client:
            async def async_set_shade_positions(self, items, *, retry: bool = True):
                return ShadeCommandResponse(
                    status="partial",
                    results={
                        "private-shade-S1": ShadeCommandResult(status="success"),
                        "private-shade-S2": ShadeCommandResult(
                            status="failure", message="unexpected controller text with fictional key",
                        ),
                    },
                )

        batcher = ShadeWriteBatcher(hass, _Client(), debounce_ms=0)
        try:
            results = await asyncio.wait_for(
                asyncio.gather(
                    batcher.enqueue("private-shade-S1", 1000),
                    batcher.enqueue("private-shade-S2", 2000),
                    return_exceptions=True,
                ),
                timeout=5,
            )
        finally:
            await asyncio.wait_for(batcher.async_shutdown(), timeout=5)

        assert results[0] is None
        assert isinstance(results[1], HomeAssistantError)
        summary = next(record.batch for record in caplog.records if hasattr(record, "batch"))
        shade_alias = summary["ids"][1]
        assert shade_alias.startswith("shade-")
        assert summary["status"] == "partial"
        assert shade_alias in str(results[1])
        assert shade_alias in caplog.text
        for private in ("private-shade", "unexpected controller text", "fictional key"):
            assert private not in str(results[1])
            assert private not in caplog.text
            assert private not in repr(summary)

    with caplog.at_level(logging.DEBUG, logger="custom_components.crestron_home"):
        asyncio.run(_async_test())


def test_login_transport_failure_keeps_controller_details_out_of_traceback(
    monkeypatch, caplog,
) -> None:
    """Verify the traceback a caller can log after a transport failure."""

    async def run():
        hass = FakeHass(asyncio.get_running_loop())
        private_host = "fictional-controller.invalid"
        private_token = "fictional-access-token"

        class FailingTransport:
            def get(self, url, *, headers, **_kwargs):
                assert private_host in url
                assert private_token in headers.values()
                raise api.ClientError(f"Error with {url} and {headers}")

        monkeypatch.setattr(api, "async_get_clientsession", lambda _hass: FailingTransport())
        client = api.ApiClient(hass, private_host, private_token)
        try:
            await client.async_login()
        except api.CannotConnectError:
            logging.getLogger(__name__).exception("Setup could not connect")
        else:
            pytest.fail("Expected login to fail")

    with caplog.at_level(logging.DEBUG):
        asyncio.run(run())
    assert "Error communicating with controller" in caplog.text
    assert "fictional-controller.invalid" not in caplog.text
    assert "fictional-access-token" not in caplog.text


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

        try:
            await asyncio.wait_for(batcher.enqueue("shade-1", 1234), timeout=5)
            await asyncio.wait_for(batcher.async_flush(), timeout=5)
        finally:
            await asyncio.wait_for(batcher.async_shutdown(), timeout=5)

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
