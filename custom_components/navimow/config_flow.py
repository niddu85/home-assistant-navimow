"""Config flow for Segway Navimow integration."""
import urllib.parse
import logging
from aiohttp import web
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.components.http import HomeAssistantView
from homeassistant.helpers.network import get_url
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

CLIENT_ID = "homeassistant"
CLIENT_SECRET = "57056e15-722e-42be-bbaa-b0cbfb208a52"
TOKEN_URL = "https://navimow-fra.ninebot.com/openapi/oauth/getAccessToken"
AUTH_BASE_URL = "https://navimow-h5-fra.willand.com/smartHome/login"


class NavimowCallbackView(HomeAssistantView):
    """HTTP endpoint in Home Assistant to handle Navimow OAuth redirect."""
    
    url = "/api/navimow/callback"
    name = "api:navimow:callback"
    requires_auth = False

    def __init__(self, hass: HomeAssistant, flow_id: str):
        """Initialize the view with the config flow ID."""
        self.hass = hass
        self.flow_id = flow_id

    async def get(self, request: web.Request) -> web.Response:
        """Handle GET request from Navimow OAuth redirect."""
        code = request.query.get("code")
        
        if not code:
            return web.Response(text="Error: 'code' parameter not found in redirect URL.", status=400)

        await self.hass.config_entries.flow.async_configure(
            flow_id=self.flow_id,
            user_input={"code": code}
        )

        html_response = """
        <html>
            <head><title>Navimow Authentication</title></head>
            <body style="font-family: sans-serif; text-align: center; padding: 50px; background-color: #121212; color: white;">
                <h2 style="color: #4CAF50;">Authentication successful!</h2>
                <p>Home Assistant has received the data. You can close this window and return to the app.</p>
            </body>
        </html>
        """
        return web.Response(text=html_response, content_type="text/html")


class NavimowConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle setup and config flow for Navimow."""
    
    VERSION = 1

    def __init__(self):
        """Initialize the flow."""
        self.redirect_uri = None
        self.account_name = None

    async def async_step_user(self, user_input=None):
        """First step: Ask user for account name."""
        errors = {}

        if user_input is not None:
            self.account_name = user_input["account_name"]

            await self.async_set_unique_id(self.account_name)
            self._abort_if_unique_id_configured()

            return await self.async_step_auth()

        data_schema = vol.Schema({
            vol.Required("account_name", default="My Navimow"): str
        })

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors
        )

    async def async_step_auth(self, user_input=None):
        """Second step: Show OAuth login link and wait for callback."""
        
        if user_input is not None and "code" in user_input:
            return await self.async_step_exchange(user_input["code"])

        try:
            ha_url = get_url(self.hass, prefer_external=True)
        except Exception:
            ha_url = get_url(self.hass)

        self.redirect_uri = f"{ha_url}/api/navimow/callback"
        
        params = {
            "channel": "homeassistant",
            "client_id": CLIENT_ID,
            "response_type": "code",
            "redirect_uri": self.redirect_uri
        }
        auth_url = f"{AUTH_BASE_URL}?{urllib.parse.urlencode(params)}"

        self.hass.http.register_view(NavimowCallbackView(self.hass, self.flow_id))

        return self.async_show_form(
            step_id="auth", 
            description_placeholders={"auth_url": auth_url}
        )

    async def async_step_exchange(self, code: str):
        """Third step: Exchange authorization code for access token."""
        session = async_get_clientsession(self.hass)
        
        payload = {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "redirect_uri": self.redirect_uri,
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        try:
            async with session.post(TOKEN_URL, data=payload, headers=headers) as response:
                response.raise_for_status()
                token_data = await response.json()

                if "access_token" in token_data:
                    return self.async_create_entry(
                        title=self.account_name, 
                        data={
                            "access_token": token_data["access_token"],
                            "refresh_token": token_data.get("refresh_token"),
                            "expires_in": token_data.get("expires_in", 3600),
                        }
                    )
                else:
                    _LOGGER.error("Error token response: %s", token_data)
                    return self.async_abort(reason="auth_failed")
                    
        except Exception as e:
            _LOGGER.error("Error during token exchange: %s", e)
            return self.async_abort(reason="cannot_connect")