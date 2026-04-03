from homeassistant.components.lawn_mower import LawnMowerEntity, LawnMowerEntityFeature, LawnMowerActivity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import DeviceInfo
from .const import DOMAIN

RAW_STATE_TO_CANONICAL = {
    "isDocked": "docked",
    "isIdel": "idle",
    "isIdle": "idle",
    "isMapping": "mowing",
    "isRunning": "mowing",
    "isPaused": "paused",
    "isDocking": "returning",
    "Error": "error",
    "error": "error",
    "isLifted": "error",
    "inSoftwareUpdate": "paused",
    "Self-Checking": "idle",
    "Self-checking": "idle",
    "Offline": "unknown",
    "offline": "unknown",
}

async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    devices = hass.data[DOMAIN][entry.entry_id]["devices"]
    async_add_entities([NavimowLawnMower(coordinator, d) for d in devices])

class NavimowLawnMower(CoordinatorEntity, LawnMowerEntity):
    _attr_supported_features = (
        LawnMowerEntityFeature.START_MOWING | LawnMowerEntityFeature.PAUSE | LawnMowerEntityFeature.DOCK
    )

    def __init__(self, coordinator, device_data):
        super().__init__(coordinator)
        self._id = device_data.get("id")
        self._attr_name = device_data.get("name")
        self._attr_unique_id = self._id
        
        # Questo collega l'entità al dispositivo fisico nella UI
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._id)},
            name=self._attr_name,
            manufacturer="Segway",
            model=device_data.get("model"),
            sw_version=device_data.get("firmware_version"),
        )

    @property
    def activity(self) -> LawnMowerActivity:
        """Get current mowing activity state."""
        device_status = self.coordinator.data.get(self._id, {})
        
        raw_state = device_status.get("vehicleState")
        canonical = RAW_STATE_TO_CANONICAL.get(raw_state, "unknown")

        if canonical == "mowing":
            return LawnMowerActivity.MOWING
        if canonical == "returning":
            return LawnMowerActivity.RETURNING
        if canonical == "paused":
            return LawnMowerActivity.PAUSED
        if canonical == "error":
            return LawnMowerActivity.ERROR
        
        # Default per idle, docked o stati sconosciuti
        return LawnMowerActivity.DOCKED

    async def async_start_mowing(self):
        await self.coordinator.api.async_send_command(self._id, "action.devices.commands.StartStop", {"on": True})
        await self.coordinator.async_request_refresh()
    
    async def async_pause(self):
        await self.coordinator.api.async_send_command(self._id, "action.devices.commands.PauseUnpause", {"on": False})
        await self.coordinator.async_request_refresh()

    async def async_dock(self):
        await self.coordinator.api.async_send_command(self._id, "action.devices.commands.Dock")
        await self.coordinator.async_request_refresh()