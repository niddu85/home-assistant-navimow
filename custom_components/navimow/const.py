"""Constants for the Segway Navimow integration."""
from datetime import timedelta

DOMAIN = "navimow"

# OAuth Configuration
CLIENT_ID = "homeassistant"
CLIENT_SECRET = "57056e15-722e-42be-bbaa-b0cbfb208a52"
TOKEN_URL = "https://navimow-fra.ninebot.com/openapi/oauth/getAccessToken"
AUTH_BASE_URL = "https://navimow-h5-fra.willand.com/smartHome/login"
API_BASE_URL = "https://navimow-fra.ninebot.com/openapi"

CALLBACK_PATH = "/api/navimow/callback"

# Config entry data keys
CONF_ACCESS_TOKEN = "access_token"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_EXPIRES_AT = "expires_at"

UPDATE_INTERVAL = timedelta(seconds=30)

# Raw vehicleState values reported by the API
OFFLINE_STATES = {"offline", "Offline"}
ERROR_STATES = {"Error", "error", "isLifted"}
