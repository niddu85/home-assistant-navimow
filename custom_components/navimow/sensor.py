"""Sensor platform for Segway Navimow."""
from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import ERROR_STATES
from .coordinator import NavimowConfigEntry
from .entity import NavimowEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NavimowConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        [NavimowBattery(coordinator, d) for d in coordinator.devices]
        + [NavimowErrorSensor(coordinator, d) for d in coordinator.devices]
    )


class NavimowBattery(NavimowEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, device) -> None:
        super().__init__(coordinator, device, "battery")

    @property
    def native_value(self) -> float | None:
        # "battery" is only present after an MQTT update, which is newer than
        # the last REST poll (each poll replaces the whole status)
        battery = self.status.get("battery")
        if isinstance(battery, (int, float)):
            return battery
        cap = self.status.get("capacityRemaining")
        if isinstance(cap, list) and cap and isinstance(cap[0], dict):
            return cap[0].get("rawValue")
        return None


class NavimowErrorSensor(NavimowEntity, SensorEntity):
    _attr_translation_key = "error"
    _attr_icon = "mdi:alert-circle"

    def __init__(self, coordinator, device) -> None:
        super().__init__(coordinator, device, "error")

    @property
    def native_value(self) -> str:
        error_code = self.status.get("error_code")
        if error_code and error_code != "none":
            return error_code
        if self.status.get("vehicleState") in ERROR_STATES:
            return self.status["vehicleState"]
        return "none"
