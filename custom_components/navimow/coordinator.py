"""DataUpdateCoordinator per l'integrazione Segway Navimow."""
from datetime import timedelta
import logging

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

class NavimowDataUpdateCoordinator(DataUpdateCoordinator):
    """Classe per gestire il recupero dati centralizzato e il refresh dei token."""

    def __init__(self, hass, api, entry, devices):
        """Inizializza il coordinator."""
        self.api = api
        self.entry = entry
        self.devices = devices # Lista dei dispositivi recuperata al setup
        
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            # Intervallo di aggiornamento consigliato: 30 secondi
            update_interval=timedelta(seconds=30),
        )

    async def _async_update_data(self):
        """Recupera i dati dai server Navimow e gestisce la scadenza dei token."""
        device_ids = [d["id"] for d in self.devices]
        
        if not device_ids:
            _LOGGER.debug("Nessun dispositivo trovato per questo account")
            return {}

        # 1. Tenta il recupero dello stato (chiamata bulk)
        data = await self.api.async_get_all_vehicles_status(device_ids)

        # 2. Gestione Token Scaduto (Fase 5)
        if isinstance(data, dict) and data.get("error") == "TOKEN_EXPIRED":
            _LOGGER.info("Access Token Navimow scaduto, avvio procedura di refresh...")
            
            refresh_token = self.entry.data.get("refresh_token")
            if not refresh_token:
                raise UpdateFailed("Refresh token mancante, ricollega l'account Navimow")

            # Richiediamo i nuovi token ai server Segway
            token_response = await self.api.async_refresh_token(refresh_token)
            
            if token_response and "access_token" in token_response:
                new_access = token_response["access_token"]
                new_refresh = token_response.get("refresh_token", refresh_token)
                
                _LOGGER.info("Nuovo Access Token ottenuto correttamente")

                # Aggiorniamo il client API in memoria
                self.api._token = new_access
                
                # SALVATAGGIO PERSISTENTE: Aggiorna l'entry in Home Assistant
                # Questo scrive i nuovi token nel file .storage così sopravvivono al riavvio
                self.hass.config_entries.async_update_entry(
                    self.entry,
                    data={
                        **self.entry.data,
                        "access_token": new_access,
                        "refresh_token": new_refresh,
                    },
                )

                # 3. Riprova la chiamata originale con il nuovo token
                data = await self.api.async_get_all_vehicles_status(device_ids)
            else:
                _LOGGER.error("Il Refresh Token non è più valido o il server ha rifiutato la richiesta")
                raise UpdateFailed("Sessione scaduta. Per favore, rimuovi e aggiungi di nuovo l'integrazione.")

        # 4. Controllo errori generici
        if data is None:
            raise UpdateFailed("Errore di comunicazione con i server Navimow")

        
        return data