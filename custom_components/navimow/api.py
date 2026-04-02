"""API client per Segway Navimow."""
import logging
import uuid
from aiohttp import ClientSession

_LOGGER = logging.getLogger(__name__)

BASE_URL = "https://navimow-fra.ninebot.com/openapi/smarthome"

class NavimowApiClient:
    """Gestisce la comunicazione con le API Navimow."""

    def __init__(self, token: str, session: ClientSession):
        """Inizializza il client API con il token di accesso."""
        self._token = token
        self._session = session

    async def async_get_devices(self) -> list:
        """Recupera la lista dei dispositivi associati all'account."""
        url = f"{BASE_URL}/authList"
        
        # Generiamo l'UUID univoco ad ogni richiesta
        headers = {
            "authorization": f"Bearer {self._token}",
            "requestid": str(uuid.uuid4())
        }

        try:
            async with self._session.get(url, headers=headers) as response:
                response.raise_for_status()
                data = await response.json()

                if data.get("code") == 1:
                    devices = data.get("data", {}).get("payload", {}).get("devices", [])
                    _LOGGER.debug("Trovati %s dispositivi Navimow", len(devices))
                    return devices
                else:
                    _LOGGER.error("Errore API Navimow: %s", data.get("desc"))
                    return []
        except Exception as e:
            _LOGGER.error("Errore di connessione per recuperare i dispositivi: %s", e)
            return []