"""Constants for the Crestron Home integration."""

from __future__ import annotations

DOMAIN = "crestron_home"

SHADE_POSITION_MAX = 65535

CONF_API_TOKEN = "api_token"
CONF_INVERT = "invert"
OPT_CALIBRATION = "calibration"
CAL_KEY_ANCHORS = "anchors"
CAL_KEY_INVERT = "invert"

CAL_ANCHOR_PC_MIN = 0
CAL_ANCHOR_PC_MAX = 100
CAL_ANCHOR_RAW_MIN = 0
CAL_ANCHOR_RAW_MAX = SHADE_POSITION_MAX

CAL_DEFAULT_ANCHORS = [
    {"pc": CAL_ANCHOR_PC_MIN, "raw": CAL_ANCHOR_RAW_MIN},
    {"pc": CAL_ANCHOR_PC_MAX, "raw": CAL_ANCHOR_RAW_MAX},
]

ERR_ANCHORS_TOO_FEW = "anchors_too_few"
ERR_ANCHORS_ENDPOINT = "anchors_endpoint"
ERR_ANCHORS_PC_RANGE = "anchors_pc_range"
ERR_ANCHORS_RAW_RANGE = "anchors_raw_range"
ERR_ANCHORS_PC_ORDER = "anchors_pc_order"
ERR_ANCHORS_RAW_MONOTONIC = "anchors_raw_monotonic"

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
DATA_CALIBRATIONS = "calibrations"

SHADE_POLL_INTERVAL_IDLE = 12
SHADE_POLL_INTERVAL_FAST = 1.5
SHADE_BOOST_SECONDS = 10

BATCH_DEBOUNCE_MS = 80
BATCH_MAX_ITEMS = 16
