"""Tests for the Navimow config flow."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.core_config import async_process_ha_core_config
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry
from yarl import URL

from custom_components.navimow.const import (
    CONF_ACCESS_TOKEN,
    CONF_DOCK_LATITUDE,
    CONF_DOCK_LONGITUDE,
    CONF_MAP_ROTATION,
    CONF_REFRESH_TOKEN,
    DOMAIN,
    TOKEN_URL,
)

from .conftest import DEVICE, DEVICES_URL, TOKEN_RESPONSE, ok

REDIRECT_URI = "http://ha.local:8123/api/navimow/callback"


@pytest.fixture(autouse=True)
async def setup_http(hass: HomeAssistant) -> None:
    await async_process_ha_core_config(hass, {"internal_url": "http://ha.local:8123"})
    assert await async_setup_component(hass, "http", {})


@pytest.fixture(autouse=True)
def mock_setup_entry():
    with patch("custom_components.navimow.async_setup_entry", return_value=True) as mock:
        yield mock


@pytest.fixture
def mock_oauth(aioclient_mock):
    aioclient_mock.post(TOKEN_URL, json=TOKEN_RESPONSE)
    aioclient_mock.get(DEVICES_URL, json=ok({"devices": [DEVICE]}))
    return aioclient_mock


async def _start_user_flow(hass: HomeAssistant) -> dict:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"account_name": "Garden"}
    )
    assert result["type"] is FlowResultType.EXTERNAL_STEP
    return result


async def test_full_flow(hass: HomeAssistant, hass_client_no_auth, mock_oauth) -> None:
    result = await _start_user_flow(hass)
    query = URL(result["url"]).query
    assert query["redirect_uri"] == REDIRECT_URI
    assert query["client_id"] == "homeassistant"

    client = await hass_client_no_auth()
    resp = await client.get(f"/api/navimow/callback?code=the-code&state={query['state']}")
    assert resp.status == 200

    result = await hass.config_entries.flow.async_configure(result["flow_id"])
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "dock"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"dock_location": {"latitude": 45.5, "longitude": 9.25}, "map_rotation": 30},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"] == {
        CONF_DOCK_LATITUDE: 45.5,
        CONF_DOCK_LONGITUDE: 9.25,
        CONF_MAP_ROTATION: 30.0,
    }
    assert result["title"] == "Garden"
    assert result["data"][CONF_ACCESS_TOKEN] == "new-access"
    assert result["data"][CONF_REFRESH_TOKEN] == "new-refresh"

    token_request = mock_oauth.mock_calls[0][2]
    assert token_request["code"] == "the-code"
    assert token_request["redirect_uri"] == REDIRECT_URI


async def test_callback_without_state_single_flow(
    hass: HomeAssistant, hass_client_no_auth, mock_oauth
) -> None:
    """The login page might not echo state back."""
    result = await _start_user_flow(hass)
    client = await hass_client_no_auth()
    resp = await client.get("/api/navimow/callback?code=the-code")
    assert resp.status == 200

    result = await hass.config_entries.flow.async_configure(result["flow_id"])
    assert result["step_id"] == "dock"


async def test_callback_rejects_unknown_state(
    hass: HomeAssistant, hass_client_no_auth, mock_oauth
) -> None:
    await _start_user_flow(hass)
    client = await hass_client_no_auth()
    resp = await client.get("/api/navimow/callback?code=the-code&state=forged")
    assert resp.status == 400
    assert len(mock_oauth.mock_calls) == 0


async def test_second_flow_gets_its_own_code(
    hass: HomeAssistant, hass_client_no_auth, mock_oauth
) -> None:
    """An abandoned flow must not steal the code of a later one."""
    first = await _start_user_flow(hass)
    hass.config_entries.flow.async_abort(first["flow_id"])
    second = await _start_user_flow(hass)

    client = await hass_client_no_auth()
    resp = await client.get("/api/navimow/callback?code=the-code")
    assert resp.status == 200
    result = await hass.config_entries.flow.async_configure(second["flow_id"])
    assert result["step_id"] == "dock"


async def test_token_exchange_rejected(
    hass: HomeAssistant, hass_client_no_auth, aioclient_mock
) -> None:
    aioclient_mock.post(TOKEN_URL, status=400, json={"error": "invalid_grant"})
    result = await _start_user_flow(hass)
    client = await hass_client_no_auth()
    await client.get(f"/api/navimow/callback?code=bad&state={URL(result['url']).query['state']}")

    result = await hass.config_entries.flow.async_configure(result["flow_id"])
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "auth_failed"


def _entry_with_device(hass: HomeAssistant, device_id: str = "dev1") -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN, title="Existing", data={CONF_ACCESS_TOKEN: "a", CONF_REFRESH_TOKEN: "r"}
    )
    entry.add_to_hass(hass)
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, device_id)}
    )
    return entry


async def test_account_already_configured(
    hass: HomeAssistant, hass_client_no_auth, mock_oauth
) -> None:
    _entry_with_device(hass)
    result = await _start_user_flow(hass)
    client = await hass_client_no_auth()
    await client.get(f"/api/navimow/callback?code=c&state={URL(result['url']).query['state']}")

    result = await hass.config_entries.flow.async_configure(result["flow_id"])
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def _run_reauth(hass: HomeAssistant, hass_client_no_auth, entry: MockConfigEntry) -> dict:
    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.EXTERNAL_STEP
    client = await hass_client_no_auth()
    await client.get(f"/api/navimow/callback?code=c&state={URL(result['url']).query['state']}")
    return await hass.config_entries.flow.async_configure(result["flow_id"])


async def test_reauth(hass: HomeAssistant, hass_client_no_auth, mock_oauth) -> None:
    entry = _entry_with_device(hass)
    result = await _run_reauth(hass, hass_client_no_auth, entry)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_ACCESS_TOKEN] == "new-access"
    assert entry.data[CONF_REFRESH_TOKEN] == "new-refresh"


async def test_reauth_wrong_account(
    hass: HomeAssistant, hass_client_no_auth, mock_oauth
) -> None:
    entry = _entry_with_device(hass, "another-mower")
    result = await _run_reauth(hass, hass_client_no_auth, entry)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_account"
    assert entry.data[CONF_ACCESS_TOKEN] == "a"


async def test_dock_defaults_to_home(
    hass: HomeAssistant, hass_client_no_auth, mock_oauth
) -> None:
    result = await _start_user_flow(hass)
    client = await hass_client_no_auth()
    await client.get(f"/api/navimow/callback?code=c&state={URL(result['url']).query['state']}")
    result = await hass.config_entries.flow.async_configure(result["flow_id"])

    defaults = {key.schema: key.default() for key in result["data_schema"].schema}
    assert defaults["dock_location"] == {
        "latitude": hass.config.latitude,
        "longitude": hass.config.longitude,
    }
    assert defaults["map_rotation"] == 0


async def test_options_flow(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ACCESS_TOKEN: "a", CONF_REFRESH_TOKEN: "r"},
        options={CONF_DOCK_LATITUDE: 45.0, CONF_DOCK_LONGITUDE: 9.0, CONF_MAP_ROTATION: 0.0},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"dock_location": {"latitude": 45.1, "longitude": 9.1}, "map_rotation": -12.5},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {
        CONF_DOCK_LATITUDE: 45.1,
        CONF_DOCK_LONGITUDE: 9.1,
        CONF_MAP_ROTATION: -12.5,
    }
