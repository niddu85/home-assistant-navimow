"""API client for Segway Navimow."""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Callable
from typing import Any
from urllib.parse import urlencode

import aiohttp

from .const import (
    API_BASE_URL,
    AUTH_BASE_URL,
    CLIENT_ID,
    CLIENT_SECRET,
    CONF_ACCESS_TOKEN,
    CONF_EXPIRES_AT,
    CONF_REFRESH_TOKEN,
    TOKEN_URL,
)

_LOGGER = logging.getLogger(__name__)

SMARTHOME_URL = f"{API_BASE_URL}/smarthome"
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)
# Refresh the access token this many seconds before it actually expires
TOKEN_EXPIRY_MARGIN = 60
DEFAULT_TOKEN_LIFETIME = 3600

AUTH_ERROR_CODES = {4005}
AUTH_ERROR_DESCS = {"TOKEN_EXPIRED", "CODE_OAUTH_INFO_ILLEGAL"}


class NavimowError(Exception):
    """Generic Navimow API error."""


class NavimowConnectionError(NavimowError):
    """Navimow servers could not be reached."""


class NavimowAuthError(NavimowError):
    """Credentials were rejected and the user must log in again."""


def build_authorize_url(redirect_uri: str, state: str) -> str:
    """Return the URL of the Navimow login page."""
    params = {
        "channel": "homeassistant",
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "state": state,
    }
    return f"{AUTH_BASE_URL}?{urlencode(params)}"


async def async_request_token(
    session: aiohttp.ClientSession, payload: dict[str, str]
) -> dict[str, Any]:
    """Call the OAuth token endpoint and return the token response."""
    payload = {**payload, "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET}
    try:
        async with session.post(
            TOKEN_URL, data=payload, timeout=REQUEST_TIMEOUT
        ) as response:
            if response.status >= 500:
                raise NavimowConnectionError(
                    f"Token endpoint returned HTTP {response.status}"
                )
            token_data = await response.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError, ValueError) as err:
        raise NavimowConnectionError(f"Token request failed: {err}") from err

    if not isinstance(token_data, dict) or "access_token" not in token_data:
        # Only log the error fields: the body may echo credentials back
        reason = ""
        if isinstance(token_data, dict):
            reason = token_data.get("error") or token_data.get("desc") or ""
        raise NavimowAuthError(
            f"Token request rejected (HTTP {response.status}) {reason}".strip()
        )
    return token_data


async def async_exchange_code(
    session: aiohttp.ClientSession, code: str, redirect_uri: str
) -> dict[str, Any]:
    """Exchange an OAuth authorization code for tokens."""
    return await async_request_token(
        session,
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        },
    )


def token_data_to_entry_data(
    token_data: dict[str, Any], fallback_refresh_token: str | None = None
) -> dict[str, Any]:
    """Convert a token endpoint response to the config entry data format."""
    try:
        lifetime = int(token_data.get("expires_in") or DEFAULT_TOKEN_LIFETIME)
    except (TypeError, ValueError):
        lifetime = DEFAULT_TOKEN_LIFETIME
    return {
        CONF_ACCESS_TOKEN: token_data["access_token"],
        CONF_REFRESH_TOKEN: token_data.get("refresh_token") or fallback_refresh_token,
        CONF_EXPIRES_AT: time.time() + lifetime,
    }


