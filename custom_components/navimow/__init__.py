"""Segway Navimow integration."""
from __future__ import annotations

from typing import Any

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import NavimowApiClient, NavimowAuthError, NavimowError
from .const import CONF_ACCESS_TOKEN, CONF_EXPIRES_AT, CONF_REFRESH_TOKEN
from .coordinator import NavimowConfigEntry, NavimowDataUpdateCoordinator
from .mqtt import NavimowMqttClient

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.DEVICE_TRACKER,
    Platform.LAWN_MOWER,
    Platform.SENSOR,
]


async def async_setup_entry(hass: HomeAssistant, entry: NavimowConfigEntry) -> bool:
    """Set up integration from config entry."""

    @callback
    def _async_save_tokens(token_data: dict[str, Any]) -> None:
        hass.config_entries.async_update_entry(entry, data={**entry.data, **token_data})

    api = NavimowApiClient(
        async_get_clientsession(hass),
        entry.data[CONF_ACCESS_TOKEN],
        entry.data.get(CONF_REFRESH_TOKEN),
        entry.data.get(CONF_EXPIRES_AT, 0),
        _async_save_tokens,
    )

    try:
        devices = await api.async_get_devices()
    except NavimowAuthError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except NavimowError as err:
        raise ConfigEntryNotReady(f"Unable to fetch Navimow devices: {err}") from err

    coordinator = NavimowDataUpdateCoordinator(
        hass, entry, api, [d for d in devices if d.get("id")]
    )
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    if coordinator.device_ids:
        mqtt_client = NavimowMqttClient(
            hass,
            entry,
            api,
            coordinator.device_ids,
            coordinator.async_handle_mqtt_message,
        )
        entry.async_on_unload(mqtt_client.async_stop)
        entry.async_create_background_task(
            hass, mqtt_client.async_start(), "navimow_mqtt_start"
        )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: NavimowConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
