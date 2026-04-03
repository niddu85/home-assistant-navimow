"""API client per Segway Navimow."""
import logging
import uuid
from aiohttp import ClientSession

_LOGGER = logging.getLogger(__name__)

BASE_URL = "https://navimow-fra.ninebot.com/openapi/smarthome"

class NavimowApiClient:
    """Gestisce la comunicazione REST con Navimow."""

    def __init__(self, token: str, session: ClientSession):
        self._token = token
        self._session = session

    def _get_headers(self):
        """Header richiesti."""
        return {
            "Authorization": f"Bearer {self._token}",
            "requestId": str(uuid.uuid4())[:32], # Limita la lunghezza per sicurezza
            "Content-Type": "application/json"
        }

    async def async_get_devices(self) -> list:
        """Recupera l'elenco dispositivi."""
        url = f"{BASE_URL}/authList"
        try:
            async with self._session.get(url, headers=self._get_headers()) as response:
                res = await response.json()
                if res.get("code") == 1:
                    return res.get("data", {}).get("payload", {}).get("devices", [])
                return []
        except Exception as e:
            _LOGGER.error("Errore recupero dispositivi: %s", e)
            return []

    async def async_get_all_vehicles_status(self, device_ids: list) -> dict:
        """Recupera lo stato bulk."""
        if not device_ids:
            return {}

        url = f"{BASE_URL}/getVehicleStatus"
        payload = {"devices": [{"id": d_id} for d_id in device_ids]}
        
        try:
            async with self._session.post(url, headers=self._get_headers(), json=payload) as response:
                # Se riceve 401, il token è sicuramente scaduto
                if response.status == 401:
                    return {"error": "TOKEN_EXPIRED"}
                
                res = await response.json()
                code = res.get("code")
                desc = res.get("desc", "")

                # SUCCESSO
                if code == 1:
                    devices = res.get("data", {}).get("payload", {}).get("devices", [])
                    return {d["id"]: d for d in devices}
                
                # TRAPPOLA PER TOKEN SCADUTO (4005 o stringa)
                if code == 4005 or desc == "TOKEN_EXPIRED" or desc == "CODE_OAUTH_INFO_ILLEGAL":
                    _LOGGER.info("Rilevato token scaduto (codice %s), richiedo refresh", code)
                    return {"error": "TOKEN_EXPIRED"}
                
                _LOGGER.error("Errore API Navimow sconosciuto: %s", res)
                return None
        except Exception as e:
            _LOGGER.error("Eccezione durante getVehicleStatus: %s", e)
            return None

    async def async_refresh_token(self, refresh_token: str) -> dict:
        """Richiede un nuovo access_token."""
        url = "https://navimow-fra.ninebot.com/openapi/oauth/getAccessToken"
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": "homeassistant",
            "client_secret": "57056e15-722e-42be-bbaa-b0cbfb208a52"
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        try:
            async with self._session.post(url, data=payload, headers=headers) as response:
                return await response.json()
        except Exception as e:
            _LOGGER.error("Errore durante il refresh del token: %s", e)
            return {}

    async def async_send_command(self, device_id: str, command: str, params: dict = None) -> bool:
        """Invia un comando."""
        url = f"{BASE_URL}/sendCommands"
        payload = {"commands": [{"devices": [{"id": device_id}], "execution": {"command": command, "params": params}}]}
        async with self._session.post(url, headers=self._get_headers(), json=payload) as response:
            res = await response.json()
            return res.get("code") == 1

    async def async_get_mqtt_info(self) -> dict:
        """Recupera le credenziali MQTT."""
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