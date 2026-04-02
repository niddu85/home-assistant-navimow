from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import PERCENTAGE
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import DeviceInfo
from .const import DOMAIN

async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    devices = hass.data[DOMAIN][entry.entry_id]["devices"]
    async_add_entities([NavimowBattery(coordinator, d) for d in devices])

class NavimowBattery(CoordinatorEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, device_data):
        super().__init__(coordinator)
        self._id = device_data.get("id")
        self._attr_name = f"{device_data.get('name')} Battery"
        self._attr_unique_id = f"{self._id}_battery"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, self._id)})

    @property
    def native_value(self):
        device_status = self.coordinator.data.get(self._id, {})
        cap = device_status.get("capacityRemaining", [{}])
        return cap[0].get("rawValue") if cap else None