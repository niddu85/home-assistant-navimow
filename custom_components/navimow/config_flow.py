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
    """Endpoint HTTP in Home Assistant per catturare il redirect di Navimow."""
    
    url = "/api/navimow/callback"
    name = "api:navimow:callback"
    requires_auth = False

    def __init__(self, hass: HomeAssistant, flow_id: str):
        """Inizializza la view passando l'ID del config flow da sbloccare."""
        self.hass = hass
        self.flow_id = flow_id

    async def get(self, request: web.Request) -> web.Response:
        """Gestisce la richiesta GET di ritorno da Navimow."""
        code = request.query.get("code")
        
        if not code:
            return web.Response(text="Errore: Nessun parametro 'code' trovato nell'URL di redirect.", status=400)

        # Sblocchiamo il Config Flow passandogli in modo asincrono il codice ricevuto
        await self.hass.config_entries.flow.async_configure(
            flow_id=self.flow_id,
            user_input={"code": code}
        )

        # Mostriamo all'utente una pagina di successo così capisce che può chiudere la scheda
        html_response = """
        <html>
            <head><title>Autenticazione Navimow</title></head>
            <body style="font-family: sans-serif; text-align: center; padding: 50px; background-color: #121212; color: white;">
                <h2 style="color: #4CAF50;">Autenticazione completata con successo!</h2>
                <p>Home Assistant ha ricevuto i dati. Puoi chiudere questa finestra e tornare all'app.</p>
            </body>
        </html>
        """
        return web.Response(text=html_response, content_type="text/html")


class NavimowConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Gestisce il setup della configurazione via UI per Navimow."""
    
    VERSION = 1

    def __init__(self):
        """Inizializza il flow."""
        self.redirect_uri = None
        self.account_name = None  # Variabile per memorizzare il nome scelto dall'utente

    async def async_step_user(self, user_input=None):
        """Step 1: Chiediamo all'utente come vuole chiamare questo account."""
        errors = {}

        if user_input is not None:
            self.account_name = user_input["account_name"]

            # Impostiamo questo nome come ID univoco dell'integrazione
            await self.async_set_unique_id(self.account_name)
            # Se l'utente ha già un'integrazione con questo nome, blocchiamo il processo
            self._abort_if_unique_id_configured()

            # Passiamo allo step successivo (l'autenticazione vera e propria)
            return await self.async_step_auth()

        # Mostriamo il modulo per inserire il nome
        data_schema = vol.Schema({
            vol.Required("account_name", default="Mio Navimow"): str
        })

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors
        )

    async def async_step_auth(self, user_input=None):
        """Step 2: Mostriamo il link per il login e attendiamo la callback."""
        
        # Se riceviamo il codice (passato dalla nostra NavimowCallbackView)
        if user_input is not None and "code" in user_input:
            return await self.async_step_exchange(user_input["code"])

        # Costruiamo l'URL come prima
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

        # Mettiamo in ascolto l'endpoint HTTP
        self.hass.http.register_view(NavimowCallbackView(self.hass, self.flow_id))

        return self.async_show_form(
            step_id="auth", 
            description_placeholders={"auth_url": auth_url}
        )

    async def async_step_exchange(self, code: str):
        """Step 3: Scambiamo il codice con il token e salviamo col nome personalizzato."""
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
                    # Usiamo self.account_name come titolo!
                    return self.async_create_entry(
                        title=self.account_name, 
                        data={
                            "access_token": token_data["access_token"],
                            "refresh_token": token_data.get("refresh_token"),
                            "expires_in": token_data.get("expires_in", 3600),
                        }
                    )
                else:
                    _LOGGER.error("Errore risposta token: %s", token_data)
                    return self.async_abort(reason="auth_failed")
                    
        except Exception as e:
            _LOGGER.error("Errore API Navimow durante lo scambio token: %s", e)
            return self.async_abort(reason="cannot_connect")