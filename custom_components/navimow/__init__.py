"""Inizializzazione integrazione."""
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN
from .api import NavimowApiClient
from .coordinator import NavimowDataUpdateCoordinator

PLATFORMS = ["lawn_mower", "sensor", "binary_sensor", "device_tracker"]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Configura l'entry dell'integrazione."""
    hass.data.setdefault(DOMAIN, {})
    
    token = entry.data.get("access_token")
    session = async_get_clientsession(hass)
    api_client = NavimowApiClient(token, session)

    # 1. Recupero dispositivi iniziale
    devices = await api_client.async_get_devices()

    # 2. Creazione Coordinator
    coordinator = NavimowDataUpdateCoordinator(hass, api_client, entry, devices)
    
    # 3. Primo refresh (indispensabile per creare le entità con dati)
    await coordinator.async_config_entry_first_refresh()

    # 4. Salvataggio dati per le piattaforme
    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "api": api_client,
        "devices": devices
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Rimuove l'integrazione."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok