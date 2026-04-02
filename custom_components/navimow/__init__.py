"""The Segway Navimow integration."""
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN
from .api import NavimowApiClient

PLATFORMS = ["lawn_mower"]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Segway Navimow from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    
    # Recuperiamo il token salvato dal config flow
    token = entry.data.get("access_token")
    session = async_get_clientsession(hass)

    # Inizializziamo il nostro nuovo client API
    api_client = NavimowApiClient(token, session)

    # Recuperiamo i dispositivi
    devices = await api_client.async_get_devices()

    # Salviamo il client e i dispositivi in modo che lawn_mower.py possa leggerli
    hass.data[DOMAIN][entry.entry_id] = {
        "api": api_client,
        "devices": devices
    }

    # Carichiamo le piattaforme (creerà le entità vere e proprie)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok