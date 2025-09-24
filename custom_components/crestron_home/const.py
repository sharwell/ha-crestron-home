"""Constants for the Crestron Home integration."""

from __future__ import annotations

DOMAIN = "crestron_home"

CONF_API_TOKEN = "api_token"
CONF_INVERT = "invert"

DEFAULT_VERIFY_SSL = True
DEFAULT_INVERT = False

REQUEST_TIMEOUT = 10
CONFIG_FLOW_TIMEOUT = 30

HEADER_ACCEPT = "Accept"
HEADER_AUTH_TOKEN = "Crestron-RestAPI-AuthToken"
HEADER_AUTH_KEY = "Crestron-RestAPI-AuthKey"

MIME_TYPE_JSON = "application/json"

PATH_LOGIN = "/cws/api/login"
PATH_ROOMS = "/cws/api/rooms"
PATH_SHADES = "/cws/api/shades"

DATA_API_CLIENT = "api_client"
DATA_SHADES_COORDINATOR = "shades_coordinator"

SHADE_POSITION_MAX = 65535
SHADE_POLL_INTERVAL_IDLE = 12
SHADE_POLL_INTERVAL_FAST = 1.5
SHADE_BOOST_SECONDS = 10
