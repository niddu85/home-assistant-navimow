"""Sensor platform for Navimow integration."""
from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Navimow sensor."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    async_add_entities([NavimowSensor(coordinator)])


class NavimowSensor(CoordinatorEntity, SensorEntity):
    """Representation of a Navimow sensor."""

    def __init__(self, coordinator):
        """Initialize the sensor."""
        super().__init__(coordinator)

    @property
    def name(self):
        """Return the name of the sensor."""
        return "Navimow Status"

    @property
    def state(self):
        """Return the state of the sensor."""
        return self.coordinator.data.get("status") if self.coordinator.data else None

    @property
    def unique_id(self):
        """Return a unique ID."""
        return f"{self.coordinator.config_entry.entry_id}_status"