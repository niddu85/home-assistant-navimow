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
        entity
        for device in coordinator.devices
        for entity in (
            NavimowBattery(coordinator, device),
            NavimowErrorSensor(coordinator, device),
            NavimowMowingZoneSensor(coordinator, device),
            NavimowMowingProgressSensor(coordinator, device),
        )
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


class NavimowMowingZoneSensor(NavimowEntity, SensorEntity):
    """Zone the mower is mowing, from the MQTT location channel.

    The value is the mower's internal zone id, not the name shown in the app.
    """

    _attr_translation_key = "mowing_zone"
    _attr_icon = "mdi:texture-box"

    def __init__(self, coordinator, device) -> None:
        super().__init__(coordinator, device, "mowing_zone")

    @property
    def native_value(self) -> str | None:
        zone = self.coordinator.locations.get(self._device_id, {}).get("zone")
        return None if zone is None else str(zone)


class NavimowMowingProgressSensor(NavimowEntity, SensorEntity):
    """Progress of the current mowing route, from the MQTT location channel."""

    _attr_translation_key = "mowing_progress"
    _attr_icon = "mdi:progress-check"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0

    def __init__(self, coordinator, device) -> None:
        super().__init__(coordinator, device, "mowing_progress")

    @property
    def native_value(self) -> float | None:
        # Reported as 0-10000
        progress = self.coordinator.locations.get(self._device_id, {}).get("progress")
        if not isinstance(progress, int | float):
            return None
        return progress / 100
