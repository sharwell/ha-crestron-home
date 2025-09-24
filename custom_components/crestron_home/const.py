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
PATH_SHADES_SET_STATE = "/cws/api/shades/SetState"

DATA_API_CLIENT = "api_client"
DATA_SHADES_COORDINATOR = "shades_coordinator"
DATA_WRITE_BATCHER = "write_batcher"

SHADE_POSITION_MAX = 65535
SHADE_POLL_INTERVAL_IDLE = 12
SHADE_POLL_INTERVAL_FAST = 1.5
SHADE_BOOST_SECONDS = 10

BATCH_DEBOUNCE_MS = 80
BATCH_MAX_ITEMS = 16


def raw_to_pct(raw: int | None, invert: bool) -> int | None:
    """Convert a Crestron raw position value to a Home Assistant percentage."""

    if raw is None:
        return None

    if raw < 0:
        raw = 0
    elif raw > SHADE_POSITION_MAX:
        raw = SHADE_POSITION_MAX

    percentage = round(raw * 100 / SHADE_POSITION_MAX)
    if invert:
        percentage = 100 - percentage

    return max(0, min(100, percentage))


def pct_to_raw(percentage: int, invert: bool) -> int:
    """Convert a Home Assistant percentage to a Crestron raw position value."""

    pct = max(0, min(100, int(percentage)))
    if invert:
        pct = 100 - pct

    raw = round(pct * SHADE_POSITION_MAX / 100)
    if raw < 0:
        return 0
    if raw > SHADE_POSITION_MAX:
        return SHADE_POSITION_MAX
    return raw
