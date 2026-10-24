"""Tests for the Navimow MQTT client lifecycle."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.navimow.const import DOMAIN
from custom_components.navimow.mqtt import NavimowMqttClient

MQTT_INFO = {"mqttHost": "wss://mqtt.example.com", "userName": "u", "pwdInfo": "p"}


@pytest.fixture
def api() -> AsyncMock:
    api = AsyncMock()
    api.async_get_mqtt_info.return_value = MQTT_INFO
    api.async_get_access_token.return_value = "token"
    return api


@pytest.fixture
def paho_clients():
    """Fake paho clients handed out by _create_client, in order."""
    clients = [MagicMock(name=f"client{i}") for i in range(3)]
    with (
        patch.object(
            NavimowMqttClient, "_create_client", side_effect=[(c, "mqtt.example.com") for c in clients]
        ),
        patch("custom_components.navimow.mqtt._start_client") as start,
        patch("custom_components.navimow.mqtt._close_client") as close,
        patch("custom_components.navimow.mqtt.RECONNECT_MIN_DELAY", 0),
    ):
        yield clients, start, close


async def _started_client(hass: HomeAssistant, api, callback=None) -> NavimowMqttClient:
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    client = NavimowMqttClient(hass, entry, api, ["dev1"], callback or Mock())
    await client.async_start()
    return client


def _rc(failure: bool = False) -> MagicMock:
    reason = MagicMock()
    reason.is_failure = failure
    return reason


async def test_disconnect_reconnects_once_with_fresh_credentials(
    hass: HomeAssistant, api, paho_clients
) -> None:
    clients, start, close = paho_clients
    mqtt_client = await _started_client(hass, api)

    # paho may report the same disconnect more than once: only one reconnect
    mqtt_client._on_disconnect(clients[0], None, None, _rc(), None)
    mqtt_client._on_disconnect(clients[0], None, None, _rc(), None)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert start.call_count == 2
    close.assert_called_once_with(clients[0])
    assert api.async_get_mqtt_info.call_count == 2
    assert mqtt_client._client is clients[1]

    # Late callbacks from the replaced client are ignored
    mqtt_client._on_disconnect(clients[0], None, None, _rc(), None)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert start.call_count == 2

    await mqtt_client.async_stop()
    close.assert_called_with(clients[1])


async def test_refused_connection_reconnects(hass: HomeAssistant, api, paho_clients) -> None:
    clients, start, _ = paho_clients
    mqtt_client = await _started_client(hass, api)

    mqtt_client._on_connect(clients[0], None, None, _rc(failure=True), None)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert start.call_count == 2
    clients[0].subscribe.assert_not_called()
    await mqtt_client.async_stop()


async def test_initial_failure_retries(hass: HomeAssistant, api, paho_clients) -> None:
    _, start, _ = paho_clients
    start.side_effect = [OSError("dns"), None]
    mqtt_client = await _started_client(hass, api)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert start.call_count == 2
    assert mqtt_client._client is not None
    await mqtt_client.async_stop()


async def test_no_reconnect_after_stop(hass: HomeAssistant, api, paho_clients) -> None:
    clients, start, _ = paho_clients
    mqtt_client = await _started_client(hass, api)
    await mqtt_client.async_stop()

    mqtt_client._on_disconnect(clients[0], None, None, _rc(), None)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert start.call_count == 1


async def test_subscribe_and_messages(hass: HomeAssistant, api, paho_clients) -> None:
    clients, _, _ = paho_clients
    callback = Mock()
    mqtt_client = await _started_client(hass, api, callback)

    mqtt_client._on_connect(clients[0], None, None, _rc(), None)
    topics = [c.args[0] for c in clients[0].subscribe.call_args_list]
    assert "/downlink/vehicle/dev1/realtimeDate/state" in topics
    assert len(topics) == 3

    msg = MagicMock(topic="/downlink/vehicle/dev1/realtimeDate/state", payload=b'{"state": "isRunning"}')
    mqtt_client._on_message(clients[0], None, msg)
    mqtt_client._on_message(clients[0], None, MagicMock(topic="t", payload=b"not json"))
    await hass.async_block_till_done()

    callback.assert_called_once_with(msg.topic, {"state": "isRunning"})
    await mqtt_client.async_stop()


async def test_create_real_paho_client(hass: HomeAssistant, api) -> None:
    """Build a real paho client (no connection) to check the paho 2.x API usage."""
    entry = MockConfigEntry(domain=DOMAIN)
    mqtt_client = NavimowMqttClient(hass, entry, api, ["dev1"], Mock())
    client, hostname = await hass.async_add_executor_job(
        mqtt_client._create_client, {**MQTT_INFO, "mqttUrl": "/ws"}, "token"
    )
    assert hostname == "mqtt.example.com"
    assert client.on_disconnect == mqtt_client._on_disconnect


async def test_create_client_rejects_incomplete_info(hass: HomeAssistant, api) -> None:
    from custom_components.navimow.api import NavimowError

    mqtt_client = NavimowMqttClient(hass, MockConfigEntry(domain=DOMAIN), api, [], Mock())
    with pytest.raises(NavimowError):
        mqtt_client._create_client({"mqttHost": "wss://h"}, "token")
