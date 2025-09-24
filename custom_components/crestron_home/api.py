"""REST API client for Crestron Home."""

from __future__ import annotations

import asyncio
import logging
import time
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

            auth_key = data.get("AuthKey")
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

    async def async_logout(self) -> None:
        """Close the API session and forget credentials."""

        self._auth_key = None
        self._last_used = None

        self._session = None

    async def async_close(self) -> None:
        """Alias for logout for compatibility."""

        await self.async_logout()
