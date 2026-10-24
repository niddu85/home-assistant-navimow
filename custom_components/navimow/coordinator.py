"""DataUpdateCoordinator for Segway Navimow integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import NavimowApiClient, NavimowAuthError, NavimowError
from .const import DOMAIN, ERROR_STATES, UPDATE_INTERVAL

_LOGGER = logging.getLogger(__name__)

type NavimowConfigEntry = ConfigEntry[NavimowDataUpdateCoordinator]

MQTT_ERROR_EVENTS = {"Error", "error", "isLifted", "stuck"}
MQTT_RECOVERY_EVENTS = {"errorRecovery", "clear"}
MQTT_STATE_KEYS = ("battery", "timestamp", "signal_strength")


class NavimowDataUpdateCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """Polls vehicle status via REST and merges real-time MQTT updates."""

    config_entry: NavimowConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: NavimowConfigEntry,
        api: NavimowApiClient,
        devices: list[dict[str, Any]],
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self.api = api
        self.devices = devices
        self.device_ids = [d["id"] for d in devices]
        # Data from the MQTT location channel, kept apart from the REST status
        # because each poll replaces the whole status
        self.locations: dict[str, dict[str, Any]] = {}

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        try:
            data = await self.api.async_get_vehicles_status(self.device_ids)
        except NavimowAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except NavimowError as err:
            raise UpdateFailed(f"Error communicating with Navimow: {err}") from err

        # Error details only arrive through MQTT events, and the REST status
        # does not include them: keep them while the mower is still in error.
        previous = self.data or {}
        for device_id, status in data.items():
            error_code = previous.get(device_id, {}).get("error_code")
            if (
                error_code
                and "error_code" not in status
                and status.get("vehicleState") in ERROR_STATES
            ):
                status["error_code"] = error_code
        return data

    @callback
    def async_handle_mqtt_message(self, topic: str, payload: Any) -> None:
        """Merge an MQTT update into the coordinator data."""
        # Topic format: /downlink/vehicle/{device_id}/realtimeDate/{channel}
        parts = topic.split("/")
        channel = parts[-1]
        topic_device_id = parts[3] if len(parts) > 3 else None

        if channel == "location":
            self._async_handle_location(topic_device_id, payload)
            return
        if not isinstance(payload, dict):
            return

        device_id = payload.get("device_id") or topic_device_id
        if not self.data or device_id not in self.data:
            _LOGGER.debug("MQTT update for unknown device '%s'", device_id)
            return

        status = dict(self.data[device_id])

        if channel == "state":
            if "state" in payload:
                status["vehicleState"] = payload["state"]
            for key in MQTT_STATE_KEYS:
                if key in payload:
                    status[key] = payload[key]

        elif channel == "event":
            event_type = payload.get("event", "")
            level = payload.get("level", "")
            _LOGGER.debug("Device '%s' event: type=%s level=%s", device_id, event_type, level)
            if level == "error" or event_type in MQTT_ERROR_EVENTS:
                status["error_code"] = event_type or level
                status["vehicleState"] = "Error"
            elif level == "info" and event_type in MQTT_RECOVERY_EVENTS:
                status["error_code"] = "none"
            else:
                return

        elif channel == "attributes":
            attributes = payload.get("attributes", payload)
            if not isinstance(attributes, dict):
                return
            status.update(attributes)

        else:
            return

        # Not async_set_updated_data: it reschedules the REST poll, which would
        # never run while pushes keep arriving (positions come every 2 seconds)
        self.data = {**self.data, device_id: status}
        self.async_update_listeners()

    @callback
    def _async_handle_location(self, device_id: str | None, payload: Any) -> None:
        """Decode the location channel: a JSON array of items keyed by type."""
        if device_id not in self.device_ids or not isinstance(payload, list):
            return
        previous = self.locations.get(device_id, {})
        location = dict(previous)
        for item in payload:
            if not isinstance(item, dict):
                continue
            item_type = item.get("type")
            if item_type == 1:
                # Pose: meters from the dock on the mower's map, heading in radians
                try:
                    location["x"] = float(item["postureX"])
                    location["y"] = float(item["postureY"])
                    location["theta"] = float(item.get("postureTheta", 0))
                except (KeyError, TypeError, ValueError):
                    continue
            elif item_type == 2:
                # Mowing progress (0-10000) and zone the mower is in
                if "currentMowProgress" in item:
                    location["progress"] = item["currentMowProgress"]
                if "currentMowBoundary" in item:
                    location["zone"] = item["currentMowBoundary"]
            elif item_type == 3:
                # Zones requested at mow start, absent when mowing everything
                location["target_zones"] = item.get("partitionIds")
            elif item_type == 4:
                location["task_delay"] = item.get("taskDelay")
        if location != previous:
            self.locations[device_id] = location
            self.async_update_listeners()
