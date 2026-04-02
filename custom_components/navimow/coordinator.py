"""Coordinator for Navimow integration."""
import asyncio
from datetime import timedelta
import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import NavimowApi
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class NavimowCoordinator(DataUpdateCoordinator):
    """Coordinator for Navimow data updates."""

    def __init__(self, hass: HomeAssistant, api: NavimowApi):
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=5),
        )
        self.api = api

    async def _async_update_data(self):
        """Fetch data from API."""
        try:
            return await self.api.async_get_status()
        except Exception as err:
            _LOGGER.error("Error fetching data: %s", err)
            raise