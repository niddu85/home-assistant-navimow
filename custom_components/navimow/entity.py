"""Base entity for the Segway Navimow integration."""
from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, OFFLINE_STATES
from .coordinator import NavimowDataUpdateCoordinator


def is_online(status: dict[str, Any]) -> bool:
    """Return whether a device status reports the mower as online."""
    return bool(status.get("online", True)) and status.get("vehicleState") not in OFFLINE_STATES


class NavimowEntity(CoordinatorEntity[NavimowDataUpdateCoordinator]):
    """Entity bound to one Navimow device."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: NavimowDataUpdateCoordinator,
        device: dict[str, Any],
        unique_id_suffix: str | None = None,
    ) -> None:
        super().__init__(coordinator)
        self._device_id: str = device["id"]
        self._attr_unique_id = (
            f"{self._device_id}_{unique_id_suffix}" if unique_id_suffix else self._device_id
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            name=device.get("name"),
            manufacturer="Segway",
            model=device.get("model"),
            sw_version=device.get("firmware_version"),
        )

    @property
    def status(self) -> dict[str, Any]:
        """Return the latest status of this device."""
        return (self.coordinator.data or {}).get(self._device_id, {})

    @property
    def available(self) -> bool:
        """Return True if the device reported a status and is online."""
        return (
            super().available
            and self._device_id in (self.coordinator.data or {})
            and is_online(self.status)
        )
