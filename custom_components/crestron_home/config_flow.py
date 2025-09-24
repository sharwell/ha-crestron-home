"""Config flow for the Crestron Home integration."""
from __future__ import annotations

import asyncio
import copy
import logging
from collections import OrderedDict
from typing import Any, Mapping
from urllib.parse import urlparse

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_VERIFY_SSL
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .api import ApiClient, CannotConnectError, CrestronHomeApiError, InvalidAuthError
from .calibration import (
    CalibrationCollection,
    DEFAULT_ANCHORS,
    InvalidCalibrationError,
    ShadeCalibration,
    parse_calibration_options,
    remove_calibration_option,
    update_calibration_option,
    validate_anchors,
)
from .const import (
    CAL_ANCHOR_PC_MAX,
    CAL_ANCHOR_PC_MIN,
    CAL_ANCHOR_RAW_MAX,
    CAL_ANCHOR_RAW_MIN,
    CONFIG_FLOW_TIMEOUT,
    CONF_API_TOKEN,
    CONF_INVERT,
    DATA_SHADES_COORDINATOR,
    DEFAULT_INVERT,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
    ERR_ANCHORS_TOO_FEW,
)
from .coordinator import Shade, ShadesCoordinator


_LOGGER = logging.getLogger(__name__)


class CrestronHomeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Crestron Home."""

    VERSION = 1

    def __init__(self) -> None:
        self._user_input: dict[str, Any] | None = None
        self._rooms_count: int = 0

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle the initial step of the config flow."""

        errors: dict[str, str] = {}
        submitted: dict[str, Any] | None = None

        if user_input is not None:
            submitted = dict(user_input)
            host = submitted.get(CONF_HOST, "").strip()
            if "://" in host:
                parsed = urlparse(host)
                if parsed.hostname:
                    host = parsed.hostname
                    if parsed.port:
                        host = f"{host}:{parsed.port}"
                else:
                    host = host.split("//", 1)[1]
            host = host.strip("/")
            submitted[CONF_HOST] = host
            submitted[CONF_API_TOKEN] = submitted.get(CONF_API_TOKEN, "").strip()
            submitted[CONF_VERIFY_SSL] = bool(
                submitted.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)
            )

            if self._host_already_configured(host):
                return self.async_abort(reason="already_configured")

            client = ApiClient(
                self.hass,
                host,
                submitted[CONF_API_TOKEN],
                verify_ssl=submitted[CONF_VERIFY_SSL],
            )

            request_details = {
                "host": host,
                "verify_ssl": submitted[CONF_VERIFY_SSL],
            }
            log_level = logging.DEBUG
            response_details: Any | Exception | None = None

            try:
                async with asyncio.timeout(CONFIG_FLOW_TIMEOUT):
                    rooms = await client.async_get_rooms()
            except asyncio.TimeoutError as err:
                log_level = logging.WARNING
                response_details = err
                errors["base"] = "cannot_connect"
            except InvalidAuthError as err:
                log_level = logging.WARNING
                response_details = err
                errors["base"] = "invalid_auth"
            except CannotConnectError as err:
                log_level = logging.WARNING
                response_details = err
                errors["base"] = "cannot_connect"
            except CrestronHomeApiError as err:
                log_level = logging.WARNING
                response_details = err
                errors["base"] = "unknown"
            else:
                response_details = rooms
                self._rooms_count = len(rooms)
                self._user_input = submitted
                return await self.async_step_confirm()
            finally:
                _LOGGER.log(log_level, "Connection test request: %s", request_details)
                _LOGGER.log(log_level, "Connection test response: %s", response_details)
                await client.async_logout()

        defaults = submitted or user_input or {}

        data_schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): str,
                vol.Required(CONF_API_TOKEN, default=""): str,
                vol.Optional(
                    CONF_VERIFY_SSL,
                    default=defaults.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
                ): bool,
            }
        )

        return self.async_show_form(step_id="user", data_schema=data_schema, errors=errors)

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Show confirmation step before creating the entry."""

        assert self._user_input is not None
        host = self._user_input[CONF_HOST]

        if user_input is None:
            return self.async_show_form(
                step_id="confirm",
                description_placeholders={
                    "host": host,
                    "rooms": str(self._rooms_count),
                },
            )

        await self.async_set_unique_id(host)
        self._abort_if_unique_id_configured()

        return self.async_create_entry(
            title=f"Crestron Home ({host})",
            data={
                CONF_HOST: host,
                CONF_API_TOKEN: self._user_input[CONF_API_TOKEN],
                CONF_VERIFY_SSL: bool(self._user_input.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)),
            },
            options={CONF_INVERT: DEFAULT_INVERT},
        )

    def _host_already_configured(self, host: str) -> bool:
        """Return True if the host already has a config entry."""

        normalized_host = host.lower()
        for entry in self._async_current_entries():
            existing_host = entry.data.get(CONF_HOST, "").lower()
            if existing_host == normalized_host:
                return True
        return False

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow."""

        return CrestronHomeOptionsFlowHandler(config_entry)


class CrestronHomeOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options for the Crestron Home integration."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._config_entry = config_entry

        base_options = dict(config_entry.options)
        self._options: dict[str, Any] = copy.deepcopy(base_options)
        if CONF_INVERT not in self._options:
            self._options[CONF_INVERT] = DEFAULT_INVERT
        self._calibration_collection: CalibrationCollection = parse_calibration_options(
            self._options
        )
        self._selected_shade_id: str | None = None
        self._working_anchors: list[dict[str, int]] | None = None
        self._working_invert_override: bool | None = None

    @property
    def _coordinator(self) -> ShadesCoordinator | None:
        domain_data = self.hass.data.get(DOMAIN)
        if not domain_data:
            return None
        entry_data = domain_data.get(self._config_entry.entry_id)
        if not entry_data:
            return None
        coordinator = entry_data.get(DATA_SHADES_COORDINATOR)
        if isinstance(coordinator, ShadesCoordinator):
            return coordinator
        return None

    def _shade_choices(self) -> dict[str, str]:
        choices: dict[str, str] = {}
        coordinator = self._coordinator
        if coordinator and coordinator.data:
            for shade_id, shade in sorted(coordinator.data.items()):
                label = shade.name if shade.name else shade_id
                if shade.name and shade.name != shade_id:
                    label = f"{shade.name} ({shade_id})"
                choices[shade_id] = label
        else:
            for shade_id in sorted(self._calibration_collection.per_shade.keys()):
                choices[shade_id] = shade_id
        return choices

    @staticmethod
    def _selector_value(value: Any) -> Any:
        """Return the actual payload from Home Assistant selector values."""

        if isinstance(value, Mapping):
            if "value" in value:
                return value["value"]
            if "id" in value:
                return value["id"]

        candidate = getattr(value, "value", None)
        if candidate is not None:
            return candidate

        return value

    @staticmethod
    def _normalize_shade_id(value: Any) -> str:
        """Extract a shade identifier from selector values."""

        candidate = CrestronHomeOptionsFlowHandler._selector_value(value)
        if candidate is None:
            return ""

        return str(candidate).strip()

    @staticmethod
    def _invert_to_form(value: bool | None) -> str:
        if value is True:
            return "inverted"
        if value is False:
            return "normal"
        return "default"

    @staticmethod
    def _invert_from_form(value: Any) -> bool | None:
        normalized = CrestronHomeOptionsFlowHandler._selector_value(value)
        if normalized is None:
            return None

        if isinstance(normalized, str):
            lowered = normalized.strip().lower()
        else:
            lowered = str(normalized).strip().lower()

        if lowered == "inverted":
            return True
        if lowered == "normal":
            return False
        return None

    @staticmethod
    def _new_anchor_between(
        previous_anchor: dict[str, int], next_anchor: dict[str, int]
    ) -> dict[str, int]:
        span_pc = next_anchor["pc"] - previous_anchor["pc"]
        if span_pc <= 1:
            pct = previous_anchor["pc"] + 1
        else:
            pct = previous_anchor["pc"] + span_pc // 2
        pct = max(CAL_ANCHOR_PC_MIN + 1, min(pct, CAL_ANCHOR_PC_MAX - 1))
        raw_span = next_anchor["raw"] - previous_anchor["raw"]
        if raw_span == 0:
            raw_value = previous_anchor["raw"]
        else:
            raw_value = previous_anchor["raw"] + round(raw_span / 2)
        raw_value = max(CAL_ANCHOR_RAW_MIN, min(raw_value, CAL_ANCHOR_RAW_MAX))
        return {"pc": pct, "raw": raw_value}

    def _load_working_calibration(self, shade_id: str) -> None:
        calibration = self._calibration_collection.for_shade(shade_id)
        self._working_anchors = [
            {"pc": anchor[0], "raw": anchor[1]} for anchor in calibration.anchors
        ]
        self._working_invert_override = calibration.invert_override

    def _anchors_from_input(self, user_input: Mapping[str, Any]) -> list[dict[str, int]]:
        assert self._working_anchors is not None
        anchors: list[dict[str, int]] = []
        for index in range(len(self._working_anchors)):
            anchors.append(
                {
                    "pc": int(user_input[f"pc_{index}"]),
                    "raw": int(user_input[f"raw_{index}"]),
                }
            )
        return anchors

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return self.async_show_menu(
            step_id="init",
            menu_options={
                "global_defaults": "options_menu_global_defaults",
                "select_shade": "options_menu_select_shade",
                "finish": "options_menu_finish",
            },
        )

    async def async_step_finish(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return self.async_create_entry(title="", data=self._options)

    async def async_step_global_defaults(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            self._options[CONF_INVERT] = bool(user_input[CONF_INVERT])
            self._calibration_collection = parse_calibration_options(self._options)
            return await self.async_step_init()

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_INVERT,
                    default=bool(self._options.get(CONF_INVERT, DEFAULT_INVERT)),
                ): bool,
            }
        )
        return self.async_show_form(
            step_id="global_defaults",
            data_schema=data_schema,
        )

    async def async_step_select_shade(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        choices = self._shade_choices()

        if user_input is not None:
            shade_raw = user_input.get("shade")
            shade_id = self._normalize_shade_id(shade_raw)
            if not shade_id:
                errors["base"] = "select_shade"
            else:
                self._selected_shade_id = shade_id
                self._load_working_calibration(shade_id)
                return await self.async_step_edit_shade()

        if choices:
            options = [
                {"value": shade_id, "label": label}
                for shade_id, label in choices.items()
            ]
            shade_selector = selector.selector(
                {
                    "select": {
                        "options": options,
                        "mode": "dropdown",
                        "custom_value": True,
                    }
                }
            )
            data_schema = vol.Schema({vol.Required("shade"): shade_selector})
        else:
            data_schema = vol.Schema({vol.Required("shade"): str})

        return self.async_show_form(
            step_id="select_shade",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_edit_shade(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        assert self._selected_shade_id is not None
        if self._working_anchors is None:
            self._load_working_calibration(self._selected_shade_id)

        errors: dict[str, str] = {}

        if user_input is not None:
            anchors = self._anchors_from_input(user_input)
            self._working_anchors = anchors
            self._working_invert_override = self._invert_from_form(
                user_input.get("invert_axis")
            )
            action_raw = user_input.get("action")
            if action_raw is None:
                action = "save"
            else:
                action = str(self._selector_value(action_raw)).strip().lower()
                if not action:
                    action = "save"

            if action == "add":
                insert_after_raw = user_input.get("insert_after")
                if insert_after_raw is None:
                    insert_index = len(anchors) - 2
                else:
                    insert_after_value = self._selector_value(insert_after_raw)
                    try:
                        insert_index = int(insert_after_value)
                    except (TypeError, ValueError):
                        insert_index = len(anchors) - 2
                insert_index = max(0, min(insert_index, len(anchors) - 2))
                new_anchor = self._new_anchor_between(
                    anchors[insert_index], anchors[insert_index + 1]
                )
                anchors.insert(insert_index + 1, new_anchor)
                self._working_anchors = anchors
                return await self.async_step_edit_shade()

            if action == "remove":
                remove_index_raw = user_input.get("remove_index")
                if remove_index_raw is None:
                    remove_idx = 1
                else:
                    remove_index_value = self._selector_value(remove_index_raw)
                    try:
                        remove_idx = int(remove_index_value)
                    except (TypeError, ValueError):
                        remove_idx = 1
                if len(anchors) <= 2 or not (0 < remove_idx < len(anchors) - 1):
                    errors["base"] = ERR_ANCHORS_TOO_FEW
                else:
                    anchors.pop(remove_idx)
                    self._working_anchors = anchors
                    return await self.async_step_edit_shade()

            if action == "reset":
                self._working_anchors = [
                    {"pc": pc, "raw": raw} for pc, raw in DEFAULT_ANCHORS
                ]
                self._working_invert_override = None
                return await self.async_step_edit_shade()

            if action == "cancel":
                self._selected_shade_id = None
                self._working_anchors = None
                self._working_invert_override = None
                return await self.async_step_select_shade()

            if action == "save":
                try:
                    anchors_tuple = validate_anchors(self._working_anchors)
                except InvalidCalibrationError as err:
                    errors["base"] = err.code
                else:
                    calibration = ShadeCalibration(
                        anchors=anchors_tuple,
                        invert_override=self._working_invert_override,
                    )
                    if (
                        calibration.anchors == DEFAULT_ANCHORS
                        and calibration.invert_override is None
                    ):
                        remove_calibration_option(
                            self._options, self._selected_shade_id
                        )
                    else:
                        update_calibration_option(
                            self._options, self._selected_shade_id, calibration
                        )
                    self._calibration_collection = parse_calibration_options(
                        self._options
                    )
                    self._selected_shade_id = None
                    self._working_anchors = None
                    self._working_invert_override = None
                    return await self.async_step_select_shade()

        schema_dict: OrderedDict[Any, Any] = OrderedDict()
        assert self._working_anchors is not None
        for index, anchor in enumerate(self._working_anchors):
            schema_dict[vol.Required(
                f"pc_{index}", default=anchor["pc"]
            )] = vol.All(
                vol.Coerce(int),
                vol.Range(min=CAL_ANCHOR_PC_MIN, max=CAL_ANCHOR_PC_MAX),
            )
            schema_dict[vol.Required(
                f"raw_{index}", default=anchor["raw"]
            )] = vol.All(
                vol.Coerce(int),
                vol.Range(min=CAL_ANCHOR_RAW_MIN, max=CAL_ANCHOR_RAW_MAX),
            )

        invert_selector = selector.selector(
            {
                "select": {
                    "options": [
                        {"value": "default", "label": "Use global default"},
                        {"value": "normal", "label": "Normal axis"},
                        {"value": "inverted", "label": "Invert axis"},
                    ],
                    "mode": "dropdown",
                }
            }
        )
        schema_dict[vol.Required(
            "invert_axis",
            default=self._invert_to_form(self._working_invert_override),
        )] = invert_selector

        action_selector = selector.selector(
            {
                "select": {
                    "options": [
                        {"value": "save", "label": "Save calibration"},
                        {"value": "add", "label": "Add anchor"},
                        {"value": "remove", "label": "Remove anchor"},
                        {"value": "reset", "label": "Reset to defaults"},
                        {"value": "cancel", "label": "Back"},
                    ],
                    "mode": "dropdown",
                }
            }
        )
        schema_dict[vol.Required("action", default="save")] = action_selector

        if len(self._working_anchors) >= 2:
            insert_options = []
            for index in range(len(self._working_anchors) - 1):
                current = self._working_anchors[index]
                nxt = self._working_anchors[index + 1]
                label = f"Between {current['pc']}% and {nxt['pc']}%"
                insert_options.append({"value": index, "label": label})
            schema_dict[vol.Optional(
                "insert_after", default=len(self._working_anchors) - 2
            )] = selector.selector(
                {
                    "select": {
                        "options": insert_options,
                        "mode": "dropdown",
                    }
                }
            )

        if len(self._working_anchors) > 2:
            remove_options = []
            for index in range(1, len(self._working_anchors) - 1):
                anchor = self._working_anchors[index]
                label = f"Anchor at {anchor['pc']}%"
                remove_options.append({"value": index, "label": label})
            schema_dict[vol.Optional("remove_index", default=1)] = selector.selector(
                {
                    "select": {
                        "options": remove_options,
                        "mode": "dropdown",
                    }
                }
            )

        data_schema = vol.Schema(schema_dict)
        description_placeholders = {"shade_id": self._selected_shade_id}
        shade = None
        coordinator = self._coordinator
        if coordinator and coordinator.data:
            shade = coordinator.data.get(self._selected_shade_id)
        if isinstance(shade, Shade):
            description_placeholders["shade_name"] = shade.name
        else:
            description_placeholders["shade_name"] = self._selected_shade_id

        return self.async_show_form(
            step_id="edit_shade",
            data_schema=data_schema,
            errors=errors,
            description_placeholders=description_placeholders,
        )
