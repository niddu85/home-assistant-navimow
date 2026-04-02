"""Navimow integration for Home Assistant."""
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

from .api import NavimowApi
from .coordinator import NavimowCoordinator
from .const import DOMAIN


async def async_setup(hass: HomeAssistant, config: dict):
    """Set up the Navimow integration via configuration.yaml (legacy)."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up Navimow from a config entry."""
    api = NavimowApi(
        entry.data["host"], entry.data["username"], entry.data["password"]
    )
    await api.async_setup()

    coordinator = NavimowCoordinator(hass, api)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await coordinator.async_config_entry_first_refresh()

    # Forward setup to platforms
    await hass.config_entries.async_forward_entry_setups(entry, ["sensor"])
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, ["sensor"])
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok