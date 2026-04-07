"""DataUpdateCoordinator for Segway Navimow integration."""
from datetime import timedelta
import logging
import json
import time
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
        self._mqtt_client = None
        self._pending_mqtt_token = None
        self._mqtt_info = None
        self._token_expires_at = 0  # Timestamp when access token expires
        
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=30),
        )

    async def _async_ensure_valid_token(self) -> None:
        """Refresh OAuth token only if expired or expiring soon.
        
        Checks token expiration timestamp before refreshing to avoid unnecessary
        API calls. Maintains 10-second buffer before actual expiration.
        """
        # Check if token is still valid (with 10s buffer)
        now = time.time()
        if now < self._token_expires_at - 10:
            return  # Token still valid, no need to refresh
        
        refresh_token = self.entry.data.get("refresh_token")
        if not refresh_token:
            return
        
        try:
            token_response = await self.api.async_refresh_token(refresh_token)
            if token_response and "access_token" in token_response:
                new_access = token_response["access_token"]
                new_refresh = token_response.get("refresh_token", refresh_token)
                
                # Calculate token expiration time
                expires_in = token_response.get("expires_in", 3600)  # Default 1 hour if not provided
                self._token_expires_at = now + expires_in
                
                self.api._token = new_access
                
                self.hass.config_entries.async_update_entry(
                    self.entry,
                    data={
                        **self.entry.data,
                        "access_token": new_access,
                        "refresh_token": new_refresh,
                    },
                )
                _LOGGER.debug("OAuth token refreshed (expires in %ds)", expires_in)
        except Exception as err:
            _LOGGER.warning("Failed to refresh OAuth token: %s", err)

    async def _async_refresh_mqtt_credentials_on_disconnect(self) -> None:
        """Refresh MQTT credentials after disconnection.
        
        When MQTT disconnects, it's often because the OAuth token expired.
        We need to refresh the token first, then fetch fresh MQTT credentials.
        """
        try:
            # First ensure we have a fresh OAuth token
            await self._async_ensure_valid_token()
            
            # Then fetch fresh MQTT credentials with the new token
            new_mqtt_info = await self.api.async_get_mqtt_info()
            if new_mqtt_info:
                new_username = new_mqtt_info.get("userName")
                new_password = new_mqtt_info.get("pwdInfo")
                
                if new_username and new_password and self._mqtt_client:
                    _LOGGER.info("MQTT credentials refreshed after disconnect, updating client credentials")
                    
                    # Update MQTT client with new credentials
                    def _update_credentials():
                        try:
                            # Stop the loop and disconnect
                            self._mqtt_client.loop_stop()
                            self._mqtt_client.disconnect()
                            
                            # Update credentials
                            self._mqtt_client.username_pw_set(new_username, new_password)
                            
                            # Update auth headers with fresh token
                            token = self.entry.data.get("access_token")
                            auth_headers = {"Authorization": f"Bearer {token}"}
                            ws_path = new_mqtt_info.get("mqttUrl", "/mqtt")
                            self._mqtt_client.ws_set_options(path=ws_path, headers=auth_headers)
                            
                            # Reconnect
                            mqtt_host = new_mqtt_info.get("mqttHost", "")
                            parsed = urlparse(mqtt_host)
                            hostname = parsed.hostname or mqtt_host
                            port = 443
                            
                            _LOGGER.info("Reconnecting MQTT with new credentials")
                            self._mqtt_client.connect(hostname, port, 60)
                            self._mqtt_client.loop_start()
                        except Exception as err:
                            _LOGGER.error("Failed to update MQTT client credentials: %s", err)
                    
                    await self.hass.async_add_executor_job(_update_credentials)
                    # Store updated mqtt_info
                    self._mqtt_info = new_mqtt_info
        except Exception as err:
            _LOGGER.warning("Failed to refresh MQTT credentials on disconnect: %s", err)

    async def _async_update_data(self):
        """Fetch vehicle data and handle token refresh."""
        # Proactively refresh token before each update to keep API and MQTT credentials in sync.
        # If only refreshed during HTTP fallback, MQTT would have stale token for extended periods,
        # causing commands to fail with CODE_OAUTH_INFO_ILLEGAL when token eventually expires.
        try:
            await self._async_ensure_valid_token()
        except Exception as err:
            _LOGGER.warning("Token refresh failed during update: %s", err)
        
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
                # Update MQTT WebSocket auth headers to avoid reconnection failures (CODE_OAUTH_INFO_ILLEGAL)
                # Store new token for MQTT credential refresh on disconnect
                self._pending_mqtt_token = new_access

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
        # Store mqtt_info for later credential refresh
        self._mqtt_info = mqtt_info

        # Don't block the setup by waiting for MQTT connection - run it in background
        self.hass.create_task(self._async_connect_mqtt(mqtt_info))

    async def _async_connect_mqtt(self, mqtt_info):
        """Connect to MQTT without blocking the main thread."""
        try:
            await self.hass.async_add_executor_job(self._connect_mqtt, mqtt_info)
        except Exception as e:
            _LOGGER.error("Error setting up MQTT: %s", e)

    def _connect_mqtt(self, mqtt_info):
        """Connect to MQTT broker (blocking operation, run in executor)."""
        try:
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
                    self.hass.add_job(self._handle_mqtt_payload, msg.topic, payload)
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
                # After MQTT disconnection, refresh credentials from server.
                # MQTT credentials (userName/pwdInfo) are bound to the OAuth token.
                # If token expired, causing the disconnection, we need to fetch fresh credentials.
                self.hass.create_task(self._async_refresh_mqtt_credentials_on_disconnect())

            client.on_message = on_message
            client.on_connect = on_connect
            client.on_disconnect = on_disconnect
            
            port = 443
            
            _LOGGER.debug("Connecting to MQTT %s:%d with path %s", hostname, port, ws_path)
            client.connect(hostname, port, 60)
            client.loop_start()
            
            self._mqtt_client = client
            _LOGGER.info("MQTT client initialized and connecting")
        except Exception as e:
            _LOGGER.error("Error connecting to MQTT: %s", e)
            raise

    async def _handle_mqtt_payload(self, topic, payload):
        """Update data with MQTT updates in the main loop."""
        _LOGGER.debug("MQTT payload received: topic=%s payload=%s", topic, payload)

        # Extract channel from topic: /downlink/vehicle/{id}/realtimeDate/{channel}
        parts = topic.split("/")
        channel = parts[-1] if parts else ""

        device_id = payload.get("device_id")
        if not device_id:
            # Fallback: extract device_id from topic position
            try:
                device_id = parts[3]
            except IndexError:
                pass
        if not device_id:
            _LOGGER.debug("Payload has no device_id and topic has no device segment")
            return

        if not self.data or device_id not in self.data:
            _LOGGER.debug("Device '%s' not found", device_id)
            return

        if channel == "state":
            old_state = self.data[device_id].get("vehicleState", "unknown")
            if "state" in payload:
                self.data[device_id]["vehicleState"] = payload["state"]
            for key in ["battery", "timestamp", "position", "signal_strength"]:
                if key in payload:
                    self.data[device_id][key] = payload[key]
            new_state = self.data[device_id].get("vehicleState", "unknown")
            _LOGGER.debug("Device '%s': vehicleState %s -> %s", device_id, old_state, new_state)

        elif channel == "event":
            event_type = payload.get("event", "")
            level = payload.get("level", "")
            _LOGGER.debug("Device '%s' event: type=%s level=%s", device_id, event_type, level)
            # Propagate error events immediately so the error sensor updates in real time
            if level == "error" or event_type in {"Error", "error", "isLifted", "stuck"}:
                self.data[device_id]["error_code"] = event_type or level
                self.data[device_id]["vehicleState"] = "Error"
            elif level == "info" and event_type in {"errorRecovery", "clear"}:
                self.data[device_id]["error_code"] = "none"

        elif channel == "attributes":
            attributes = payload.get("attributes", payload)
            if isinstance(attributes, dict):
                _LOGGER.debug("Device '%s' attributes: %s", device_id, list(attributes.keys()))
                self.data[device_id].update(attributes)

        await self.async_set_updated_data(self.data)