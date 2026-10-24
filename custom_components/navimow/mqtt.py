"""MQTT over WebSocket client for real-time Navimow updates."""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

import paho.mqtt.client as mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from paho.mqtt.enums import CallbackAPIVersion

from .api import NavimowApiClient, NavimowError

_LOGGER = logging.getLogger(__name__)

MQTT_PORT = 443
MQTT_KEEPALIVE = 60
# The MQTT credentials endpoint rejects calls less than a minute apart
RECONNECT_MIN_DELAY = 60
RECONNECT_MAX_DELAY = 300
TOPIC_CHANNELS = ("state", "event", "attributes")


class NavimowMqttClient:
    """Keeps an MQTT connection open for real-time device updates.

    MQTT credentials are bound to the OAuth token, so paho's automatic
    reconnect (which reuses the original credentials) is disabled: after every
    disconnect the old client is discarded and a new one is created with fresh
    credentials, with exponential backoff between attempts.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        api: NavimowApiClient,
        device_ids: list[str],
        message_callback: Callable[[str, dict[str, Any]], None],
    ) -> None:
        self._hass = hass
        self._entry = entry
        self._api = api
        self._device_ids = device_ids
        self._message_callback = message_callback
        self._client: mqtt.Client | None = None
        self._reconnect_task: asyncio.Task | None = None
        self._failures = 0
        self._stopping = False

    async def async_start(self) -> None:
        """Connect to the broker, retrying in the background on failure."""
        try:
            await self._async_connect()
        except Exception as err:  # noqa: BLE001 - paho raises many error types
            _LOGGER.warning("Unable to connect to Navimow MQTT: %s", err)
            self._failures += 1
            self._async_schedule_reconnect(None)

    async def async_stop(self) -> None:
        """Disconnect and stop reconnecting."""
        self._stopping = True
        if self._reconnect_task:
            self._reconnect_task.cancel()
        client, self._client = self._client, None
        if client:
            await self._hass.async_add_executor_job(_close_client, client)

    async def _async_connect(self) -> None:
        mqtt_info = await self._api.async_get_mqtt_info()
        token = await self._api.async_get_access_token()
        client, hostname = await self._hass.async_add_executor_job(
            self._create_client, mqtt_info, token
        )
        if self._stopping:
            return
        # Set before starting the network loop so callbacks recognize the client
        self._client = client
        try:
            await self._hass.async_add_executor_job(_start_client, client, hostname)
        except Exception:
            self._client = None
            raise
        if self._stopping:
            await self._hass.async_add_executor_job(_close_client, client)

    def _create_client(
        self, mqtt_info: dict[str, Any], token: str
    ) -> tuple[mqtt.Client, str]:
        """Build an MQTT client (blocking: loads TLS certificates)."""
        mqtt_host = mqtt_info.get("mqttHost", "")
        hostname = urlparse(mqtt_host).hostname or mqtt_host
        username = mqtt_info.get("userName")
        password = mqtt_info.get("pwdInfo")
        if not hostname or not username or not password:
            raise NavimowError("Incomplete MQTT connection info")

        client = mqtt.Client(
            CallbackAPIVersion.VERSION2,
            client_id=f"web_{username}_{uuid.uuid4().hex[:10]}",
            transport="websockets",
            reconnect_on_failure=False,
        )
        client.username_pw_set(username, password)
        client.ws_set_options(
            path=mqtt_info.get("mqttUrl", "/mqtt"),
            headers={"Authorization": f"Bearer {token}"},
        )
        client.tls_set()
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message
        return client, hostname

    # Paho callbacks: these run in the paho network thread

    def _on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        if reason_code.is_failure:
            _LOGGER.warning("Navimow MQTT connection refused: %s", reason_code)
            self._hass.loop.call_soon_threadsafe(self._async_schedule_reconnect, client)
            return
        _LOGGER.info("Navimow MQTT connected")
        self._failures = 0
        for device_id in self._device_ids:
            for channel in TOPIC_CHANNELS:
                client.subscribe(f"/downlink/vehicle/{device_id}/realtimeDate/{channel}")

    def _on_disconnect(
        self, client, userdata, disconnect_flags, reason_code, properties
    ) -> None:
        _LOGGER.info("Navimow MQTT disconnected: %s", reason_code)
        self._hass.loop.call_soon_threadsafe(self._async_schedule_reconnect, client)

    def _on_message(self, client, userdata, msg: mqtt.MQTTMessage) -> None:
        try:
            payload = json.loads(msg.payload)
        except ValueError:
            _LOGGER.debug("Ignoring non-JSON MQTT payload on %s", msg.topic)
            return
        if isinstance(payload, dict):
            self._hass.loop.call_soon_threadsafe(
                self._message_callback, msg.topic, payload
            )

    @callback
    def _async_schedule_reconnect(self, client: mqtt.Client | None) -> None:
        """Replace the given client with a new one, unless already done."""
        if self._stopping or client is not self._client:
            # Stale callback from a client that has already been replaced
            return
        self._client = None
        if self._reconnect_task and not self._reconnect_task.done():
            return
        self._reconnect_task = self._entry.async_create_background_task(
            self._hass, self._async_reconnect(client), "navimow_mqtt_reconnect"
        )

    async def _async_reconnect(self, old_client: mqtt.Client | None) -> None:
        if old_client:
            await self._hass.async_add_executor_job(_close_client, old_client)
        while not self._stopping:
            delay = min(RECONNECT_MAX_DELAY, RECONNECT_MIN_DELAY * 2**self._failures)
            _LOGGER.debug("Reconnecting to Navimow MQTT in %ss", delay)
            await asyncio.sleep(delay)
            try:
                await self._async_connect()
            except Exception as err:  # noqa: BLE001 - paho raises many error types
                self._failures += 1
                _LOGGER.warning("Navimow MQTT reconnection failed: %s", err)
                continue
            # A disconnect while this task was still running clears the client
            # without spawning a new task: in that case keep trying
            if self._client is not None:
                return


def _start_client(client: mqtt.Client, hostname: str) -> None:
    """Connect and start the network loop (blocking)."""
    client.connect(hostname, MQTT_PORT, MQTT_KEEPALIVE)
    client.loop_start()


def _close_client(client: mqtt.Client) -> None:
    """Disconnect and stop the network loop (blocking)."""
    client.disconnect()
    client.loop_stop()
