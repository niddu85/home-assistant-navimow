from homeassistant.components.device_tracker import SourceType
from homeassistant.components.device_tracker.config_entry import TrackerEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import DeviceInfo
from .const import DOMAIN

async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    devices = hass.data[DOMAIN][entry.entry_id]["devices"]
    async_add_entities([NavimowTracker(coordinator, d) for d in devices])

class NavimowTracker(CoordinatorEntity, TrackerEntity):
    def __init__(self, coordinator, device_data):
        super().__init__(coordinator)
        self._id = device_data.get("id")
        self._attr_name = f"{device_data.get('name')} Position"
        self._attr_unique_id = f"{self._id}_tracker"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, self._id)})

    @property
    def latitude(self):
        pos = self.coordinator.data.get(self._id, {}).get("position")
        return pos.get("lat") if pos else None

    @property
    def longitude(self):
        pos = self.coordinator.data.get(self._id, {}).get("position")
        return pos.get("lng") if pos else None

    @property
    def source_type(self):
        return SourceType.GPS