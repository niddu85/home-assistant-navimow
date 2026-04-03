"""API client for Segway Navimow."""
import logging
import uuid
from aiohttp import ClientSession

_LOGGER = logging.getLogger(__name__)

BASE_URL = "https://navimow-fra.ninebot.com/openapi/smarthome"

class NavimowApiClient:
    """Handles REST communication with Navimow API."""

    def __init__(self, token: str, session: ClientSession):
        self._token = token
        self._session = session

    def _get_headers(self):
        """Get request headers with authorization."""
        return {
            "Authorization": f"Bearer {self._token}",
            "requestId": str(uuid.uuid4())[:32],
            "Content-Type": "application/json"
        }

    async def async_get_devices(self) -> list:
        """Fetch list of devices."""
        url = f"{BASE_URL}/authList"
        try:
            async with self._session.get(url, headers=self._get_headers()) as response:
                res = await response.json()
                if res.get("code") == 1:
                    return res.get("data", {}).get("payload", {}).get("devices", [])
                return []
        except Exception as e:
            _LOGGER.error("Error fetching devices: %s", e)
            return []

    async def async_get_all_vehicles_status(self, device_ids: list) -> dict:
        """Fetch vehicle status for multiple devices."""
        if not device_ids:
            return {}

        url = f"{BASE_URL}/getVehicleStatus"
        payload = {"devices": [{"id": d_id} for d_id in device_ids]}
        
        try:
            async with self._session.post(url, headers=self._get_headers(), json=payload) as response:
                if response.status == 401:
                    return {"error": "TOKEN_EXPIRED"}
                
                res = await response.json()
                code = res.get("code")
                desc = res.get("desc", "")

                if code == 1:
                    devices = res.get("data", {}).get("payload", {}).get("devices", [])
                    return {d["id"]: d for d in devices}
                
                if code == 4005 or desc == "TOKEN_EXPIRED" or desc == "CODE_OAUTH_INFO_ILLEGAL":
                    _LOGGER.info("Token expired (code %s), requesting refresh", code)
                    return {"error": "TOKEN_EXPIRED"}
                
                _LOGGER.error("Unknown Navimow API error: %s", res)
                return None
        except Exception as e:
            _LOGGER.error("Exception during getVehicleStatus: %s", e)
            return None

    async def async_refresh_token(self, refresh_token: str) -> dict:
        """Request new access token using refresh token."""
        url = "https://navimow-fra.ninebot.com/openapi/oauth/getAccessToken"
        import os
        client_secret = os.getenv("NAVIMOW_CLIENT_SECRET", "")
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": "homeassistant",
            "client_secret": client_secret
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        try:
            async with self._session.post(url, data=payload, headers=headers) as response:
                return await response.json()
        except Exception as e:
            _LOGGER.error("Error during token refresh: %s", e)
            return {}

    async def async_send_command(self, device_id: str, command: str, params: dict = None) -> bool:
        """Send command to device."""
        url = f"{BASE_URL}/sendCommands"
        payload = {"commands": [{"devices": [{"id": device_id}], "execution": {"command": command, "params": params}}]}
        async with self._session.post(url, headers=self._get_headers(), json=payload) as response:
            res = await response.json()
            return res.get("code") == 1

    async def async_get_mqtt_info(self) -> dict:
        """Fetch MQTT broker credentials."""
        url = f"{BASE_URL.replace('/smarthome', '')}/mqtt/userInfo/get/v2"
        try:
            async with self._session.get(url, headers=self._get_headers()) as response:
                res = await response.json()
                if res.get("code") == 1:
                    return res.get("data", {})
                return {}
        except Exception as e:
            _LOGGER.error("Errore recupero info MQTT: %s", e)
            return {}