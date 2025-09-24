"""Constants for the Crestron Home integration."""

from __future__ import annotations

DOMAIN = "crestron_home"

CONF_API_TOKEN = "api_token"

DEFAULT_VERIFY_SSL = True

REQUEST_TIMEOUT = 10
CONFIG_FLOW_TIMEOUT = 30

HEADER_ACCEPT = "Accept"
HEADER_AUTH_TOKEN = "Crestron-RestAPI-AuthToken"
HEADER_AUTH_KEY = "Crestron-RestAPI-AuthKey"

MIME_TYPE_JSON = "application/json"

PATH_LOGIN = "/cws/api/login"
PATH_ROOMS = "/cws/api/rooms"
