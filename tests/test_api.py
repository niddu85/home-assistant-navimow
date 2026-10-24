"""Tests for the Navimow API client."""
from __future__ import annotations

import asyncio
import time
from unittest.mock import Mock

import aiohttp
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)

from custom_components.navimow.api import (
    NavimowApiClient,
    NavimowAuthError,
    NavimowConnectionError,
    NavimowError,
)
from custom_components.navimow.const import TOKEN_URL

from .conftest import COMMAND_URL, DEVICE, DEVICES_URL, STATUS, STATUS_URL, TOKEN_RESPONSE, ok


def _client(hass: HomeAssistant, expires_at: float | None = None, callback=None):
    return NavimowApiClient(
        async_get_clientsession(hass),
        "access",
        "refresh",
        time.time() + 3600 if expires_at is None else expires_at,
        callback,
    )


def _sequence(*responses):
    """Side effect returning the given JSON bodies in order."""
    remaining = list(responses)

    async def side_effect(method, url, data):
        return AiohttpClientMockResponse(method, url, json=remaining.pop(0))

    return side_effect


async def test_get_devices(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(DEVICES_URL, json=ok({"devices": [DEVICE]}))
    assert await _client(hass).async_get_devices() == [DEVICE]
    assert aioclient_mock.mock_calls[0][3]["Authorization"] == "Bearer access"


async def test_rejected_token_is_refreshed_and_request_retried(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    callback = Mock()
    aioclient_mock.post(
        STATUS_URL,
        side_effect=_sequence(
            {"code": 4005, "desc": "TOKEN_EXPIRED"}, ok({"devices": [STATUS]})
        ),
    )
    aioclient_mock.post(TOKEN_URL, json=TOKEN_RESPONSE)

    data = await _client(hass, callback=callback).async_get_vehicles_status(["dev1"])

    assert data == {"dev1": STATUS}
    token_calls = [c for c in aioclient_mock.mock_calls if str(c[1]) == TOKEN_URL]
    assert len(token_calls) == 1
    assert token_calls[0][2]["refresh_token"] == "refresh"
    assert aioclient_mock.mock_calls[-1][3]["Authorization"] == "Bearer new-access"
    saved = callback.call_args[0][0]
    assert saved["access_token"] == "new-access"
    assert saved["refresh_token"] == "new-refresh"
    assert saved["expires_at"] > time.time() + 3000


async def test_concurrent_requests_refresh_once(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """With rotating refresh tokens a second refresh would break the session."""
    aioclient_mock.get(DEVICES_URL, json=ok({"devices": [DEVICE]}))
    aioclient_mock.post(TOKEN_URL, json=TOKEN_RESPONSE)
    client = _client(hass, expires_at=0)

    await asyncio.gather(client.async_get_devices(), client.async_get_devices())

    assert sum(str(c[1]) == TOKEN_URL for c in aioclient_mock.mock_calls) == 1


async def test_rejected_refresh_token_raises_auth_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.post(TOKEN_URL, status=400, json={"error": "invalid_grant"})
    with pytest.raises(NavimowAuthError):
        await _client(hass, expires_at=0).async_get_devices()


async def test_token_still_rejected_after_refresh(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(DEVICES_URL, status=401)
    aioclient_mock.post(TOKEN_URL, json=TOKEN_RESPONSE)
    with pytest.raises(NavimowAuthError):
        await _client(hass).async_get_devices()


@pytest.mark.parametrize(
    "mock_kwargs", [{"exc": aiohttp.ClientError()}, {"exc": TimeoutError()}, {"status": 502}]
)
async def test_connection_errors(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_kwargs: dict
) -> None:
    aioclient_mock.get(DEVICES_URL, **mock_kwargs)
    with pytest.raises(NavimowConnectionError):
        await _client(hass).async_get_devices()


async def test_refresh_network_error_is_not_auth_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.post(TOKEN_URL, exc=aiohttp.ClientError())
    with pytest.raises(NavimowConnectionError):
        await _client(hass, expires_at=0).async_get_devices()


async def test_failed_command_raises(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.post(COMMAND_URL, json={"code": 0, "desc": "DEVICE_OFFLINE"})
    with pytest.raises(NavimowError, match="DEVICE_OFFLINE"):
        await _client(hass).async_send_command("dev1", "action.devices.commands.Dock")
