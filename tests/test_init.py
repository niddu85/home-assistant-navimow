"""Tests for setup, entities and coordinator of the Navimow integration."""
from __future__ import annotations

from datetime import timedelta

import aiohttp
import pytest
from homeassistant.components.lawn_mower import (
    DOMAIN as LAWN_MOWER_DOMAIN,
)
from homeassistant.components.lawn_mower import (
    SERVICE_DOCK,
    LawnMowerActivity,
)
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID, STATE_OFF, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.navimow.const import CONF_ACCESS_TOKEN, CONF_REFRESH_TOKEN, TOKEN_URL

from .conftest import COMMAND_URL, DEVICE, DEVICES_URL, STATUS, STATUS_URL, TOKEN_RESPONSE, ok

MOWER = "lawn_mower.my_mower"
BATTERY = "sensor.my_mower_battery"
ERROR = "sensor.my_mower_error"
CONNECTIVITY = "binary_sensor.my_mower_connectivity"
TRACKER = "device_tracker.my_mower_position"


def _mock_api(aioclient_mock: AiohttpClientMocker, status: dict | None = None) -> None:
    aioclient_mock.get(DEVICES_URL, json=ok({"devices": [DEVICE]}))
    aioclient_mock.post(STATUS_URL, json=ok({"devices": [status or STATUS]}))


def _expired(entry: MockConfigEntry) -> MockConfigEntry:
    return MockConfigEntry(
        domain=entry.domain, title=entry.title, data={**entry.data, "expires_at": 0}
    )


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_setup_creates_entities(
    hass: HomeAssistant, aioclient_mock, config_entry, mock_mqtt
) -> None:
    _mock_api(aioclient_mock)
    await _setup(hass, config_entry)

    assert config_entry.state is ConfigEntryState.LOADED
    assert hass.states.get(MOWER).state == LawnMowerActivity.DOCKED
    assert hass.states.get(BATTERY).state == "80"
    assert hass.states.get(ERROR).state == "none"
    assert hass.states.get(CONNECTIVITY).state == "on"
    tracker = hass.states.get(TRACKER)
    assert tracker.attributes["latitude"] == 45.0
    assert tracker.attributes["longitude"] == 9.0
    mock_mqtt.return_value.async_start.assert_called_once()


async def test_unload_stops_mqtt(
    hass: HomeAssistant, aioclient_mock, config_entry, mock_mqtt
) -> None:
    _mock_api(aioclient_mock)
    await _setup(hass, config_entry)

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.NOT_LOADED
    mock_mqtt.return_value.async_stop.assert_called_once()


async def test_setup_retries_when_servers_unreachable(
    hass: HomeAssistant, aioclient_mock, config_entry, mock_mqtt
) -> None:
    aioclient_mock.get(DEVICES_URL, exc=aiohttp.ClientError())
    await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_expired_token_at_startup_is_refreshed_first(
    hass: HomeAssistant, aioclient_mock, config_entry, mock_mqtt
) -> None:
    """After a long downtime the stored token is expired: refresh before authList."""
    config_entry = _expired(config_entry)
    _mock_api(aioclient_mock)
    aioclient_mock.post(TOKEN_URL, json=TOKEN_RESPONSE)
    await _setup(hass, config_entry)

    assert config_entry.state is ConfigEntryState.LOADED
    assert str(aioclient_mock.mock_calls[0][1]) == TOKEN_URL
    assert config_entry.data[CONF_ACCESS_TOKEN] == "new-access"
    assert config_entry.data[CONF_REFRESH_TOKEN] == "new-refresh"
    assert hass.states.get(MOWER) is not None


async def test_rejected_refresh_token_starts_reauth(
    hass: HomeAssistant, aioclient_mock, config_entry, mock_mqtt
) -> None:
    config_entry = _expired(config_entry)
    aioclient_mock.post(TOKEN_URL, status=400, json={"error": "invalid_grant"})
    await _setup(hass, config_entry)

    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert [f["context"]["source"] for f in flows] == [SOURCE_REAUTH]


@pytest.mark.parametrize(
    ("raw_state", "expected"),
    [
        ("isRunning", LawnMowerActivity.MOWING),
        ("isPaused", LawnMowerActivity.PAUSED),
        ("isDocking", LawnMowerActivity.RETURNING),
        ("isLifted", LawnMowerActivity.ERROR),
        ("somethingNew", STATE_UNKNOWN),
    ],
)
async def test_activity_mapping(
    hass: HomeAssistant, aioclient_mock, config_entry, mock_mqtt, raw_state, expected
) -> None:
    _mock_api(aioclient_mock, {**STATUS, "vehicleState": raw_state})
    await _setup(hass, config_entry)
    assert hass.states.get(MOWER).state == expected


@pytest.mark.parametrize("status", [{"vehicleState": "Offline"}, {"online": False}])
async def test_offline_mower(
    hass: HomeAssistant, aioclient_mock, config_entry, mock_mqtt, status
) -> None:
    _mock_api(aioclient_mock, {**STATUS, **status})
    await _setup(hass, config_entry)

    assert hass.states.get(MOWER).state == STATE_UNAVAILABLE
    assert hass.states.get(BATTERY).state == STATE_UNAVAILABLE
    assert hass.states.get(CONNECTIVITY).state == STATE_OFF


async def test_failed_command_raises(
    hass: HomeAssistant, aioclient_mock, config_entry, mock_mqtt
) -> None:
    _mock_api(aioclient_mock)
    aioclient_mock.post(COMMAND_URL, json={"code": 0, "desc": "DEVICE_BUSY"})
    await _setup(hass, config_entry)

    with pytest.raises(HomeAssistantError, match="DEVICE_BUSY"):
        await hass.services.async_call(
            LAWN_MOWER_DOMAIN, SERVICE_DOCK, {ATTR_ENTITY_ID: MOWER}, blocking=True
        )


async def test_mqtt_updates(
    hass: HomeAssistant, aioclient_mock, config_entry, mock_mqtt
) -> None:
    _mock_api(aioclient_mock)
    await _setup(hass, config_entry)
    handle = config_entry.runtime_data.async_handle_mqtt_message

    handle("/downlink/vehicle/dev1/realtimeDate/state", {"state": "isRunning", "battery": 55})
    await hass.async_block_till_done()
    assert hass.states.get(MOWER).state == LawnMowerActivity.MOWING
    assert hass.states.get(BATTERY).state == "55"

    handle("/downlink/vehicle/dev1/realtimeDate/event", {"event": "stuck", "level": "error"})
    await hass.async_block_till_done()
    assert hass.states.get(MOWER).state == LawnMowerActivity.ERROR
    assert hass.states.get(ERROR).state == "stuck"

    # Unknown devices are ignored
    handle("/downlink/vehicle/other/realtimeDate/state", {"state": "isRunning"})


async def test_mqtt_error_survives_poll_while_still_in_error(
    hass: HomeAssistant, aioclient_mock, config_entry, mock_mqtt
) -> None:
    _mock_api(aioclient_mock, {**STATUS, "vehicleState": "Error"})
    await _setup(hass, config_entry)
    config_entry.runtime_data.async_handle_mqtt_message(
        "/downlink/vehicle/dev1/realtimeDate/event", {"event": "stuck", "level": "error"}
    )

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=31))
    await hass.async_block_till_done()

    assert hass.states.get(ERROR).state == "stuck"
