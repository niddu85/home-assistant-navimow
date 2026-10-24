"""Device tracker platform for Segway Navimow."""
from __future__ import annotations

import math
from typing import Any

from homeassistant.components.device_tracker import SourceType, TrackerEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_DOCK_LATITUDE, CONF_DOCK_LONGITUDE, CONF_MAP_ROTATION
from .coordinator import NavimowConfigEntry
from .entity import NavimowEntity
from .geo import local_to_gps


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NavimowConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(NavimowTracker(coordinator, d) for d in coordinator.devices)


class NavimowTracker(NavimowEntity, TrackerEntity):
    """Mower position: local map coordinates converted with the dock location."""

    _attr_translation_key = "position"
    _attr_source_type = SourceType.GPS

    def __init__(self, coordinator, device) -> None:
        super().__init__(coordinator, device, "tracker")

    @property
    def _location(self) -> dict[str, Any]:
        return self.coordinator.locations.get(self._device_id, {})

    @property
    def _gps(self) -> tuple[float, float] | None:
        x, y = self._location.get("x"), self._location.get("y")
        if x is None or y is None:
            # No position received yet: a docked mower is at the dock
            if self.status.get("vehicleState") != "isDocked":
                return None
            x = y = 0.0
        options = self.coordinator.config_entry.options
        return local_to_gps(
            x,
            y,
            options.get(CONF_DOCK_LATITUDE, self.hass.config.latitude),
            options.get(CONF_DOCK_LONGITUDE, self.hass.config.longitude),
            options.get(CONF_MAP_ROTATION, 0),
        )

    @property
    def latitude(self) -> float | None:
        gps = self._gps
        return gps[0] if gps else None

    @property
    def longitude(self) -> float | None:
        gps = self._gps
        return gps[1] if gps else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        location = self._location
        attributes: dict[str, Any] = {}
        if "x" in location:
            attributes["local_x"] = location["x"]
            attributes["local_y"] = location["y"]
            attributes["local_heading"] = round(math.degrees(location["theta"]) % 360, 1)
            attributes["distance_from_dock"] = round(math.hypot(location["x"], location["y"]), 2)
        if location.get("zone") is not None:
            attributes["mowing_zone"] = location["zone"]
        if location.get("progress") is not None:
            attributes["mowing_progress"] = location["progress"] / 100
        return attributes
