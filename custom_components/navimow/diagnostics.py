"""Diagnostics support for Segway Navimow."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import (
    CONF_ACCESS_TOKEN,
    CONF_DOCK_LATITUDE,
    CONF_DOCK_LONGITUDE,
    CONF_REFRESH_TOKEN,
)
from .coordinator import NavimowConfigEntry

TO_REDACT = {
    CONF_ACCESS_TOKEN,
    CONF_REFRESH_TOKEN,
    CONF_DOCK_LATITUDE,
    CONF_DOCK_LONGITUDE,
    "position",
    "lat",
    "lng",
    "latitude",
    "longitude",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: NavimowConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    return {
        "entry_data": async_redact_data(dict(entry.data), TO_REDACT),
        "entry_options": async_redact_data(dict(entry.options), TO_REDACT),
        "devices": coordinator.devices,
        "status": async_redact_data(coordinator.data or {}, TO_REDACT),
        # Local map coordinates: meters from the dock, not GPS
        "locations": coordinator.locations,
    }
