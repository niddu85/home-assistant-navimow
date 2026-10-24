"""Fixtures for Navimow tests."""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.navimow.api import API_BASE_URL, SMARTHOME_URL
from custom_components.navimow.const import (
    CONF_ACCESS_TOKEN,
    CONF_EXPIRES_AT,
    CONF_REFRESH_TOKEN,
    DOMAIN,
)

DEVICES_URL = f"{SMARTHOME_URL}/authList"
STATUS_URL = f"{SMARTHOME_URL}/getVehicleStatus"
COMMAND_URL = f"{SMARTHOME_URL}/sendCommands"
MQTT_INFO_URL = f"{API_BASE_URL}/mqtt/userInfo/get/v2"

DEVICE = {"id": "dev1", "name": "My Mower", "model": "i105E", "firmware_version": "1.2.3"}
STATUS = {
    "id": "dev1",
    "vehicleState": "isDocked",
    "online": True,
    "capacityRemaining": [{"rawValue": 80}],
    "position": {"lat": 45.0, "lng": 9.0},
}
TOKEN_RESPONSE = {"access_token": "new-access", "refresh_token": "new-refresh", "expires_in": 3600}


def ok(payload: dict) -> dict:
    """Build a successful Navimow API response."""
    return {"code": 1, "data": {"payload": payload}}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading the custom integration in every test."""
    return


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """Config entry with a valid access token."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="My Navimow",
        data={
            CONF_ACCESS_TOKEN: "access",
            CONF_REFRESH_TOKEN: "refresh",
            CONF_EXPIRES_AT: time.time() + 3600,
        },
    )


@pytest.fixture
def mock_mqtt():
    """Replace the MQTT client: tests must not open network connections."""
    with patch("custom_components.navimow.NavimowMqttClient", autospec=True) as mock:
        yield mock