class NavimowApiClient:
    """Handles REST communication with Navimow API, including token refresh."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        access_token: str,
        refresh_token: str | None,
        expires_at: float = 0.0,
        token_update_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._session = session
        self._access_token = access_token
        self._refresh_token = refresh_token
        self._expires_at = expires_at
        self._token_update_callback = token_update_callback
        # Refresh tokens rotate: two concurrent refreshes would invalidate each
        # other, so every refresh goes through this lock.
        self._token_lock = asyncio.Lock()

    async def async_get_access_token(self) -> str:
        """Return a valid access token, refreshing it if it is about to expire."""
        await self._async_refresh_token()
        return self._access_token

    async def _async_refresh_token(self, rejected_token: str | None = None) -> None:
        """Refresh the access token.

        Without rejected_token the refresh only happens if the token is about to
        expire. With rejected_token it happens unless another caller already
        replaced that token while we were waiting for the lock.
        """
        async with self._token_lock:
            if rejected_token is None:
                if time.time() < self._expires_at - TOKEN_EXPIRY_MARGIN:
                    return
            elif rejected_token != self._access_token:
                return

            if not self._refresh_token:
                raise NavimowAuthError("No refresh token available")

            token_data = await async_request_token(
                self._session,
                {"grant_type": "refresh_token", "refresh_token": self._refresh_token},
            )
            entry_data = token_data_to_entry_data(token_data, self._refresh_token)
            self._access_token = entry_data[CONF_ACCESS_TOKEN]
            self._refresh_token = entry_data[CONF_REFRESH_TOKEN]
            self._expires_at = entry_data[CONF_EXPIRES_AT]
            _LOGGER.debug("OAuth token refreshed")
            if self._token_update_callback:
                self._token_update_callback(entry_data)

    async def _async_raw_request(
        self, method: str, url: str, token: str, json: dict | None
    ) -> tuple[int, dict[str, Any]]:
        """Perform a single HTTP request and return status and JSON body."""
        headers = {
            "Authorization": f"Bearer {token}",
            "requestId": str(uuid.uuid4())[:32],
        }
        try:
            async with self._session.request(
                method, url, headers=headers, json=json, timeout=REQUEST_TIMEOUT
            ) as response:
                if response.status == 401:
                    return response.status, {}
                if response.status >= 500:
                    raise NavimowConnectionError(
                        f"{url} returned HTTP {response.status}"
                    )
                body = await response.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise NavimowConnectionError(f"Request to {url} failed: {err}") from err

        if not isinstance(body, dict):
            raise NavimowError(f"Unexpected response from {url}")
        return response.status, body

    @staticmethod
    def _is_auth_error(status: int, body: dict[str, Any]) -> bool:
        return (
            status == 401
            or body.get("code") in AUTH_ERROR_CODES
            or body.get("desc") in AUTH_ERROR_DESCS
        )

    async def _async_request(
        self, method: str, url: str, json: dict | None = None
    ) -> dict[str, Any]:
        """Perform an authenticated API call and return the response data."""
        token = await self.async_get_access_token()
        status, body = await self._async_raw_request(method, url, token, json)

        if self._is_auth_error(status, body):
            _LOGGER.debug("Access token rejected by %s, refreshing", url)
            await self._async_refresh_token(rejected_token=token)
            status, body = await self._async_raw_request(
                method, url, self._access_token, json
            )
            if self._is_auth_error(status, body):
                raise NavimowAuthError("Access token rejected after refresh")

        if body.get("code") != 1:
            raise NavimowError(
                f"Navimow API error {body.get('code')}: {body.get('desc')}"
            )
        data = body.get("data")
        return data if isinstance(data, dict) else {}

    async def async_get_devices(self) -> list[dict[str, Any]]:
        """Fetch the list of devices linked to the account."""
        data = await self._async_request("GET", f"{SMARTHOME_URL}/authList")
        return data.get("payload", {}).get("devices", [])

    async def async_get_vehicles_status(
        self, device_ids: list[str]
    ) -> dict[str, dict[str, Any]]:
        """Fetch vehicle status for multiple devices, keyed by device id."""
        if not device_ids:
            return {}
        data = await self._async_request(
            "POST",
            f"{SMARTHOME_URL}/getVehicleStatus",
            {"devices": [{"id": d_id} for d_id in device_ids]},
        )
        devices = data.get("payload", {}).get("devices", [])
        return {d["id"]: d for d in devices if "id" in d}

    async def async_send_command(
        self, device_id: str, command: str, params: dict | None = None
    ) -> None:
        """Send a command to a device. Raises NavimowError on failure."""
        await self._async_request(
            "POST",
            f"{SMARTHOME_URL}/sendCommands",
            {
                "commands": [
                    {
                        "devices": [{"id": device_id}],
                        "execution": {"command": command, "params": params},
                    }
                ]
            },
        )

    async def async_get_mqtt_info(self) -> dict[str, Any]:
        """Fetch MQTT broker connection info and credentials."""
        return await self._async_request("GET", f"{API_BASE_URL}/mqtt/userInfo/get/v2")
