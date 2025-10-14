"""Config flow for the Crestron Home integration."""
from __future__ import annotations

import asyncio
import copy
import logging
import re
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_VERIFY_SSL
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector
from homeassistant.exceptions import HomeAssistantError

from .api import ApiClient, CannotConnectError, CrestronHomeApiError, InvalidAuthError
from .calibration import (
    CalibrationCollection,
    DEFAULT_ANCHORS,
    InvalidCalibrationError,
    ShadeCalibration,
    parse_calibration_options,
    pct_to_raw,
    raw_to_pct,
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
    DATA_PREDICTIVE_MANAGER,
    DATA_PREDICTIVE_STORAGE,
    DATA_SHADES_COORDINATOR,
    DATA_WRITE_BATCHER,
    DEFAULT_INVERT,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
    ERR_ANCHORS_TOO_FEW,
    OPT_PREDICTIVE_STOP,
    PREDICTIVE_DEFAULT_ENABLED,
)
from .coordinator import Shade, ShadesCoordinator
from .predictive_stop import PredictiveRuntime
from .storage import PredictiveStopStore
from .visual_groups import (
    VISUAL_GROUPS_VERSION,
    VisualGroupEntry,
    VisualGroupsConfig,
    parse_visual_groups,
    update_visual_groups_option,
)
from .assisted_calibration import (
    AssistedCalibrationRun,
    apply_assisted_anchor,
    largest_gap_target,
)
from .write import ShadeWriteBatcher


_LOGGER = logging.getLogger(__name__)


