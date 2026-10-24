"""Binary sensor platform for Segway Navimow."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import NavimowConfigEntry
from .entity import NavimowEntity, is_online


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NavimowConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(NavimowConnectivity(coordinator, d) for d in coordinator.devices)


class NavimowConnectivity(NavimowEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, coordinator, device) -> None:
        super().__init__(coordinator, device, "connectivity")

    @property
    def available(self) -> bool:
        # Must stay available while the mower is offline: that is its state
        return self.coordinator.last_update_success and self._device_id in (
            self.coordinator.data or {}
        )

    @property
    def is_on(self) -> bool:
        return is_online(self.status)
