from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import DeviceInfo
from .const import DOMAIN

async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    devices = hass.data[DOMAIN][entry.entry_id]["devices"]
    async_add_entities([NavimowConnectivity(coordinator, d) for d in devices])

class NavimowConnectivity(CoordinatorEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, coordinator, device_data):
        super().__init__(coordinator)
        self._id = device_data.get("id")
        self._attr_name = f"{device_data.get('name')} Connectivity"
        self._attr_unique_id = f"{self._id}_connectivity"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, self._id)})

    @property
    def is_on(self):
        device_status = self.coordinator.data.get(self._id, {})
        return device_status.get("online", True) and device_status.get("vehicleState") != "offline"