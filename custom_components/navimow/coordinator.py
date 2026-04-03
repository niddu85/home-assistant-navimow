"""DataUpdateCoordinator for Segway Navimow integration."""
from datetime import timedelta
import logging
import json
import uuid
from urllib.parse import urlparse
import paho.mqtt.client as mqtt

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

class NavimowDataUpdateCoordinator(DataUpdateCoordinator):
    """Coordinator for centralized data fetching and token refresh."""

    def __init__(self, hass, api, entry, devices):
        """Initialize coordinator."""
        self.api = api
        self.entry = entry
        self.devices = devices
        
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=30),
        )

    async def _async_update_data(self):
        """Fetch vehicle data and handle token refresh."""
        device_ids = [d["id"] for d in self.devices]
        
        if not device_ids:
            _LOGGER.debug("No devices found for this account")
            return {}

        data = await self.api.async_get_all_vehicles_status(device_ids)

        if isinstance(data, dict) and data.get("error") == "TOKEN_EXPIRED":
            _LOGGER.info("Access token expired, attempting refresh...")
            
            refresh_token = self.entry.data.get("refresh_token")
            if not refresh_token:
                raise UpdateFailed("Refresh token missing, reconnect the Navimow account")

            token_response = await self.api.async_refresh_token(refresh_token)
            
            if token_response and "access_token" in token_response:
                new_access = token_response["access_token"]
                new_refresh = token_response.get("refresh_token", refresh_token)
                
                _LOGGER.info("New access token obtained successfully")

                self.api._token = new_access
                
                self.hass.config_entries.async_update_entry(
                    self.entry,
                    data={
                        **self.entry.data,
                        "access_token": new_access,
                        "refresh_token": new_refresh,
                    },
                )

                data = await self.api.async_get_all_vehicles_status(device_ids)
            else:
                _LOGGER.error("Refresh token is invalid or server rejected the request")
                raise UpdateFailed("Session expired. Please remove and re-add the integration.")

        if data is None:
            raise UpdateFailed("Communication error with Navimow servers")

        
        return data

    async def async_setup_mqtt(self, mqtt_info):
        """Initialize MQTT connection without blocking the loop."""
        if not mqtt_info:
            return

        _LOGGER.debug("MQTT info: %s", mqtt_info)

        def _connect_mqtt():
            mqtt_host = mqtt_info.get("mqttHost", "")
            parsed = urlparse(mqtt_host)
            hostname = parsed.hostname or mqtt_host
            
            username = mqtt_info.get("userName", "unknown")
            rand_suffix = uuid.uuid4().hex[:10]
            client_id = f"web_{username}_{rand_suffix}"
            
            client = mqtt.Client(client_id=client_id, transport="websockets")
            
            password = mqtt_info.get("pwdInfo")
            client.username_pw_set(username, password)
            
            ws_path = mqtt_info.get("mqttUrl", "/mqtt")
            
            token = self.entry.data.get("access_token")
            auth_headers = {"Authorization": f"Bearer {token}"}
            client.ws_set_options(path=ws_path, headers=auth_headers)
            
            client.tls_set()
            client.tls_insecure_set(False)
            
            def on_message(client, userdata, msg):
                _LOGGER.debug("MQTT message received: topic=%s", msg.topic)
                try:
                    payload = json.loads(msg.payload.decode())
                    _LOGGER.debug("MQTT payload (JSON): %s", payload)
                    self.hass.add_job(self._handle_mqtt_payload, payload)
                except json.JSONDecodeError as e:
                    _LOGGER.warning("Invalid JSON payload: %s (raw: %s)", e, msg.payload)
                except Exception as e:
                    _LOGGER.error("Error parsing MQTT: %s", e)

            def on_connect(client, userdata, flags, rc):
                if rc == 0:
                    _LOGGER.info("MQTT connected successfully")
                    for device in self.devices:
                        device_id = device.get("id")
                        if device_id:
                            topics = [
                                f"/downlink/vehicle/{device_id}/realtimeDate/state",
                                f"/downlink/vehicle/{device_id}/realtimeDate/event",
                                f"/downlink/vehicle/{device_id}/realtimeDate/attributes",
                            ]
                            for topic in topics:
                                client.subscribe(topic)
                                _LOGGER.debug("Subscribed to topic: %s", topic)
                else:
                    _LOGGER.error("MQTT connection error (rc=%d)", rc)

            def on_disconnect(client, userdata, rc):
                _LOGGER.info("MQTT disconnected: rc=%d", rc)

            client.on_message = on_message
            client.on_connect = on_connect
            client.on_disconnect = on_disconnect
            
            port = 443
            
            _LOGGER.debug("Connecting to MQTT %s:%d with path %s", hostname, port, ws_path)
            client.connect(hostname, port, 60)
            client.loop_start()
            return client

        try:
            await self.hass.async_add_executor_job(_connect_mqtt)
        except Exception as e:
            _LOGGER.error("Error setting up MQTT: %s", e)

    async def _handle_mqtt_payload(self, payload):
        """Update data with MQTT updates in the main loop."""
        _LOGGER.debug("MQTT payload received: %s", payload)
        
        device_id = payload.get("device_id")
        if not device_id:
            _LOGGER.debug("Payload has no device_id")
            return
        
        if not self.data or device_id not in self.data:
            _LOGGER.debug("Device '%s' not found", device_id)
            return
        
        mqtt_to_ha_mapping = {
            'state': 'vehicleState',
        }
        
        old_state = self.data[device_id].get("vehicleState", "unknown")
        
        for mqtt_field, ha_field in mqtt_to_ha_mapping.items():
            if mqtt_field in payload:
                self.data[device_id][ha_field] = payload[mqtt_field]
                _LOGGER.debug("Mapped %s=%s -> %s", mqtt_field, payload[mqtt_field], ha_field)
        
        for key in ['battery', 'timestamp', 'position', 'signal_strength']:
            if key in payload:
                self.data[device_id][key] = payload[key]
        
        new_state = self.data[device_id].get("vehicleState", "unknown")
        
        _LOGGER.debug("Device '%s': vehicleState %s -> %s", device_id, old_state, new_state)
        
        await self.async_set_updated_data(self.data)