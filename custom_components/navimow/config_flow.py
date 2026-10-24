"""Config flow for Segway Navimow integration."""
from __future__ import annotations

import logging
import secrets
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.config_entries import SOURCE_REAUTH, ConfigFlow, ConfigFlowResult
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import UnknownFlow
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.http import KEY_HASS
from homeassistant.helpers.network import NoURLAvailableError, get_url
from homeassistant.util.hass_dict import HassKey

from .api import (
    NavimowApiClient,
    NavimowAuthError,
    NavimowError,
    async_exchange_code,
    build_authorize_url,
    token_data_to_entry_data,
)
from .const import (
    CALLBACK_PATH,
    CONF_ACCESS_TOKEN,
    CONF_EXPIRES_AT,
    CONF_REFRESH_TOKEN,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

CONF_ACCOUNT_NAME = "account_name"

# OAuth state -> flow_id of the flows waiting for the redirect
DATA_PENDING_FLOWS: HassKey[dict[str, str]] = HassKey(f"{DOMAIN}_pending_flows")
DATA_VIEW_REGISTERED: HassKey[bool] = HassKey(f"{DOMAIN}_view_registered")

HTML_PAGE = """<html>
<head><title>Navimow Authentication</title></head>
<body style="font-family: sans-serif; text-align: center; padding: 50px; background-color: #121212; color: white;">
<h2 style="color: {color};">{title}</h2>
<p>{message}</p>
</body>
</html>"""


def _html_response(success: bool, message: str) -> web.Response:
    return web.Response(
        text=HTML_PAGE.format(
            color="#4CAF50" if success else "#F44336",
            title="Authentication successful!" if success else "Authentication failed",
            message=message,
        ),
        content_type="text/html",
        status=200 if success else 400,
    )


class NavimowCallbackView(HomeAssistantView):
    """Receives the OAuth redirect and hands the code to the waiting flow."""

    url = CALLBACK_PATH
    name = "api:navimow:callback"
    requires_auth = False

    async def get(self, request: web.Request) -> web.Response:
        """Handle GET request from Navimow OAuth redirect."""
        hass = request.app[KEY_HASS]
        code = request.query.get("code")
        state = request.query.get("state")
        pending = hass.data.get(DATA_PENDING_FLOWS, {})

        flow_id = None
        if state:
            flow_id = pending.pop(state, None)
        elif len(pending) == 1:
            # The login page may not echo `state` back: in that case accept the
            # code only if exactly one flow is waiting for it.
            _, flow_id = pending.popitem()

        if not code or not flow_id:
            return _html_response(
                False, "No matching Navimow setup in progress. Please start it again."
            )

        try:
            await hass.config_entries.flow.async_configure(
                flow_id=flow_id, user_input={"code": code}
            )
        except UnknownFlow:
            return _html_response(
                False, "The Navimow setup has expired. Please start it again."
            )

        return _html_response(
            True,
            "Home Assistant has received the data. You can close this window and return to the app.",
        )


@callback
def _async_register_callback_view(hass: HomeAssistant) -> None:
    """Register the OAuth callback view once per Home Assistant run."""
    if not hass.data.get(DATA_VIEW_REGISTERED):
        hass.http.register_view(NavimowCallbackView())
        hass.data[DATA_VIEW_REGISTERED] = True


class NavimowConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle setup and config flow for Navimow."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._account_name: str | None = None
        self._redirect_uri: str | None = None
        self._state: str | None = None
        self._code: str | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """First step: ask for a name for this account."""
        if user_input is not None:
            self._account_name = user_input[CONF_ACCOUNT_NAME]
            return await self.async_step_auth()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_ACCOUNT_NAME, default="My Navimow"): str}
            ),
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start reauthentication when the stored tokens are rejected."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask the user to log in again."""
        if user_input is None:
            return self.async_show_form(step_id="reauth_confirm")
        return await self.async_step_auth()

    async def async_step_auth(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Send the user to the Navimow login page and wait for the redirect."""
        if user_input is not None:
            # Called by NavimowCallbackView with the authorization code
            self._code = user_input["code"]
            return self.async_external_step_done(next_step_id="exchange")

        try:
            ha_url = get_url(self.hass, prefer_external=True)
        except NoURLAvailableError:
            return self.async_abort(reason="no_url")

        self._redirect_uri = f"{ha_url}{CALLBACK_PATH}"
        self._state = secrets.token_urlsafe(16)
        _async_register_callback_view(self.hass)
        self.hass.data.setdefault(DATA_PENDING_FLOWS, {})[self._state] = self.flow_id

        return self.async_external_step(
            step_id="auth", url=build_authorize_url(self._redirect_uri, self._state)
        )

    async def async_step_exchange(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Exchange the authorization code for tokens and create the entry."""
        assert self._code is not None and self._redirect_uri is not None
        session = async_get_clientsession(self.hass)
        try:
            token_data = await async_exchange_code(
                session, self._code, self._redirect_uri
            )
            entry_data = token_data_to_entry_data(token_data)
            api = NavimowApiClient(
                session,
                entry_data[CONF_ACCESS_TOKEN],
                entry_data[CONF_REFRESH_TOKEN],
                entry_data[CONF_EXPIRES_AT],
                entry_data.update,
            )
            devices = await api.async_get_devices()
        except NavimowAuthError as err:
            _LOGGER.error("Navimow authentication failed: %s", err)
            return self.async_abort(reason="auth_failed")
        except NavimowError as err:
            _LOGGER.error("Error connecting to Navimow: %s", err)
            return self.async_abort(reason="cannot_connect")

        device_ids = {d["id"] for d in devices if d.get("id")}

        if self.source == SOURCE_REAUTH:
            reauth_entry = self._get_reauth_entry()
            known_ids = self._configured_device_ids(reauth_entry.entry_id)
            if known_ids and device_ids and known_ids.isdisjoint(device_ids):
                return self.async_abort(reason="wrong_account")
            return self.async_update_reload_and_abort(
                reauth_entry, data_updates=entry_data
            )

        if device_ids & self._configured_device_ids():
            return self.async_abort(reason="already_configured")

        return self.async_create_entry(title=self._account_name, data=entry_data)

    @callback
    def _configured_device_ids(self, entry_id: str | None = None) -> set[str]:
        """Return the Navimow device ids of one entry, or of all entries."""
        registry = dr.async_get(self.hass)
        if entry_id:
            devices = dr.async_entries_for_config_entry(registry, entry_id)
        else:
            devices = [
                device
                for entry in self._async_current_entries(include_ignore=False)
                for device in dr.async_entries_for_config_entry(registry, entry.entry_id)
            ]
        return {
            identifier
            for device in devices
            for domain, identifier in device.identifiers
            if domain == DOMAIN
        }

    @callback
    def async_remove(self) -> None:
        """Forget the pending OAuth state when the flow is closed."""
        if self._state:
            self.hass.data.get(DATA_PENDING_FLOWS, {}).pop(self._state, None)
