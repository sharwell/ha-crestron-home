"""Batch writer for Crestron Home shade commands."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from itertools import batched
from typing import Any, Sequence

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.translation import async_get_cached_translations

from .api import ApiClient, CrestronHomeApiError, ShadeCommandFailedError, ShadeCommandResult
from .const import (
    BATCH_DEBOUNCE_MS,
    BATCH_MAX_ITEMS,
    DOMAIN,
    LOG_KEY_BATCH,
    PATH_SHADES_SET_STATE,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class _QueuedItem:
    shade_id: str
    position: int


class ShadeWriteBatcher:
    """Batch writes to the Crestron Home shade API."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: ApiClient,
        *,
        debounce_ms: int = BATCH_DEBOUNCE_MS,
        max_items: int = BATCH_MAX_ITEMS,
        on_success: Callable[[], None] | None = None,
        on_flush: Callable[[Sequence[dict[str, int]], str | None], None] | None = None,
    ) -> None:
        self._hass = hass
        self._client = client
        self._debounce_seconds = max(0, debounce_ms) / 1000
        self._max_items = max(1, max_items)
        self._lock = asyncio.Lock()
        self._queue: dict[str, _QueuedItem] = {}
        self._waiters: dict[str, list[asyncio.Future[None]]] = defaultdict(list)
        self._timer: asyncio.TimerHandle | None = None
        self._closed = False
        self._on_success = on_success
        self._on_flush = on_flush

    async def enqueue(self, shade_id: str, position: int) -> None:
        """Enqueue a shade write request and wait for completion."""

        if self._closed:
            raise HomeAssistantError(self._translate("error_write_disabled"))

        future: asyncio.Future[None] = self._hass.loop.create_future()
        self._queue[shade_id] = _QueuedItem(shade_id=shade_id, position=position)
        self._waiters[shade_id].append(future)

        self._schedule_timer(immediate=len(self._queue) >= self._max_items)
        await future

    async def async_flush(self) -> None:
        """Flush the current queue immediately."""

        self._cancel_timer()
        await self._flush()

    def _schedule_timer(self, *, immediate: bool = False) -> None:
        if immediate:
            self._cancel_timer()
        if self._timer is not None:
            return

        def _on_timer() -> None:
            self._timer = None
            self._hass.async_create_task(self._flush_scheduled())

        delay = 0 if immediate else self._debounce_seconds
        self._timer = self._hass.loop.call_later(delay, _on_timer)

    def _cancel_timer(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    async def _flush_scheduled(self) -> None:
        try:
            await self._flush()
        except HomeAssistantError as err:
            # Affected enqueue callers receive the error via their own futures.
            _LOGGER.warning("Shade write batch failed: %s", err)

    async def _flush(self) -> None:
        async with self._lock:
            queued_items = self._queue
            waiters = self._waiters
            self._queue = {}
            self._waiters = defaultdict(list)

            first_error: HomeAssistantError | None = None
            try:
                for ids in batched(queued_items, self._max_items):
                    items = [queued_items[shade_id] for shade_id in ids]
                    batch_waiters = {shade_id: waiters[shade_id] for shade_id in ids}
                    try:
                        await self._send_batch(items, batch_waiters)
                    except HomeAssistantError as err:
                        if first_error is None:
                            first_error = err
            except asyncio.CancelledError:
                for futures in waiters.values():
                    for future in futures:
                        future.cancel()
                raise

            if first_error is not None:
                raise first_error

    async def _send_batch(
        self,
        items: list[_QueuedItem],
        waiters: dict[str, list[asyncio.Future[None]]],
    ) -> None:
        payload_items = [
            {"id": item.shade_id, "position": item.position}
            for item in items
        ]
        ids = [item.shade_id for item in items]

        status: str | None = None
        try:
            response = await self._client.async_set_shade_positions(payload_items)
            status = response.status
        except ShadeCommandFailedError as err:
            status = "error"
            error = HomeAssistantError(self._translate("error_write_failed"))
            self._reject_all(waiters, error)
            raise error from err
        except CrestronHomeApiError as err:
            status = "error"
            error = HomeAssistantError(self._translate("error_write_failed"))
            self._reject_all(waiters, error)
            raise error from err
        except Exception as err:  # pragma: no cover - defensive safeguard
            status = "error"
            error = HomeAssistantError(self._translate("error_write_failed"))
            self._reject_all(waiters, error)
            raise error from err
        finally:
            if self._on_flush is not None:
                try:
                    self._on_flush(payload_items, status)
                except Exception:  # pragma: no cover - defensive safeguard
                    _LOGGER.exception("Unhandled exception from flush callback")

        status = response.status
        _LOGGER.debug(
            "POST %s items=%s ids=%s status=%s",
            PATH_SHADES_SET_STATE,
            len(payload_items),
            ids,
            status,
            extra={
                LOG_KEY_BATCH: {
                    "count": len(payload_items),
                    "ids": ids,
                    "status": status,
                }
            },
        )

        if self._on_success is not None:
            try:
                self._on_success()
            except Exception:  # pragma: no cover - defensive safeguard
                _LOGGER.exception("Unhandled exception from success callback")

        default_status = "success" if status in {"success", "partial"} else status

        failed: dict[str, ShadeCommandResult] = {}
        for shade_id in ids:
            result = response.results.get(shade_id)
            if result is None:
                result = ShadeCommandResult(status=default_status)

            if result.status != "success":
                failed[shade_id] = result
                error = HomeAssistantError(
                    self._translate(
                        "error_partial_write",
                        shade_id=shade_id,
                        reason=result.message or result.status,
                    )
                )
                for future in waiters.get(shade_id, []):
                    if not future.done():
                        future.set_exception(error)
            else:
                for future in waiters.get(shade_id, []):
                    if not future.done():
                        future.set_result(None)

        if failed:
            self._log_partial_failure(failed)
        else:
            self._resolve_remaining(waiters)

    def _reject_all(
        self,
        waiters: dict[str, list[asyncio.Future[None]]],
        err: Exception,
    ) -> None:
        for futures in waiters.values():
            for future in futures:
                if not future.done():
                    future.set_exception(err)

    def _resolve_remaining(self, waiters: dict[str, list[asyncio.Future[None]]]) -> None:
        for futures in waiters.values():
            for future in futures:
                if not future.done():
                    future.set_result(None)

    def _log_partial_failure(self, failed: dict[str, ShadeCommandResult]) -> None:
        entries = [
            "%s (%s)" % (shade_id, result.message or result.status)
            for shade_id, result in failed.items()
        ]
        _LOGGER.warning(
            "Partial shade write failure for ids: %s",
            ", ".join(entries),
        )

    async def async_shutdown(self) -> None:
        """Cancel scheduled flushes and process remaining items."""

        self._closed = True
        try:
            await self.async_flush()
        except HomeAssistantError:
            pass

    def _translate(self, key: str, **kwargs: Any) -> str:
        language = self._hass.config.language
        translations = async_get_cached_translations(
            self._hass, language, "exceptions", DOMAIN
        )
        translation_key = f"component.{DOMAIN}.exceptions.{key}.message"
        template = translations.get(translation_key)
        if not template:
            fallback = {
                "error_write_disabled": "Shade control is shutting down",
                "error_write_failed": "Failed to send shade command",
                "error_partial_write": "Shade command failed for {shade_id}: {reason}",
            }
            template = fallback.get(key, key)
        try:
            return template.format(**kwargs)
        except (KeyError, ValueError):
            return template
