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

        _LOGGER.debug("Info MQTT ricevute dal server: %s", mqtt_info)

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
                _LOGGER.debug(f"MQTT Messaggio ricevuto: topic={msg.topic}, payload_raw={msg.payload}")
                try:
                    payload = json.loads(msg.payload.decode())
                    _LOGGER.warning("MQTT Navimow Ricevuto (JSON): %s", payload)
                    # Usa add_job per eseguire la coroutine nel loop di Home Assistant
                    self.hass.add_job(self._handle_mqtt_payload, payload)
                except json.JSONDecodeError as e:
                    _LOGGER.warning("Payload non è JSON valido: %s (raw: %s)", e, msg.payload)
                except Exception as e:
                    _LOGGER.error("Errore parsing MQTT: %s", e)

            def on_connect(client, userdata, flags, rc):
                if rc == 0:
                    _LOGGER.info("MQTT connesso con successo")
                    # Sottoscrivi ai topic veri MQTT usando i device_id
                    # I subTopics sono solo metadati, i veri topic sono: /downlink/vehicle/{device_id}/realtimeDate/*
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
                                _LOGGER.warning(f"Sottoscritto a topic: {topic}")
                else:
                    _LOGGER.error("Errore connessione MQTT (rc=%d)", rc)

            def on_disconnect(client, userdata, rc):
                _LOGGER.warning("MQTT disconnesso: rc=%d", rc)

            client.on_message = on_message
            client.on_connect = on_connect
            client.on_disconnect = on_disconnect
            
            port = 443
            
            _LOGGER.warning(f"Connessione MQTT a {hostname}:{port} con path {ws_path}")
            client.connect(hostname, port, 60)
            client.loop_start()
            return client

        try:
            await self.hass.async_add_executor_job(_connect_mqtt)
        except Exception as e:
            _LOGGER.error("Errore setup MQTT: %s", e)

    async def _handle_mqtt_payload(self, payload):
        """Aggiorna i dati nel loop principale con gli aggiornamenti MQTT (ASYNC-SAFE)."""
        _LOGGER.warning(f"[MQTT HANDLER] Payload ricevuto: {payload}")
        
        device_id = payload.get("device_id")
        if not device_id:
            _LOGGER.warning("[MQTT HANDLER] Payload senza device_id")
            return
        
        if not self.data or device_id not in self.data:
            _LOGGER.warning(f"[MQTT HANDLER] Device '{device_id}' non trovato")
            return
        
        # Mappiamo i campi MQTT ai campi interni di Home Assistant
        mqtt_to_ha_mapping = {
            'state': 'vehicleState',  # MQTT 'state' -> HA 'vehicleState'
            # Aggiungi altri mapping se necessario
        }
        
        old_state = self.data[device_id].get("vehicleState", "unknown")
        
        # Aggiorna i campi con mapping
        for mqtt_field, ha_field in mqtt_to_ha_mapping.items():
            if mqtt_field in payload:
                self.data[device_id][ha_field] = payload[mqtt_field]
                _LOGGER.warning(f"[MQTT HANDLER] Mappato {mqtt_field}={payload[mqtt_field]} -> {ha_field}")
        
        # Aggiungi anche i campi non mappati (battery, timestamp, device_id)
        for key in ['battery', 'timestamp']:
            if key in payload:
                self.data[device_id][key] = payload[key]
        
        new_state = self.data[device_id].get("vehicleState", "unknown")
        
        _LOGGER.warning(f"[MQTT HANDLER] Device '{device_id}': vehicleState {old_state} -> {new_state}")
        _LOGGER.warning(f"[MQTT HANDLER] Dati aggiornati: {self.data[device_id]}")
        
        # Notifichiamo Home Assistant di aggiornare le entità
        await self.async_set_updated_data(self.data)
        _LOGGER.warning(f"[MQTT HANDLER] async_set_updated_data() chiamato con successo")