VISUAL_GROUP_UNASSIGNED = "__unassigned__"


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
            options={
                CONF_INVERT: DEFAULT_INVERT,
                OPT_PREDICTIVE_STOP: PREDICTIVE_DEFAULT_ENABLED,
            },
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
        if OPT_PREDICTIVE_STOP not in self._options:
            self._options[OPT_PREDICTIVE_STOP] = PREDICTIVE_DEFAULT_ENABLED
        self._calibration_collection: CalibrationCollection = parse_calibration_options(
            self._options
        )
        self._visual_groups: VisualGroupsConfig = parse_visual_groups(self._options)
        self._selected_shade_id: str | None = None
        self._working_anchors: list[dict[str, int]] | None = None
        self._working_invert_override: bool | None = None
        self._selected_group_id: str | None = None
        self._assisted_group_id: str | None = None
        self._assisted_members: list[str] = []
        self._assisted_target_percent: int | None = None
        self._assisted_use_current_position = False
        self._assisted_stage_sent = False
        self._assisted_stage_warnings: list[str] = []
        self._assisted_active_members: list[str] = []
        self._assisted_feedback: dict[str, object] | None = None
        self._assisted_snapshot: dict[str, tuple[ShadeCalibration, bool]] | None = None
        self._assisted_last_run: AssistedCalibrationRun | None = None

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

    @property
    def _write_batcher(self) -> ShadeWriteBatcher | None:
        domain_data = self.hass.data.get(DOMAIN)
        if not domain_data:
            return None
        entry_data = domain_data.get(self._config_entry.entry_id)
        if not entry_data:
            return None
        batcher = entry_data.get(DATA_WRITE_BATCHER)
        if isinstance(batcher, ShadeWriteBatcher):
            return batcher
        return None

    @property
    def _predictive_runtime(self) -> PredictiveRuntime | None:
        domain_data = self.hass.data.get(DOMAIN)
        if not domain_data:
            return None
        entry_data = domain_data.get(self._config_entry.entry_id)
        if not entry_data:
            return None
        runtime = entry_data.get(DATA_PREDICTIVE_MANAGER)
        if isinstance(runtime, PredictiveRuntime):
            return runtime
        return None

    @property
    def _predictive_store(self) -> PredictiveStopStore | None:
        domain_data = self.hass.data.get(DOMAIN)
        if not domain_data:
            return None
        entry_data = domain_data.get(self._config_entry.entry_id)
        if not entry_data:
            return None
        store = entry_data.get(DATA_PREDICTIVE_STORAGE)
        if isinstance(store, PredictiveStopStore):
            return store
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

    def _visual_group_choices(self) -> dict[str, str]:
        return {
            group_id: entry.name
            for group_id, entry in sorted(self._visual_groups.groups.items())
        }

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
    def _normalize_group_id(value: Any) -> str:
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

    def _generate_group_id(self, name: str) -> str:
        base = re.sub(r"[^a-z0-9_]+", "_", name.lower()).strip("_")
        if not base:
            base = "group"
        candidate = base
        suffix = 1
        while candidate in self._visual_groups.groups:
            suffix += 1
            candidate = f"{base}_{suffix}"
        return candidate

    def _save_visual_groups(self) -> None:
        self._visual_groups.version = VISUAL_GROUPS_VERSION
        update_visual_groups_option(self._options, self._visual_groups)

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return self.async_show_menu(
            step_id="init",
            menu_options=[
                "global_defaults",
                "select_shade",
                "assisted_calibration",
                "visual_groups",
                "predictive_stop",
                "reset_learning",
                "finish",
            ],
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

    async def async_step_visual_groups(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        self._selected_group_id = None
        menu: list[str] = ["visual_groups_create"]
        if self._visual_groups.groups:
            menu.extend(
                [
                    "visual_groups_rename_select",
                    "visual_groups_delete_select",
                ]
            )
        menu.extend(["visual_groups_assign", "visual_groups_back"])
        return self.async_show_menu(step_id="visual_groups", menu_options=menu)

    async def async_step_visual_groups_back(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return await self.async_step_init()

    async def async_step_visual_groups_create(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            name = str(user_input.get("name", "")).strip()
            if not name:
                errors["name"] = "invalid_group_name"
            else:
                group_id = self._generate_group_id(name)
                self._visual_groups.groups[group_id] = VisualGroupEntry(name=name)
                self._save_visual_groups()
                return await self.async_step_visual_groups()

        data_schema = vol.Schema({vol.Required("name", default=""): str})
        return self.async_show_form(
            step_id="visual_groups_create",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_visual_groups_rename_select(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if not self._visual_groups.groups:
            return await self.async_step_visual_groups()

        errors: dict[str, str] = {}
        if user_input is not None:
            group_id = self._normalize_group_id(user_input.get("group"))
            if group_id and group_id in self._visual_groups.groups:
                self._selected_group_id = group_id
                return await self.async_step_visual_groups_rename()
            errors["group"] = "invalid_group"

        options = [
            {"label": name, "value": group_id}
            for group_id, name in self._visual_group_choices().items()
        ]
        data_schema = vol.Schema(
            {
                vol.Required("group"): selector.selector(
                    {"select": {"options": options}}
                )
            }
        )
        return self.async_show_form(
            step_id="visual_groups_rename_select",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_visual_groups_rename(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        group_id = self._selected_group_id
        if not group_id or group_id not in self._visual_groups.groups:
            return await self.async_step_visual_groups()

        errors: dict[str, str] = {}
        current_name = self._visual_groups.groups[group_id].name
        if user_input is not None:
            name = str(user_input.get("name", "")).strip()
            if not name:
                errors["name"] = "invalid_group_name"
            else:
                self._visual_groups.groups[group_id] = VisualGroupEntry(name=name)
                self._save_visual_groups()
                self._selected_group_id = None
                return await self.async_step_visual_groups()

        data_schema = vol.Schema({vol.Required("name", default=current_name): str})
        return self.async_show_form(
            step_id="visual_groups_rename",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_visual_groups_delete_select(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if not self._visual_groups.groups:
            return await self.async_step_visual_groups()

        errors: dict[str, str] = {}
        if user_input is not None:
            group_id = self._normalize_group_id(user_input.get("group"))
            if group_id and group_id in self._visual_groups.groups:
                self._selected_group_id = group_id
                return await self.async_step_visual_groups_delete_confirm()
            errors["group"] = "invalid_group"

        options = [
            {"label": name, "value": group_id}
            for group_id, name in self._visual_group_choices().items()
        ]
        data_schema = vol.Schema(
            {
                vol.Required("group"): selector.selector(
                    {"select": {"options": options}}
                )
            }
        )
        return self.async_show_form(
            step_id="visual_groups_delete_select",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_visual_groups_delete_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        group_id = self._selected_group_id
        if not group_id or group_id not in self._visual_groups.groups:
            return await self.async_step_visual_groups()

        if user_input is not None:
            if user_input.get("confirm"):
                self._visual_groups.groups.pop(group_id, None)
                self._visual_groups.membership = {
                    shade_id: assigned
                    for shade_id, assigned in self._visual_groups.membership.items()
                    if assigned != group_id
                }
                self._save_visual_groups()
            self._selected_group_id = None
            return await self.async_step_visual_groups()

        data_schema = vol.Schema({vol.Required("confirm", default=False): bool})
        return self.async_show_form(
            step_id="visual_groups_delete_confirm",
            data_schema=data_schema,
            description_placeholders={"group": self._visual_groups.groups[group_id].name},
        )

    async def async_step_visual_groups_assign(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        shade_labels = self._shade_choices()
        known_shades = sorted(set(shade_labels).union(self._visual_groups.membership))

        if not known_shades:
            return await self.async_step_visual_groups()

        group_options = [
            {"label": name, "value": group_id}
            for group_id, name in self._visual_group_choices().items()
        ]
        group_options.sort(key=lambda item: item["label"].lower())
        group_options.insert(0, {"label": "Unassigned", "value": VISUAL_GROUP_UNASSIGNED})

        schema_dict: dict[Any, Any] = {}
        for shade_id in known_shades:
            default = self._visual_groups.membership.get(shade_id, VISUAL_GROUP_UNASSIGNED)
            if default not in self._visual_groups.groups:
                default = VISUAL_GROUP_UNASSIGNED
            schema_dict[
                vol.Required(f"shade::{shade_id}", default=default)
            ] = selector.selector({"select": {"options": group_options}})

        errors: dict[str, str] = {}
        if user_input is not None:
            new_membership: dict[str, str] = {}
            invalid = False
            for shade_id in known_shades:
                key = f"shade::{shade_id}"
                selected = self._normalize_group_id(user_input.get(key))
                if not selected or selected == VISUAL_GROUP_UNASSIGNED:
                    continue
                if selected not in self._visual_groups.groups:
                    invalid = True
                    continue
                new_membership[shade_id] = selected

            if invalid:
                errors["base"] = "invalid_group"
            else:
                self._visual_groups.membership = new_membership
                self._save_visual_groups()
                return await self.async_step_visual_groups()

        data_schema = vol.Schema(schema_dict)
        return self.async_show_form(
            step_id="visual_groups_assign",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_predictive_stop(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            self._options[OPT_PREDICTIVE_STOP] = bool(user_input[OPT_PREDICTIVE_STOP])
            return await self.async_step_init()

        data_schema = vol.Schema(
            {
                vol.Required(
                    OPT_PREDICTIVE_STOP,
                    default=bool(
                        self._options.get(
                            OPT_PREDICTIVE_STOP, PREDICTIVE_DEFAULT_ENABLED
                        )
                    ),
                ): bool,
            }
        )
        return self.async_show_form(
            step_id="predictive_stop",
            data_schema=data_schema,
        )

    async def async_step_reset_learning(
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
                store = self._predictive_store
                if store is not None:
                    await store.async_clear_shade(shade_id)
                runtime = self._predictive_runtime
                if runtime is not None:
                    runtime.reset_shade(shade_id)
                return await self.async_step_init()

        if choices:
            options = [
                {"value": str(shade_id), "label": str(label)}
                for shade_id, label in choices.items()
            ]
            selector_schema = selector.selector(
                {
                    "select": {
                        "options": options,
                        "mode": "dropdown",
                        "custom_value": True,
                    }
                }
            )
            data_schema = vol.Schema({vol.Required("shade"): selector_schema})
        else:
            data_schema = vol.Schema({vol.Required("shade"): str})

        return self.async_show_form(
            step_id="reset_learning",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_assisted_calibration(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return await self.async_step_assisted_calibration_select_group(user_input)

    async def async_step_assisted_calibration_select_group(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        status = ""

        if self._assisted_feedback:
            status = self._assisted_feedback.get("status", "") or ""
            self._assisted_feedback = None

        if user_input is not None:
            action_raw = user_input.get("action")
            action = str(self._selector_value(action_raw or "start")).strip().lower()
            if action == "back":
                self._assisted_reset()
                return await self.async_step_init()
            if action == "undo":
                if self._assisted_last_run and self._assisted_snapshot:
                    self._assisted_restore_snapshot()
                    status = self._assisted_status_text(
                        "Assisted calibration undo applied",
                        saved=self._assisted_last_run.saved,
                        skipped=self._assisted_last_run.skipped,
                    )
                    self._assisted_last_run = None
                else:
                    errors["base"] = "assisted_no_undo"
            else:
                group_raw = user_input.get("group")
                group_id = self._normalize_group_id(group_raw)
                if not group_id:
                    errors["group"] = "invalid_group"
                elif group_id not in self._visual_groups.groups:
                    errors["group"] = "invalid_group"
                else:
                    if not self._assisted_prepare_group(group_id):
                        errors["group"] = "assisted_empty_group"
                    else:
                        return await self.async_step_assisted_calibration_target()

        group_options = []
        for group_id, entry in sorted(self._visual_groups.groups.items()):
            members = self._assisted_group_members(group_id)
            if not members:
                continue
            label = f"{entry.name} ({len(members)})"
            group_options.append({"value": group_id, "label": label})

        schema_dict: OrderedDict[Any, Any] = OrderedDict()
        if group_options:
            schema_dict[vol.Required("group")] = selector.selector(
                {"select": {"options": group_options}}
            )
        else:
            status = status or "No visual groups are configured."

        action_options = [
            {"value": "start", "label": "Start"},
            {"value": "undo", "label": "Undo last"},
            {"value": "back", "label": "Back"},
        ]
        schema_dict[vol.Required("action", default="start")] = selector.selector(
            {"select": {"options": action_options, "mode": "dropdown"}}
        )

        data_schema = vol.Schema(schema_dict)

        if not status:
            status = "Select a visual group to begin."

        return self.async_show_form(
            step_id="assisted_calibration_select_group",
            data_schema=data_schema,
            errors=errors,
            description_placeholders={
                "status": status,
            },
        )

    async def async_step_assisted_calibration_target(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if not self._assisted_group_id:
            return await self.async_step_assisted_calibration_select_group()

        errors: dict[str, str] = {}
        status = ""

        if self._assisted_feedback:
            status = self._assisted_feedback.get("status", "") or ""
            self._assisted_feedback = None

        if user_input is not None:
            action_raw = user_input.get("action")
            action = str(self._selector_value(action_raw or "stage")).strip().lower()
            if action == "back":
                self._assisted_reset()
                return await self.async_step_assisted_calibration_select_group()

            mode_raw = user_input.get("mode")
            mode = str(self._selector_value(mode_raw or "automatic")).strip().lower()
            target_raw = user_input.get("target_percent")
            try:
                target = int(target_raw)
            except (TypeError, ValueError):
                errors["target_percent"] = "anchors_pc_range"
                target = self._assisted_target_percent or 50
            else:
                if target < CAL_ANCHOR_PC_MIN or target > CAL_ANCHOR_PC_MAX:
                    errors["target_percent"] = "anchors_pc_range"
            if not errors:
                self._assisted_target_percent = max(
                    CAL_ANCHOR_PC_MIN, min(CAL_ANCHOR_PC_MAX, target)
                )
                self._assisted_use_current_position = mode == "current"
                self._assisted_stage_sent = False
                return await self.async_step_assisted_calibration_stage()

        if self._assisted_target_percent is None:
            calibrations = [
                self._calibration_collection.for_shade(shade_id)
                for shade_id in self._assisted_members
            ]
            self._assisted_target_percent = largest_gap_target(calibrations)

        mode_options = [
            {"value": "automatic", "label": "Automatic"},
            {"value": "current", "label": "From current location"},
        ]
        schema_dict: OrderedDict[Any, Any] = OrderedDict()
        schema_dict[vol.Required("mode", default="automatic")] = selector.selector(
            {"select": {"options": mode_options, "mode": "dropdown"}}
        )
        schema_dict[vol.Required(
            "target_percent", default=self._assisted_target_percent
        )] = vol.All(
            vol.Coerce(int),
            vol.Range(min=CAL_ANCHOR_PC_MIN, max=CAL_ANCHOR_PC_MAX),
        )
        schema_dict[vol.Required("action", default="stage")] = selector.selector(
            {"select": {"options": [{"value": "stage", "label": "Continue"}, {"value": "back", "label": "Change group"}]}}
        )

        data_schema = vol.Schema(schema_dict)

        members_label = ", ".join(self._assisted_member_labels(self._assisted_members))
        group_name = self._visual_groups.group_name(
            self._assisted_group_id, shade_ids=self._assisted_members
        )

        return self.async_show_form(
            step_id="assisted_calibration_target",
            data_schema=data_schema,
            errors=errors,
            description_placeholders={
                "group": group_name,
                "members": members_label,
                "status": status,
            },
        )

    async def async_step_assisted_calibration_stage(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if not self._assisted_group_id or self._assisted_target_percent is None:
            return await self.async_step_assisted_calibration_select_group()

        errors: dict[str, str] = {}

        if not self._assisted_stage_sent:
            try:
                await self._assisted_perform_stage()
            except HomeAssistantError as err:
                errors["base"] = "assisted_stage_failed"
                self._assisted_feedback = {
                    "status": str(err),
                }

        if user_input is not None:
            action_raw = user_input.get("action")
            action = str(self._selector_value(action_raw or "record")).strip().lower()
            if action == "target":
                return await self.async_step_assisted_calibration_target()
            if action == "cancel":
                self._assisted_reset()
                return await self.async_step_assisted_calibration_select_group()
            if action == "restage":
                self._assisted_stage_sent = False
                return await self.async_step_assisted_calibration_stage()
            if action == "record":
                try:
                    saved, skipped = await self._assisted_record()
                except InvalidCalibrationError as err:
                    errors["base"] = err.code
                else:
                    status = self._assisted_status_text(
                        "Recorded calibration",
                        saved=saved,
                        skipped=skipped,
                    )
                    self._assisted_feedback = {"status": status}
                    self._assisted_stage_sent = False
                    return await self.async_step_assisted_calibration_target()

        members_label = ", ".join(self._assisted_member_labels(self._assisted_members))
        warnings = ", ".join(self._assisted_stage_warnings)
        positions = ", ".join(self._assisted_stage_positions())

        action_options = [
            {"value": "record", "label": "Record anchors"},
            {"value": "restage", "label": "Stage again"},
            {"value": "target", "label": "Pick new target"},
            {"value": "cancel", "label": "Back to groups"},
        ]

        data_schema = vol.Schema(
            {
                vol.Required("action", default="record"): selector.selector(
                    {"select": {"options": action_options, "mode": "dropdown"}}
                )
            }
        )

        return self.async_show_form(
            step_id="assisted_calibration_stage",
            data_schema=data_schema,
            errors=errors,
            description_placeholders={
                "group": self._visual_groups.group_name(
                    self._assisted_group_id, shade_ids=self._assisted_members
                ),
                "members": members_label,
                "warnings": warnings,
                "positions": positions,
                "target": str(self._assisted_target_percent),
            },
        )

    async def async_step_select_shade(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        choices = self._shade_choices()

        if user_input is not None:
            try:
                shade_raw = user_input.get("shade")
                shade_id = self._normalize_shade_id(shade_raw)
                if not shade_id:
                    errors["base"] = "select_shade"
                else:
                    self._selected_shade_id = shade_id
                    self._load_working_calibration(shade_id)
                    return await self.async_step_edit_shade()
            except Exception:  # pragma: no cover - defensive logging
                _LOGGER.exception(
                    "Unexpected error while handling shade selection: %s", user_input
                )
                if "base" not in errors:
                    errors["base"] = "unknown"

        if choices:
            options = [
                {"value": str(shade_id), "label": str(label)}
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

    def _assisted_reset(self) -> None:
        self._assisted_group_id = None
        self._assisted_members = []
        self._assisted_target_percent = None
        self._assisted_use_current_position = False
        self._assisted_stage_sent = False
        self._assisted_stage_warnings = []
        self._assisted_active_members = []

    def _assisted_group_members(self, group_id: str) -> list[str]:
        members = [
            shade_id
            for shade_id, assigned in self._visual_groups.membership.items()
            if assigned == group_id
        ]
        members.sort()
        return members

    def _assisted_prepare_group(self, group_id: str) -> bool:
        members = self._assisted_group_members(group_id)
        if not members:
            return False
        self._assisted_group_id = group_id
        self._assisted_members = members
        calibrations = [
            self._calibration_collection.for_shade(shade_id)
            for shade_id in members
        ]
        self._assisted_target_percent = largest_gap_target(calibrations)
        self._assisted_use_current_position = False
        self._assisted_stage_sent = False
        self._assisted_stage_warnings = []
        self._assisted_active_members = []
        return True

    def _assisted_member_labels(self, members: Sequence[str]) -> list[str]:
        labels: list[str] = []
        coordinator = self._coordinator
        data = coordinator.data if coordinator and coordinator.data else {}
        for shade_id in members:
            label = shade_id
            shade = data.get(shade_id) if isinstance(data, Mapping) else None
            if isinstance(shade, Shade) and shade.name:
                if shade.name == shade_id:
                    label = shade.name
                else:
                    label = f"{shade.name} ({shade_id})"
            labels.append(label)
        return labels

    def _assisted_status_text(
        self, prefix: str, *, saved: Sequence[str], skipped: Sequence[str]
    ) -> str:
        parts = [prefix]
        if saved:
            parts.append(
                "saved " + ", ".join(self._assisted_member_labels(saved))
            )
        if skipped:
            parts.append(
                "skipped " + ", ".join(self._assisted_member_labels(skipped))
            )
        return "; ".join(parts)

    async def _assisted_perform_stage(self) -> None:
        coordinator = self._coordinator
        self._assisted_stage_warnings = []
        self._assisted_active_members = []
        if coordinator is None:
            self._assisted_stage_warnings.append("Controller unavailable")
            self._assisted_stage_sent = True
            return

        data = coordinator.data or {}
        available: list[str] = []
        for shade_id in self._assisted_members:
            shade = data.get(shade_id)
            if not isinstance(shade, Shade):
                label = self._assisted_member_labels([shade_id])[0]
                self._assisted_stage_warnings.append(f"{label}: unavailable")
                continue
            if not shade.is_connected:
                label = self._assisted_member_labels([shade_id])[0]
                self._assisted_stage_warnings.append(f"{label}: offline")
                continue
            available.append(shade_id)

        self._assisted_active_members = available
        self._assisted_stage_sent = True

        if self._assisted_use_current_position or not available:
            return

        batcher = self._write_batcher
        if batcher is None:
            self._assisted_stage_warnings.append("Shade control unavailable")
            return

        target = self._assisted_target_percent or 0
        tasks = []
        for shade_id in available:
            calibration = self._calibration_collection.for_shade(shade_id)
            invert = calibration.resolved_invert(self._calibration_collection.global_invert)
            raw = pct_to_raw(target, calibration.anchors, invert)
            tasks.append(batcher.enqueue(shade_id, raw))

        if tasks:
            await asyncio.gather(*tasks)
            coordinator.burst()

    def _assisted_stage_positions(self) -> list[str]:
        coordinator = self._coordinator
        if coordinator is None or not coordinator.data:
            return []
        positions: list[str] = []
        for shade_id in self._assisted_members:
            shade = coordinator.data.get(shade_id)
            if not isinstance(shade, Shade) or shade.position is None:
                continue
            calibration = self._calibration_collection.for_shade(shade_id)
            invert = calibration.resolved_invert(self._calibration_collection.global_invert)
            pct = raw_to_pct(shade.position, calibration.anchors, invert)
            label = self._assisted_member_labels([shade_id])[0]
            if pct is None:
                positions.append(f"{label}: {shade.position}")
            else:
                positions.append(f"{label}: {pct}% ({shade.position})")
        return positions

    async def _assisted_record(self) -> tuple[list[str], list[str]]:
        coordinator = self._coordinator
        if coordinator is None or not coordinator.data:
            raise InvalidCalibrationError(
                ERR_ANCHORS_TOO_FEW, "Shades are unavailable"
            )

        target = self._assisted_target_percent or 0
        saved: list[str] = []
        skipped: list[str] = []
        snapshot: dict[str, tuple[ShadeCalibration, bool]] = {}
        new_values: dict[str, ShadeCalibration] = {}

        for shade_id in self._assisted_members:
            shade = coordinator.data.get(shade_id)
            if not isinstance(shade, Shade) or shade.position is None:
                skipped.append(shade_id)
                continue
            calibration = self._calibration_collection.for_shade(shade_id)
            anchors, changed = apply_assisted_anchor(
                calibration,
                target,
                shade.position,
            )
            if not changed:
                skipped.append(shade_id)
                continue
            snapshot[shade_id] = (
                calibration,
                shade_id in self._calibration_collection.per_shade,
            )
            new_values[shade_id] = ShadeCalibration(
                anchors=anchors,
                invert_override=calibration.invert_override,
            )
            saved.append(shade_id)

        for shade_id in saved:
            update_calibration_option(self._options, shade_id, new_values[shade_id])

        timestamp = datetime.now(timezone.utc)
        run = AssistedCalibrationRun(
            group_id=self._assisted_group_id or "",
            target_percent=target,
            saved=tuple(saved),
            skipped=tuple(skipped),
            timestamp=timestamp,
        )

        if saved:
            self._calibration_collection = parse_calibration_options(self._options)
            self._assisted_snapshot = snapshot
        else:
            self._assisted_snapshot = None

        self._assisted_last_run = run
        coordinator.record_assisted_calibration(run)
        _LOGGER.debug(
            "Assisted calibration run",
            extra={
                "group": self._assisted_group_id,
                "target_percent": target,
                "saved": saved,
                "skipped": skipped,
            },
        )

        return saved, skipped

    def _assisted_restore_snapshot(self) -> None:
        snapshot = self._assisted_snapshot
        if not snapshot:
            return
        for shade_id, (calibration, had_entry) in snapshot.items():
            if not had_entry and calibration == ShadeCalibration():
                remove_calibration_option(self._options, shade_id)
                continue
            update_calibration_option(self._options, shade_id, calibration)
        self._calibration_collection = parse_calibration_options(self._options)
        self._assisted_snapshot = None

    async def async_step_edit_shade(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        assert self._selected_shade_id is not None
        if self._working_anchors is None:
            self._load_working_calibration(self._selected_shade_id)

        errors: dict[str, str] = {}

        if user_input is not None:
            try:
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
            except Exception:  # pragma: no cover - defensive logging
                _LOGGER.exception(
                    "Unexpected error while handling shade calibration: %s",
                    {
                        "shade_id": self._selected_shade_id,
                        "user_input": user_input,
                    },
                )
                if "base" not in errors:
                    errors["base"] = "unknown"

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
                insert_options.append({"value": str(index), "label": label})
            schema_dict[vol.Optional(
                "insert_after", default=str(len(self._working_anchors) - 2)
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
                remove_options.append({"value": str(index), "label": label})
            schema_dict[vol.Optional("remove_index", default="1")] = selector.selector(
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
