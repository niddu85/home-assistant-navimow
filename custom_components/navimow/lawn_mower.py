"""Support for Navimow lawn mowers."""
from homeassistant.components.lawn_mower import (
    LawnMowerEntity,
    LawnMowerEntityFeature,
    LawnMowerActivity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN

async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Navimow lawn mowers based on a config entry."""
    # Recuperiamo i dati passati da __init__.py
    api = hass.data[DOMAIN][entry.entry_id]["api"]
    devices = hass.data[DOMAIN][entry.entry_id]["devices"]

    entities = []
    for device_data in devices:
        entities.append(NavimowLawnMower(api, device_data))

    # Aggiunge i tagliaerba a Home Assistant
    async_add_entities(entities)


class NavimowLawnMower(LawnMowerEntity):
    """Rappresentazione del robot tagliaerba Navimow."""

    _attr_supported_features = (
        LawnMowerEntityFeature.START_MOWING
        | LawnMowerEntityFeature.PAUSE
        | LawnMowerEntityFeature.DOCK
    )

    def __init__(self, api, device_data):
        """Inizializza l'entità estraendo i dati dal dizionario fornito."""
        self._api = api
        self._device_data = device_data
        
        # Mappiamo le proprietà usando la logica che mi hai incollato
        self._device_id = device_data.get("id") or device_data.get("iotId") or device_data.get("iot_id")
        nome = device_data.get("name") or device_data.get("deviceName") or device_data.get("device_name")
        
        self._attr_name = nome if nome else "Navimow Mower"
        self._attr_unique_id = self._device_id

        # Questo blocco lega l'entità a un "Dispositivo" fisico nella UI di Home Assistant
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            name=self._attr_name,
            manufacturer="Segway",
            model=device_data.get("model", "Navimow"),
            sw_version=device_data.get("firmware_version"),
            serial_number=device_data.get("serial_number"),
        )

    @property
    def activity(self) -> LawnMowerActivity:
        """Per ora ritorniamo uno stato fisso. Lo aggiorneremo con il polling o MQTT."""
        return LawnMowerActivity.DOCKED

    async def async_start_mowing(self) -> None:
        """Invia il comando per avviare il taglio."""
        # TODO: Implementare chiamata API
        pass

    async def async_pause(self) -> None:
        """Invia il comando per mettere in pausa."""
        # TODO: Implementare chiamata API
        pass

    # 2. CORREGGI QUI: Rinomina questo metodo in async_dock
    async def async_dock(self) -> None:
        """Invia il comando per tornare alla base."""
        # TODO: Implementare chiamata API
        pass