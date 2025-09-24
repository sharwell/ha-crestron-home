"""Batch writer for Crestron Home shade commands."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.translation import async_get_cached_translations

from .api import ApiClient, CrestronHomeApiError, ShadeCommandFailedError, ShadeCommandResult
from .const import BATCH_DEBOUNCE_MS, BATCH_MAX_ITEMS, DOMAIN

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
    ) -> None:
        self._hass = hass
        self._client = client
        self._debounce_seconds = max(0, debounce_ms) / 1000
        self._max_items = max(1, max_items)
        self._lock = asyncio.Lock()
        self._queue: dict[str, _QueuedItem] = {}
        self._waiters: dict[str, list[asyncio.Future[None]]] = defaultdict(list)
        self._timer: asyncio.TimerHandle | None = None
        self._flush_task: asyncio.Task[None] | None = None
        self._closed = False
        self._on_success = on_success

    async def enqueue(self, shade_id: str, position: int) -> None:
        """Enqueue a shade write request and wait for completion."""

        if self._closed:
            raise HomeAssistantError(self._translate("error_write_disabled"))

        future: asyncio.Future[None] = self._hass.loop.create_future()
        self._queue[shade_id] = _QueuedItem(shade_id=shade_id, position=position)
        self._waiters[shade_id].append(future)

        if len(self._queue) >= self._max_items:
            self._cancel_timer()
            await self._flush_now()
        else:
            self._schedule_timer()

        await future

    def _schedule_timer(self) -> None:
        if self._debounce_seconds <= 0:
            self._hass.async_create_task(self._flush_now())
            return
        if self._timer is not None:
            return

        def _on_timer() -> None:
            self._timer = None
            self._hass.async_create_task(self._flush_now())

        self._timer = self._hass.loop.call_later(self._debounce_seconds, _on_timer)

    def _cancel_timer(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    async def _flush_now(self) -> None:
        if self._flush_task and not self._flush_task.done():
            await self._flush_task
            return

        self._flush_task = self._hass.async_create_task(self._flush())
        try:
            await self._flush_task
        finally:
            self._flush_task = None

    async def _flush(self) -> None:
        async with self._lock:
            if not self._queue:
                return

            queued_items = self._queue
            waiters = self._waiters
            self._queue = {}
            self._waiters = defaultdict(list)

        payload_items = [
            {"id": item.shade_id, "position": item.position}
            for item in queued_items.values()
        ]

        ids = [item.shade_id for item in queued_items.values()]

        payload = {"shades": payload_items}

        _LOGGER.debug("POST /shades/SetState payload=%s", payload)

        try:
            response = await self._client.async_set_shade_positions(payload_items)
        except ShadeCommandFailedError as err:
            error = HomeAssistantError(self._translate("error_write_failed"))
            self._reject_all(waiters, error)
            raise error from err
        except CrestronHomeApiError as err:
            error = HomeAssistantError(self._translate("error_write_failed"))
            self._reject_all(waiters, error)
            raise error from err
        except Exception as err:  # pragma: no cover - defensive safeguard
            error = HomeAssistantError(self._translate("error_write_failed"))
            self._reject_all(waiters, error)
            raise error from err

        status = response.status
        _LOGGER.debug(
            "POST /shades/SetState items=%s ids=%s status=%s",
            len(payload_items),
            ids,
            status,
        )

        if self._on_success is not None:
            self._on_success()

        default_status = "success" if status in {"success", "partial"} else status

        failed: dict[str, ShadeCommandResult] = {}
        for shade_id, item in queued_items.items():
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
        self._cancel_timer()
        if self._queue:
            try:
                await self._flush_now()
            except HomeAssistantError:
                pass
        if self._flush_task and not self._flush_task.done():
            await self._flush_task

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
