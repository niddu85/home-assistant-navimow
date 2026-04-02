"""API client for Navimow."""
import aiohttp


class NavimowApi:
    """API client for Navimow device."""

    def __init__(self, host: str, username: str, password: str):
        """Initialize the API client."""
        self.host = host
        self.username = username
        self.password = password
        self.session = None

    async def async_setup(self):
        """Set up the API client."""
        self.session = aiohttp.ClientSession()

    async def async_get_status(self):
        """Get device status."""
        # Example API call
        async with self.session.get(f"{self.host}/status") as response:
            return await response.json()

    async def async_close(self):
        """Close the session."""
        if self.session:
            await self.session.close()