"""Lawn mower platform for Segway Navimow."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.lawn_mower import (
    LawnMowerActivity,
    LawnMowerEntity,
    LawnMowerEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import NavimowAuthError, NavimowError
from .coordinator import NavimowConfigEntry
from .entity import NavimowEntity

_LOGGER = logging.getLogger(__name__)

# Home Assistant has no "idle" activity: idle and self-checking mowers are
# reported as docked. Offline mowers make the entity unavailable instead.
RAW_STATE_TO_ACTIVITY = {
    "isDocked": LawnMowerActivity.DOCKED,
    "isIdel": LawnMowerActivity.DOCKED,
    "isIdle": LawnMowerActivity.DOCKED,
    "Self-Checking": LawnMowerActivity.DOCKED,
    "Self-checking": LawnMowerActivity.DOCKED,
    "isMapping": LawnMowerActivity.MOWING,
    "isRunning": LawnMowerActivity.MOWING,
    "isPaused": LawnMowerActivity.PAUSED,
    "inSoftwareUpdate": LawnMowerActivity.PAUSED,
    "isDocking": LawnMowerActivity.RETURNING,
    "Error": LawnMowerActivity.ERROR,
    "error": LawnMowerActivity.ERROR,
    "isLifted": LawnMowerActivity.ERROR,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NavimowConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(NavimowLawnMower(coordinator, d) for d in coordinator.devices)


class NavimowLawnMower(NavimowEntity, LawnMowerEntity):
    _attr_name = None
    _attr_supported_features = (
        LawnMowerEntityFeature.START_MOWING
        | LawnMowerEntityFeature.PAUSE
        | LawnMowerEntityFeature.DOCK
    )

    @property
    def activity(self) -> LawnMowerActivity | None:
        """Return the current mowing activity, None if not recognized."""
        raw_state = self.status.get("vehicleState")
        if raw_state is None:
            return None
        activity = RAW_STATE_TO_ACTIVITY.get(raw_state)
        if activity is None:
            _LOGGER.debug("Unknown Navimow vehicleState '%s'", raw_state)
        return activity

    async def _async_send_command(
        self, command: str, params: dict[str, Any] | None = None
    ) -> None:
        try:
            await self.coordinator.api.async_send_command(self._device_id, command, params)
        except NavimowAuthError as err:
            self.coordinator.config_entry.async_start_reauth(self.hass)
            raise HomeAssistantError(f"Navimow authentication failed: {err}") from err
        except NavimowError as err:
            raise HomeAssistantError(f"Navimow command {command} failed: {err}") from err
        await self.coordinator.async_request_refresh()

    async def async_start_mowing(self) -> None:
        if self.activity == LawnMowerActivity.PAUSED:
            await self._async_send_command(
                "action.devices.commands.PauseUnpause", {"on": True}
            )
        else:
            await self._async_send_command(
                "action.devices.commands.StartStop", {"on": True}
            )

    async def async_pause(self) -> None:
        await self._async_send_command(
            "action.devices.commands.PauseUnpause", {"on": False}
        )

    async def async_dock(self) -> None:
        await self._async_send_command("action.devices.commands.Dock")
