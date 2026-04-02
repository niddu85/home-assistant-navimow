"""Coordinator per Navimow."""
from datetime import timedelta
import logging
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

class NavimowDataUpdateCoordinator(DataUpdateCoordinator):
    """Gestore aggiornamento dati centralizzato."""

    def __init__(self, hass, api, entry, devices):
        """Inizializzazione con dispositivi già caricati."""
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
        """Recupera i dati e gestisce il refresh token."""
        device_ids = [d["id"] for d in self.devices]
        
        data = await self.api.async_get_all_vehicles_status(device_ids)

        # Se il token è scaduto, proviamo il refresh
        if isinstance(data, dict) and data.get("error") == "TOKEN_EXPIRED":
            _LOGGER.info("Token Navimow scaduto, tentativo di refresh...")
            refresh_token = self.entry.data.get("refresh_token")
            new_tokens = await self.api.async_refresh_token(refresh_token)
            
            if "access_token" in new_tokens:
                new_access_token = new_tokens["access_token"]
                self.api._token = new_access_token
                # Aggiorna i dati salvati in HA
                self.hass.config_entries.async_update_entry(
                    self.entry, 
                    data={**self.entry.data, "access_token": new_access_token}
                )
                # Riprova il fetch con il nuovo token
                data = await self.api.async_get_all_vehicles_status(device_ids)
            else:
                _LOGGER.error("Refresh token fallito per Navimow")
                raise UpdateFailed("Autenticazione scaduta, ricollegare l'account.")

        # Se data è None, c'è stato un errore di comunicazione
        if data is None:
            raise UpdateFailed("Errore durante la comunicazione con i server Navimow")
            
        return data