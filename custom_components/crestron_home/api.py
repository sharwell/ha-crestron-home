"""REST API client for Crestron Home."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

from aiohttp import ClientError, ClientResponseError, ClientSession, ClientTimeout, ContentTypeError
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession, async_get_clientsession

from .const import (
    DEFAULT_VERIFY_SSL,
    HEADER_ACCEPT,
    HEADER_AUTH_KEY,
    HEADER_AUTH_TOKEN,
    MIME_TYPE_JSON,
    PATH_LOGIN,
    PATH_ROOMS,
    PATH_SHADES,
    PATH_SHADES_SET_STATE,
    REQUEST_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)

HTTP_UNAUTHORIZED = 401
HTTP_NETWORK_AUTH_REQUIRED = 511


class CrestronHomeApiError(Exception):
    """Base exception raised for API client errors."""


class InvalidAuthError(CrestronHomeApiError):
    """Raised when authentication fails."""


class CannotConnectError(CrestronHomeApiError):
    """Raised when the controller cannot be reached."""


class ShadeCommandFailedError(CrestronHomeApiError):
    """Raised when a SetState command fails for all shades."""


@dataclass(slots=True)
class ShadeCommandResult:
    """Result for a single shade command."""

    status: str
    message: str | None = None


@dataclass(slots=True)
class ShadeCommandResponse:
    """Structured response from the SetState endpoint."""

    status: str
    results: dict[str, ShadeCommandResult]


class ApiClient:
    """Client wrapping the Crestron Home REST API."""

    def __init__(
        self,
        hass: HomeAssistant,
        host: str,
        api_token: str,
        *,
        verify_ssl: bool = DEFAULT_VERIFY_SSL,
    ) -> None:
        self._hass = hass
        self._host = host
        self._api_token = api_token
        self._verify_ssl = verify_ssl
        self._session: ClientSession | None = None
        self._auth_key: str | None = None
        self._timeout = ClientTimeout(total=REQUEST_TIMEOUT)
        self._last_used: float | None = None
        self._login_lock = asyncio.Lock()

    @property
    def host(self) -> str:
        """Return the configured host."""

        return self._host

    def _build_url(self, path: str) -> str:
        return f"https://{self._host}{path}"

    def _ensure_session(self) -> ClientSession:
        if self._session is not None:
            return self._session

        if self._verify_ssl:
            self._session = async_get_clientsession(self._hass)
        else:
            self._session = async_create_clientsession(self._hass, verify_ssl=False)

        return self._session

    async def async_login(self, *, force: bool = False) -> None:
        """Authenticate and store the auth key."""

        async with self._login_lock:
            if self._auth_key and not force:
                return

            session = self._ensure_session()
            url = self._build_url(PATH_LOGIN)
            headers = {
                HEADER_ACCEPT: MIME_TYPE_JSON,
                HEADER_AUTH_TOKEN: self._api_token,
            }

            _LOGGER.debug("Requesting auth key from %s", url)
            try:
                async with session.get(url, headers=headers, timeout=self._timeout) as response:
                    if response.status in (HTTP_UNAUTHORIZED, HTTP_NETWORK_AUTH_REQUIRED):
                        raise InvalidAuthError("Invalid API token provided")
                    response.raise_for_status()
                    data = await response.json()
            except InvalidAuthError:
                raise
            except ClientResponseError as err:
                raise CannotConnectError("Unexpected response from controller") from err
            except (ClientError, asyncio.TimeoutError) as err:
                raise CannotConnectError("Error communicating with controller") from err
            except (ContentTypeError, ValueError) as err:
                raise CrestronHomeApiError("Controller response was not JSON") from err

            auth_key = data.get("authkey")
            if not auth_key:
                raise CrestronHomeApiError("Controller response did not include an auth key")

            self._auth_key = auth_key
            self._last_used = time.monotonic()
            _LOGGER.debug("Successfully obtained auth key")

    async def async_request(self, method: str, path: str, *, retry: bool = True) -> Any:
        """Make an authenticated request to the REST API."""

        await self.async_login()

        session = self._ensure_session()
        url = self._build_url(path)
        headers = {
            HEADER_ACCEPT: MIME_TYPE_JSON,
            HEADER_AUTH_KEY: self._auth_key or "",
        }

        _LOGGER.debug("Requesting %s %s", method, url)

        try:
            async with session.request(
                method,
                url,
                headers=headers,
                timeout=self._timeout,
            ) as response:
                if response.status in (HTTP_UNAUTHORIZED, HTTP_NETWORK_AUTH_REQUIRED):
                    if retry:
                        _LOGGER.debug("Auth key expired, retrying request after reauthentication")
                        await self.async_login(force=True)
                        return await self.async_request(method, path, retry=False)
                    raise InvalidAuthError("Authentication failed after retry")

                response.raise_for_status()

                if response.content_type == MIME_TYPE_JSON:
                    data = await response.json()
                else:
                    data = await response.text()
        except InvalidAuthError:
            raise
        except ClientResponseError as err:
            raise CrestronHomeApiError("Unexpected response from controller") from err
        except (ClientError, asyncio.TimeoutError) as err:
            raise CannotConnectError("Error communicating with controller") from err
        except (ContentTypeError, ValueError) as err:
            raise CrestronHomeApiError("Controller response was not JSON") from err

        self._last_used = time.monotonic()
        return data

    async def async_get_rooms(self) -> list[Any]:
        """Return the list of rooms from the controller."""

        data = await self.async_request("GET", PATH_ROOMS)

        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            # Some controllers may wrap the rooms list in an object.
            for key in ("rooms", "Rooms"):
                rooms = data.get(key)
                if isinstance(rooms, list):
                    return rooms

        raise CrestronHomeApiError("Rooms response was not a list")

    async def async_get_shades(self) -> list[Any]:
        """Return the list of shades from the controller."""

        data = await self.async_request("GET", PATH_SHADES)

        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("shades", "Shades"):
                shades = data.get(key)
                if isinstance(shades, list):
                    return shades

        raise CrestronHomeApiError("Shades response was not a list")

    async def async_get_shade(self, shade_id: str | int) -> dict[str, Any]:
        """Return details for a specific shade."""

        data = await self.async_request("GET", f"{PATH_SHADES}/{shade_id}")

        if isinstance(data, dict):
            return data

        raise CrestronHomeApiError("Shade response was not an object")

    async def async_set_shade_positions(
        self, items: list[dict[str, int]], *, retry: bool = True
    ) -> ShadeCommandResponse:
        """Send a batch of shade position updates to the controller."""

        if not items:
            return ShadeCommandResponse(status="success", results={})

        await self.async_login()

        session = self._ensure_session()
        url = self._build_url(PATH_SHADES_SET_STATE)
        headers = {
            HEADER_ACCEPT: MIME_TYPE_JSON,
            HEADER_AUTH_KEY: self._auth_key or "",
            "Content-Type": MIME_TYPE_JSON,
        }

        try:
            async with session.post(
                url,
                headers=headers,
                json=items,
                timeout=self._timeout,
            ) as response:
                if response.status in (HTTP_UNAUTHORIZED, HTTP_NETWORK_AUTH_REQUIRED):
                    if retry:
                        _LOGGER.debug(
                            "Auth key expired during SetState, retrying after reauthentication"
                        )
                        await self.async_login(force=True)
                        return await self.async_set_shade_positions(items, retry=False)
                    raise InvalidAuthError("Authentication failed after retry")

                response.raise_for_status()

                try:
                    data = await response.json()
                except ContentTypeError as err:
                    raise CrestronHomeApiError(
                        "Controller response was not JSON"
                    ) from err
        except InvalidAuthError:
            raise
        except ClientResponseError as err:
            raise CrestronHomeApiError("Unexpected response from controller") from err
        except (ClientError, asyncio.TimeoutError) as err:
            raise CannotConnectError("Error communicating with controller") from err

        parsed = self._parse_set_state_response(data)
        if parsed.status == "failure":
            raise ShadeCommandFailedError("Controller rejected the shade command")

        self._last_used = time.monotonic()
        return parsed

    def _parse_set_state_response(self, data: Any) -> ShadeCommandResponse:
        if not isinstance(data, dict):
            raise CrestronHomeApiError("SetState response was not an object")

        status_raw = data.get("status")
        status = self._normalize_status(status_raw)
        if status is None:
            raise CrestronHomeApiError("SetState response did not include a status")

        results: dict[str, ShadeCommandResult] = {}
        raw_results = data.get("results") or data.get("items") or data.get("shades")
        if isinstance(raw_results, list):
            for entry in raw_results:
                if not isinstance(entry, dict):
                    continue
                raw_id = entry.get("id")
                if raw_id is None:
                    continue
                shade_id = str(raw_id)
                entry_status = self._normalize_status(entry.get("status"))
                if entry_status is None and "success" in entry:
                    entry_status = "success" if entry.get("success") else "failure"
                if entry_status is None and "result" in entry:
                    entry_status = self._normalize_status(entry.get("result"))
                message = self._extract_message(entry)
                results[shade_id] = ShadeCommandResult(
                    status=entry_status or ("success" if status != "failure" else "failure"),
                    message=message,
                )
        elif isinstance(raw_results, dict):
            for raw_id, entry in raw_results.items():
                shade_id = str(raw_id)
                if isinstance(entry, dict):
                    entry_status = self._normalize_status(entry.get("status"))
                    if entry_status is None and "success" in entry:
                        entry_status = "success" if entry.get("success") else "failure"
                    message = self._extract_message(entry)
                else:
                    entry_status = self._normalize_status(entry)
                    message = None
                results[shade_id] = ShadeCommandResult(
                    status=entry_status or ("success" if status != "failure" else "failure"),
                    message=message,
                )

        return ShadeCommandResponse(status=status, results=results)

    @staticmethod
    def _normalize_status(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            lowered = value.strip().lower()
            return lowered or None
        if isinstance(value, bool):
            return "success" if value else "failure"
        if isinstance(value, (int, float)):
            return "success" if value else "failure"
        return None

    @staticmethod
    def _extract_message(entry: dict[str, Any]) -> str | None:
        for key in ("message", "error", "reason", "details"):
            value = entry.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    async def async_logout(self) -> None:
        """Close the API session and forget credentials."""

        self._auth_key = None
        self._last_used = None

        self._session = None

    async def async_close(self) -> None:
        """Alias for logout for compatibility."""

        await self.async_logout()
