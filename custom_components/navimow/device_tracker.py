"""Device tracker platform for Segway Navimow."""
from __future__ import annotations

from homeassistant.components.device_tracker import SourceType, TrackerEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import NavimowConfigEntry
from .entity import NavimowEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NavimowConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(NavimowTracker(coordinator, d) for d in coordinator.devices)


class NavimowTracker(NavimowEntity, TrackerEntity):
    _attr_translation_key = "position"
    _attr_source_type = SourceType.GPS

    def __init__(self, coordinator, device) -> None:
        super().__init__(coordinator, device, "tracker")

    @property
    def latitude(self) -> float | None:
        pos = self.status.get("position")
        return pos.get("lat") if isinstance(pos, dict) else None

    @property
    def longitude(self) -> float | None:
        pos = self.status.get("position")
        return pos.get("lng") if isinstance(pos, dict) else None
