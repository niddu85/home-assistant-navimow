"""DataUpdateCoordinator per l'integrazione Segway Navimow."""
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

    async def async_setup_mqtt(self, mqtt_info):
        """Inizializza la connessione MQTT senza bloccare il loop."""
        if not mqtt_info:
            return

        _LOGGER.warning("Info MQTT ricevute dal server: %s", mqtt_info)

        def _connect_mqtt():
            # Estrai hostname da URL completo (es: wss://mqtt-fra.navimow.com)
            mqtt_host = mqtt_info.get("mqttHost", "")
            parsed = urlparse(mqtt_host)
            hostname = parsed.hostname or mqtt_host
            
            # Genera client ID come fa l'SDK ufficiale
            username = mqtt_info.get("userName", "unknown")
            rand_suffix = uuid.uuid4().hex[:10]
            client_id = f"web_{username}_{rand_suffix}"
            
            # Transport WebSocket per porta 443
            client = mqtt.Client(client_id=client_id, transport="websockets")
            
            # Credenziali usuali
            password = mqtt_info.get("pwdInfo")
            client.username_pw_set(username, password)
            
            # WebSocket path
            ws_path = mqtt_info.get("mqttUrl", "/mqtt")
            
            # ESSENZIALE: Header di autorizzazione per il handshake WebSocket
            token = self.entry.data.get("access_token")
            auth_headers = {"Authorization": f"Bearer {token}"}
            client.ws_set_options(path=ws_path, headers=auth_headers)
            
            # TLS per porta 443
            client.tls_set()
            client.tls_insecure_set(False)  # Verifica certificati
            
            def on_message(client, userdata, msg):
                try:
                    payload = json.loads(msg.payload.decode())
                    _LOGGER.debug("MQTT Navimow Ricevuto: %s", payload)
                    self.hass.add_job(self._handle_mqtt_payload, payload)
                except Exception as e:
                    _LOGGER.error("Errore parsing MQTT: %s", e)

            def on_connect(client, userdata, flags, rc):
                if rc == 0:
                    _LOGGER.info("MQTT connesso con successo")
                    # Sottoscrivi ai topic
                    for topic in mqtt_info.get("subTopics", []):
                        client.subscribe(topic)
                        _LOGGER.debug(f"Sottoscritto a topic: {topic}")
                else:
                    _LOGGER.error("Errore connessione MQTT (rc=%d): %s", rc)

            def on_disconnect(client, userdata, rc):
                _LOGGER.warning("MQTT disconnesso: rc=%d", rc)

            client.on_message = on_message
            client.on_connect = on_connect
            client.on_disconnect = on_disconnect
            
            port = 443
            
            _LOGGER.info(f"Connessione MQTT a {hostname}:{port} con path {ws_path} e headers: {auth_headers}")
            client.connect(hostname, port, 60)
            client.loop_start()
            return client

        try:
            await self.hass.async_add_executor_job(_connect_mqtt)
        except Exception as e:
            _LOGGER.error("Errore setup MQTT: %s", e)

    def _handle_mqtt_payload(self, payload):
        """Aggiorna i dati nel loop principale."""
        device_id = payload.get("id")
        if self.data and device_id in self.data:
            # Aggiorniamo i dati esistenti con i nuovi arrivati via MQTT
            self.data[device_id].update(payload)
            # Notifichiamo a tutte le entità di rinfrescarsi
            self.async_set_updated_data(self.data)