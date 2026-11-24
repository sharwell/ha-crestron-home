"""Calibration through Home Assistant's real config entry Options flow."""

import asyncio
from collections.abc import AsyncIterator
import json
import logging
from pathlib import Path
import re
import sys
import time
from types import MappingProxyType

import pytest
import pytest_asyncio
from homeassistant import loader
from homeassistant.config_entries import ConfigEntries, ConfigEntry, ConfigFlowResult
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr, entity_registry as er, frame
from homeassistant.helpers.config_validation import custom_serializer
from probatio import to_field_list

from custom_components.crestron_home import async_migrate_entry
from custom_components.crestron_home import config_flow
from custom_components.crestron_home.api import ShadeCommandResponse
from custom_components.crestron_home.calibration import parse_calibration_options
from custom_components.crestron_home.const import (
    CONF_API_TOKEN,
    CONF_INVERT,
    DATA_CALIBRATIONS,
    DATA_PREDICTIVE_MANAGER,
    DATA_PREDICTIVE_STORAGE,
    DATA_SHADES_COORDINATOR,
    DATA_WRITE_BATCHER,
    DOMAIN,
    OPT_CALIBRATION,
    OPT_MINIMUM_POSITIONS,
    OPT_PREDICTIVE_STOP,
    PREDICTIVE_STORAGE_KEY_PREFIX,
    PREDICTIVE_STORAGE_VERSION,
)
from custom_components.crestron_home.coordinator import ShadesCoordinator
from custom_components.crestron_home.cover import CrestronHomeShade
from custom_components.crestron_home.diagnostics import async_get_config_entry_diagnostics
from custom_components.crestron_home.learning import LearningManager
from custom_components.crestron_home.predictive_stop import PredictiveRuntime
from custom_components.crestron_home.storage import PredictiveStopStore, PredictiveStoreData
from custom_components.crestron_home.visual_groups import (
    OPT_VISUAL_GROUPS,
    parse_visual_groups,
)
from custom_components.crestron_home.write import ShadeWriteBatcher


SHADE_ID = "shade-1"
GROUP_ID = "lounge"


class FakeCrestronController:
    """Report shade positions and capture writes without opening a connection."""

    def __init__(self) -> None:
        self.position = 0
        self.connection_status = "connected"
        self.other_shades: list[dict[str, object]] = []
        self.writes: list[list[dict[str, str | int]]] = []

    async def async_get_shades(self) -> list[dict[str, object]]:
        return [
            {
                "id": SHADE_ID,
                "name": "Test shade",
                "position": self.position,
                "connectionStatus": self.connection_status,
            },
            *self.other_shades,
        ]

    async def async_set_shade_positions(
        self, items: list[dict[str, str | int]], *, validate_before_send=None,
    ) -> ShadeCommandResponse:
        if validate_before_send is not None:
            validate_before_send()
        self.writes.append([dict(item) for item in items])
        return ShadeCommandResponse(status="success", results={})


@pytest_asyncio.fixture
async def hass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[HomeAssistant]:
    instance = HomeAssistant(str(tmp_path))
    try:
        instance.config.skip_pip = True
        # The loader mounts the temporary config directory on sys.path.
        monkeypatch.setattr(sys, "path", sys.path.copy())
        loader.async_setup(instance)
        frame.async_setup(instance)
        instance.config_entries = ConfigEntries(instance, {})
        await instance.config_entries.async_initialize()
        dr.async_setup(instance)
        await dr.async_load(instance, load_empty=True)
        await er.async_load(instance, load_empty=True)
        yield instance
    finally:
        await instance.async_stop(force=True)


@pytest_asyncio.fixture
async def calibration(
    hass: HomeAssistant, request: pytest.FixtureRequest,
) -> AsyncIterator[tuple[ConfigEntry, FakeCrestronController, ShadesCoordinator]]:
    entry = ConfigEntry(
        domain=DOMAIN,
        title="Test shades",
        data={},
        options={
            OPT_VISUAL_GROUPS: {
                "version": 1,
                "groups": {GROUP_ID: {"name": "Lounge"}},
                "membership": {SHADE_ID: GROUP_ID},
            }
        } | getattr(request, "param", {}),
        source="user",
        version=1,
        minor_version=1,
        unique_id=None,
        subentries_data=None,
        discovery_keys=MappingProxyType({}),
    )
    # Public async_add also sets up the integration and starts its cover platform.
    hass.config_entries._entries[entry.entry_id] = entry
    controller = FakeCrestronController()
    predictive = PredictiveRuntime(
        learning=LearningManager(defaults={}),
        tau_acc=1.0,
        tau_dec=1.0,
        tau_resp_init=0.15,
        min_confidence_scale=0.25,
        history_size=5,
    )
    calibrations = parse_calibration_options(entry.options)
    coordinator = ShadesCoordinator(
        hass, controller, entry, predictive,
        calibrations, parse_visual_groups(entry.options),
    )
    batcher = ShadeWriteBatcher(
        hass, controller, get_calibrations=lambda: parse_calibration_options(entry.options),
        log_aliases=coordinator.log_aliases,
        on_flush=coordinator.handle_write_flush,
    )
    hass.data[DOMAIN] = {
        entry.entry_id: {
            DATA_CALIBRATIONS: calibrations,
            DATA_PREDICTIVE_MANAGER: predictive,
            DATA_PREDICTIVE_STORAGE: PredictiveStopStore(
                hass, entry_id=entry.entry_id, version=PREDICTIVE_STORAGE_VERSION,
                key_prefix=PREDICTIVE_STORAGE_KEY_PREFIX,
            ),
            DATA_SHADES_COORDINATOR: coordinator,
            DATA_WRITE_BATCHER: batcher,
        }
    }
    try:
        await coordinator.async_refresh()
        yield entry, controller, coordinator
    finally:
        await batcher.async_shutdown()
        await coordinator.async_shutdown()


async def _start_assisted(hass: HomeAssistant, entry: ConfigEntry) -> str:
    options = hass.config_entries.options
    menu = await options.async_init(entry.entry_id)
    assert menu["type"] is FlowResultType.MENU
    flow_id = menu["flow_id"]
    await options.async_configure(flow_id, {"next_step_id": "assisted_calibration"})
    result = await options.async_configure(flow_id, {"group": GROUP_ID, "action": "start"})
    assert result["step_id"] == "assisted_calibration_target"
    return flow_id


async def _record_anchor(
    hass: HomeAssistant,
    flow_id: str,
    controller: FakeCrestronController,
    coordinator: ShadesCoordinator,
    *,
    percent: int,
    raw: int,
    mode: str = "current",
) -> None:
    options = hass.config_entries.options
    stage = await asyncio.wait_for(
        options.async_configure(
            flow_id, {"target_percent": percent, "mode": mode, "action": "stage"},
        ),
        timeout=5,
    )
    assert stage["step_id"] == "assisted_calibration_stage"
    assert not stage["errors"]
    controller.position = raw
    await coordinator.async_refresh()
    result = await options.async_configure(flow_id, {"action": "record"})
    assert result["step_id"] == "assisted_calibration_target"


async def _finish_assisted(hass: HomeAssistant, flow_id: str) -> None:
    options = hass.config_entries.options
    menu = await options.async_configure(flow_id, {"group": GROUP_ID, "action": "back"})
    assert menu["type"] is FlowResultType.MENU
    result = await options.async_configure(flow_id, {"next_step_id": "finish"})
    assert result["type"] is FlowResultType.CREATE_ENTRY


@pytest.mark.asyncio
async def test_setup_logs_room_count_without_controller_details(hass, monkeypatch, caplog):
    class SetupController:
        async def async_get_rooms(self):
            return [{"id": "fictional-room-id", "name": "fictional-room-name"}]

        async def async_logout(self):
            pass

    monkeypatch.setattr(config_flow, "ApiClient", lambda *_args, **_kwargs: SetupController())
    with caplog.at_level(logging.DEBUG, logger="custom_components.crestron_home"):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "user"},
            data={
                CONF_HOST: "fictional-controller.invalid",
                CONF_API_TOKEN: "fictional-setup-token",
            },
        )

    assert result["step_id"] == "confirm"
    assert result["description_placeholders"]["rooms"] == "1"
    assert "Connection test succeeded with rooms=1" in caplog.text
    assert "fictional-" not in caplog.text


@pytest.mark.asyncio
async def test_diagnostics_aliases_link_stop_batch_and_assisted_calibration(
    hass, calibration, caplog,
):
    entry, controller, coordinator = calibration
    hass.config_entries.async_update_entry(
        entry,
        data={CONF_HOST: "fictional-crestron.invalid", CONF_API_TOKEN: "fictional-private-token"},
    )
    other_shade = "fictional-standalone-shade"
    controller.other_shades = [
        {"id": other_shade, "position": 1234, "roomId": "fictional-room"},
        {"name": "fictional-malformed-payload"},
    ]
    with caplog.at_level(logging.DEBUG, logger="custom_components.crestron_home"):
        await coordinator.async_refresh()
        await asyncio.wait_for(
            CrestronHomeShade(coordinator, entry, SHADE_ID).async_stop_cover(), timeout=5,
        )
        flow_id = await _start_assisted(hass, entry)
        await _record_anchor(
            hass, flow_id, controller, coordinator, percent=50, raw=36000, mode="automatic",
        )
    store = hass.data[DOMAIN][entry.entry_id][DATA_PREDICTIVE_STORAGE]
    await store.async_save(
        PredictiveStoreData(
            version=PREDICTIVE_STORAGE_VERSION,
            shades={
                SHADE_ID: {
                    "rls": {
                        "theta0": 0.4, "theta1": 0.1, "cov_00": 12.0, "forgetting": 0.98,
                    },
                    "confidence": 0.3, "tau_resp": 0.12, "sample_count": 9, "rmse": 0.02,
                    "last_updated": "fictional-private-timestamp",
                    "unrecognized": "fictional-stored-extra",
                },
            },
        )
    )
    export = await async_get_config_entry_diagnostics(hass, entry)
    second_export = await async_get_config_entry_diagnostics(hass, entry)
    dumped = json.dumps(export, allow_nan=False)
    for private in (
        '"shade-1"', '"lounge"', "Lounge", "Test shade", other_shade, "fictional-room",
        "fictional-crestron.invalid", "fictional-private-token", "fictional-stored-extra",
        "fictional-private-timestamp", "fictional-malformed-payload", entry.entry_id,
    ):
        assert private not in dumped

    shade_alias, group_alias = next(iter(export["visual_groups"]["membership"].items()))
    assert shade_alias not in second_export["visual_groups"]["membership"]
    assert group_alias not in second_export["visual_groups"]["groups"]
    assert export["shades"][shade_alias]["position"] == 36000
    assert shade_alias in export["learning"]
    assert export["stored_learning"][shade_alias] == {
        "v0": 0.4, "v1": 0.1, "confidence": 0.3,
        "tau_resp": 0.12, "sample_count": 9, "rmse": 0.02,
    }
    plan, = export["plan_events"]
    assert plan["group_id"] == group_alias
    assert plan["targets"][0]["shade_id"] == shade_alias
    stop_batch, stage_batch = export["flush_events"]
    assert stop_batch["groups"] == [{"group_id": group_alias, "shade_ids": [shade_alias]}]
    assert stage_batch["targets"] == [
        {"shade_id": shade_alias, "position": controller.writes[-1][0]["position"]},
    ]
    assisted_run, = export["assisted_calibration_runs"]
    assert assisted_run["group_id"] == group_alias
    assert assisted_run["saved"] == [shade_alias]
    assert assisted_run["target_percent"] == 50
    assert (
        plan["seconds_from_export"] <= stop_batch["seconds_from_export"]
        <= stage_batch["seconds_from_export"] <= assisted_run["seconds_from_export"] <= 0
    )

    log_alias = next(record.batch["ids"][0] for record in caplog.records if hasattr(record, "batch"))
    assert f"Shade {log_alias} applying calibration" in caplog.text
    assert f"saved=['{log_alias}']" in caplog.text
    assert "fictional-malformed-payload" not in caplog.text
    assert not re.search(r"\bshade-1\b|\blounge\b", caplog.text)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("title", "updated"),
    [
        ("Crestron Home (fictional-crestron.invalid)", "Crestron Home"),
        ("My Crestron shades", "My Crestron shades"),
    ],
)
async def test_migration_changes_only_generated_entry_titles(hass, calibration, title, updated):
    entry, _, _ = calibration
    hass.config_entries.async_update_entry(
        entry, title=title, data={CONF_HOST: "fictional-crestron.invalid"},
    )
    assert await async_migrate_entry(hass, entry)
    assert entry.title == updated
    assert entry.minor_version == 2
    assert entry.data[CONF_HOST] == "fictional-crestron.invalid"


@pytest.mark.asyncio
async def test_assisted_calibration_stages_move_and_saves_only_at_finish(hass, calibration):
    entry, controller, coordinator = calibration
    flow_id = await _start_assisted(hass, entry)
    await _record_anchor(
        hass, flow_id, controller, coordinator, percent=50, raw=36000, mode="automatic",
    )
    assert controller.writes == [[{"id": SHADE_ID, "position": 32768}]]
    assert OPT_CALIBRATION not in entry.options

    await hass.config_entries.options.async_configure(flow_id, {"action": "back"})
    await _finish_assisted(hass, flow_id)
    assert entry.options[OPT_CALIBRATION][SHADE_ID]["anchors"] == [
        {"pc": 0, "raw": 0},
        {"pc": 50, "raw": 36000},
        {"pc": 100, "raw": 65535},
    ]


@pytest.mark.asyncio
async def test_abandoning_assisted_calibration_discards_recorded_anchor(hass, calibration):
    entry, controller, coordinator = calibration
    original_options = dict(entry.options)
    flow_id = await _start_assisted(hass, entry)
    await _record_anchor(hass, flow_id, controller, coordinator, percent=50, raw=36000)
    assert not controller.writes

    hass.config_entries.options.async_abort(flow_id)
    assert entry.options == original_options


@pytest.mark.asyncio
async def test_assisted_undo_keeps_earlier_recording_after_finish(hass, calibration):
    entry, controller, coordinator = calibration
    flow_id = await _start_assisted(hass, entry)
    await _record_anchor(hass, flow_id, controller, coordinator, percent=40, raw=28000)
    await _record_anchor(hass, flow_id, controller, coordinator, percent=60, raw=41000)

    options = hass.config_entries.options
    await options.async_configure(flow_id, {"action": "back"})
    undo = await options.async_configure(flow_id, {"group": GROUP_ID, "action": "undo"})
    assert not undo["errors"]
    await _finish_assisted(hass, flow_id)
    assert entry.options[OPT_CALIBRATION][SHADE_ID]["anchors"] == [
        {"pc": 0, "raw": 0},
        {"pc": 40, "raw": 28000},
        {"pc": 100, "raw": 65535},
    ]


async def _open_manual_editor(hass: HomeAssistant, entry: ConfigEntry) -> ConfigFlowResult:
    options = hass.config_entries.options
    menu = await options.async_init(entry.entry_id)
    flow_id = menu["flow_id"]
    picker = await options.async_configure(flow_id, {"next_step_id": "select_shade"})
    assert picker["step_id"] == "select_shade"
    editor = await options.async_configure(flow_id, {"shade": SHADE_ID})
    assert editor["step_id"] == "edit_shade"
    return editor


async def _submit_manual_anchor(hass: HomeAssistant, flow_id: str, *, action: str) -> None:
    options = hass.config_entries.options
    editor = await options.async_configure(flow_id, {"action": "add"})
    assert editor["step_id"] == "edit_shade"
    result = await options.async_configure(flow_id, {"raw_1": 36000, "action": action})
    assert result["step_id"] == "select_shade"


async def _finish_manual(hass: HomeAssistant, flow_id: str) -> None:
    options = hass.config_entries.options
    menu = await options.async_configure(flow_id, {"action": "back"})
    assert menu["type"] is FlowResultType.MENU
    result = await options.async_configure(flow_id, {"next_step_id": "finish"})
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def _open_group_assignment(hass: HomeAssistant, entry: ConfigEntry) -> ConfigFlowResult:
    options = hass.config_entries.options
    menu = await options.async_init(entry.entry_id)
    flow_id = menu["flow_id"]
    await options.async_configure(flow_id, {"next_step_id": "visual_groups"})
    form = await options.async_configure(flow_id, {"next_step_id": "visual_groups_assign"})
    assert form["step_id"] == "visual_groups_assign"
    return form


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "calibration",
    [{
        OPT_VISUAL_GROUPS: {
            "version": 1,
            "groups": {GROUP_ID: {"name": "Lounge"}, "study": {"name": "Study"}},
            "membership": {SHADE_ID: GROUP_ID},
        },
    }],
    indirect=True,
)
async def test_visual_group_assignment_labels_distinct_shades_and_preserves_ids(hass, calibration):
    entry, controller, coordinator = calibration
    controller.other_shades.extend([
        {"id": "shade-2", "name": "South shade", "position": 0, "connectionStatus": "connected"},
        {"id": "shade-3", "name": "South shade", "position": 0, "connectionStatus": "connected"},
        {"id": "shade-4", "name": "", "position": 0, "connectionStatus": "connected"},
    ])
    await coordinator.async_refresh()
    registry = er.async_get(hass)
    entity = registry.async_get_or_create(
        "cover", DOMAIN, f"shade:{entry.entry_id.lower()}:{SHADE_ID}",
        suggested_object_id="test_shade", config_entry=entry,
    )
    registry.async_update_entity(entity.entity_id, name="Window seat")

    options = hass.config_entries.options
    form = await _open_group_assignment(hass, entry)
    fields = to_field_list(form["data_schema"], custom_serializer=custom_serializer)
    assert {field["name"] for field in fields} == {
        "Group for Window seat",
        "Group for South shade (shade-2)",
        "Group for South shade (shade-3)",
        "Group for Shade shade-4",
    }
    assert all("select" in field["selector"] for field in fields)

    # A name change between rendering and submission must not remap the field.
    registry.async_update_entity(entity.entity_id, name="Window shade")
    flow_id = form["flow_id"]
    menu = await options.async_configure(flow_id, {
        "Group for Window seat": "study",
        "Group for South shade (shade-2)": GROUP_ID,
    })
    assert menu["step_id"] == "visual_groups"
    assert entry.options[OPT_VISUAL_GROUPS]["membership"] == {SHADE_ID: GROUP_ID}
    await options.async_configure(flow_id, {"next_step_id": "visual_groups_back"})
    result = await options.async_configure(flow_id, {"next_step_id": "finish"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[OPT_VISUAL_GROUPS]["membership"] == {
        SHADE_ID: "study", "shade-2": GROUP_ID,
    }

    reopened = await _open_group_assignment(hass, entry)
    fields = to_field_list(reopened["data_schema"], custom_serializer=custom_serializer)
    defaults = {field["name"]: field["default"] for field in fields}
    assert "Group for Window seat" not in defaults
    assert defaults["Group for Window shade"] == "study"
    assert defaults["Group for South shade (shade-2)"] == GROUP_ID
    assert defaults["Group for South shade (shade-3)"] != GROUP_ID
    options.async_abort(reopened["flow_id"])


async def _save_shade_minimum(hass: HomeAssistant, entry: ConfigEntry, minimum: int) -> None:
    editor = await _open_manual_editor(hass, entry)
    flow_id = editor["flow_id"]
    options = hass.config_entries.options
    picker = await options.async_configure(
        flow_id, {"minimum_position": minimum, "action": "save"},
    )
    assert picker["step_id"] == "select_shade"
    await _finish_manual(hass, flow_id)


@pytest.mark.asyncio
async def test_stale_options_save_preserves_newer_minimum(hass, calibration):
    entry, controller, coordinator = calibration
    options = hass.config_entries.options
    earlier = await options.async_init(entry.entry_id)
    flow_id = earlier["flow_id"]
    await options.async_configure(flow_id, {"next_step_id": "predictive_stop"})
    await options.async_configure(flow_id, {OPT_PREDICTIVE_STOP: False})
    await _save_shade_minimum(hass, entry, 10)

    result = await options.async_configure(flow_id, {"next_step_id": "finish"})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "options_changed"
    assert entry.options[OPT_MINIMUM_POSITIONS] == {SHADE_ID: 10}
    assert entry.options[OPT_PREDICTIVE_STOP] is True
    shade = CrestronHomeShade(coordinator, entry, SHADE_ID)
    await asyncio.wait_for(shade.async_close_cover(), timeout=5)
    assert controller.writes == [[{"id": SHADE_ID, "position": 6554}]]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "calibration",
    [{
        CONF_INVERT: False,
        OPT_CALIBRATION: {SHADE_ID: {
            "anchors": [[0, 0], [20, 10000], [100, 10000]],
        }},
    }],
    indirect=True,
)
async def test_assisted_undo_preserves_curve_needed_by_pending_minimum(hass, calibration):
    entry, controller, coordinator = calibration
    options = hass.config_entries.options
    flow_id = await _start_assisted(hass, entry)
    await _record_anchor(hass, flow_id, controller, coordinator, percent=20, raw=8000)
    await options.async_configure(flow_id, {"action": "back"})
    await options.async_configure(flow_id, {"group": GROUP_ID, "action": "back"})
    await options.async_configure(flow_id, {"next_step_id": "select_shade"})
    await options.async_configure(flow_id, {"shade": SHADE_ID})
    saved = await options.async_configure(flow_id, {"minimum_position": 40, "action": "save"})
    assert saved["step_id"] == "select_shade"
    await options.async_configure(flow_id, {"action": "back"})
    await options.async_configure(flow_id, {"next_step_id": "assisted_calibration"})

    undo = await options.async_configure(flow_id, {"group": GROUP_ID, "action": "undo"})
    assert undo["errors"] == {"base": "minimum_position_unreachable"}
    await _finish_assisted(hass, flow_id)
    assert entry.options[OPT_MINIMUM_POSITIONS] == {SHADE_ID: 40}
    assert entry.options[OPT_CALIBRATION][SHADE_ID]["anchors"] == [
        {"pc": 0, "raw": 0}, {"pc": 20, "raw": 8000}, {"pc": 100, "raw": 10000},
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "calibration",
    [{
        OPT_VISUAL_GROUPS: {
            "version": 1,
            "groups": {GROUP_ID: {"name": "Lounge"}},
            "membership": {SHADE_ID: GROUP_ID, "shade-2": GROUP_ID},
        },
    }],
    indirect=True,
)
async def test_assisted_move_skips_anchor_when_minimum_changes_in_queue(
    hass, calibration, monkeypatch,
):
    entry, controller, coordinator = calibration
    controller.position = 4200
    controller.other_shades.append({
        "id": "shade-2", "name": "Second shade", "position": 4300,
        "connectionStatus": "connected",
    })
    await coordinator.async_refresh()
    flow_id = await _start_assisted(hass, entry)
    options = hass.config_entries.options
    batcher = hass.data[DOMAIN][entry.entry_id][DATA_WRITE_BATCHER]
    queued = asyncio.Event()

    # Hold the batching timer so the second dialog can save before dispatch.
    with monkeypatch.context() as hold:
        hold.setattr(batcher, "_schedule_timer", lambda **_kwargs: queued.set())
        move = asyncio.create_task(options.async_configure(
            flow_id, {"target_percent": 5, "mode": "automatic", "action": "stage"},
        ))
        try:
            await asyncio.wait_for(queued.wait(), timeout=5)
            await _save_shade_minimum(hass, entry, 10)
            await asyncio.wait_for(batcher.async_flush(), timeout=5)
            stage = await asyncio.wait_for(move, timeout=5)
        finally:
            if not move.done():
                move.cancel()
                await asyncio.wait_for(
                    asyncio.gather(move, return_exceptions=True), timeout=5,
                )

    assert stage["errors"] == {"base": "assisted_stage_failed"}
    assert "minimum position changed" in stage["description_placeholders"]["warnings"]
    assert controller.writes == [[{"id": "shade-2", "position": 3277}]]
    result = await options.async_configure(flow_id, {"action": "record"})
    assert "skipped Test shade" in result["description_placeholders"]["status"]
    assert coordinator.assisted_history[-1]["saved"] == ["shade-2"]
    assert coordinator.assisted_history[-1]["skipped"] == [SHADE_ID]
    options.async_abort(flow_id)
    assert entry.options[OPT_MINIMUM_POSITIONS] == {SHADE_ID: 10}
    assert OPT_CALIBRATION not in entry.options


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "calibration",
    [{
        CONF_INVERT: False,
        OPT_CALIBRATION: {SHADE_ID: {
            "anchors": [[0, 0], [20, 10000], [60, 10000], [100, 65535]],
        }},
    }],
    indirect=True,
)
async def test_close_target_reports_above_minimum_inside_flat_span(hass, calibration):
    entry, controller, coordinator = calibration
    await _save_shade_minimum(hass, entry, 40)
    shade = CrestronHomeShade(coordinator, entry, SHADE_ID)

    await asyncio.wait_for(shade.async_close_cover(), timeout=5)
    assert controller.writes == [[{"id": SHADE_ID, "position": 10001}]]
    controller.position = 10001
    await coordinator.async_refresh()
    assert shade.current_cover_position == 60


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "calibration",
    [{
        CONF_INVERT: False,
        OPT_CALIBRATION: {SHADE_ID: {
            "anchors": [[0, 0], [20, 10000], [100, 10000]],
        }},
    }],
    indirect=True,
)
async def test_editor_rejects_minimum_above_calibrated_travel(hass, calibration):
    entry, controller, _ = calibration
    editor = await _open_manual_editor(hass, entry)
    options = hass.config_entries.options
    flow_id = editor["flow_id"]
    result = await options.async_configure(
        flow_id, {"minimum_position": 40, "action": "save"},
    )
    assert result["step_id"] == "edit_shade"
    assert result["errors"] == {"base": "minimum_position_unreachable"}
    assert OPT_MINIMUM_POSITIONS not in entry.options
    assert not controller.writes
    options.async_abort(flow_id)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "calibration",
    [{
        CONF_INVERT: False,
        OPT_CALIBRATION: {SHADE_ID: {
            "anchors": [[0, 10000], [40, 10000], [100, 65535]],
        }},
        OPT_MINIMUM_POSITIONS: {SHADE_ID: 90},
    }],
    indirect=True,
)
async def test_global_invert_rejects_unreachable_minimum(hass, calibration):
    entry, _, _ = calibration
    options = hass.config_entries.options
    menu = await options.async_init(entry.entry_id)
    flow_id = menu["flow_id"]
    await options.async_configure(flow_id, {"next_step_id": "global_defaults"})
    result = await options.async_configure(flow_id, {CONF_INVERT: True})
    assert result["step_id"] == "global_defaults"
    assert result["errors"] == {CONF_INVERT: "minimum_position_unreachable"}
    assert entry.options[CONF_INVERT] is False
    options.async_abort(flow_id)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("calibration", "raw_minimum", "raw_quarter", "raw_closed", "other_closed"),
    [
        ({CONF_INVERT: False}, 6554, 16384, 0, 0),
        ({CONF_INVERT: True}, 58981, 49151, 65535, 65535),
        (
            {CONF_INVERT: False, OPT_CALIBRATION: {SHADE_ID: {
                "anchors": [[0, 1000], [20, 5001], [100, 65000]],
            }}},
            3001, 8751, 1000, 0,
        ),
    ],
    indirect=["calibration"],
    ids=["normal", "inverted", "calibrated"],
)
async def test_minimum_limits_each_shade_in_a_batch_and_can_be_cleared(
    hass, calibration, raw_minimum, raw_quarter, raw_closed, other_closed,
):
    entry, controller, coordinator = calibration
    controller.other_shades.append({
        "id": "shade-2", "name": "Second shade", "position": other_closed,
        "connectionStatus": "connected",
    })
    await coordinator.async_refresh()
    await _save_shade_minimum(hass, entry, 10)
    assert entry.options[OPT_MINIMUM_POSITIONS] == {SHADE_ID: 10}
    reopened = await _open_manual_editor(hass, entry)
    assert reopened["data_schema"]({})["minimum_position"] == 10
    hass.config_entries.options.async_abort(reopened["flow_id"])

    shade = CrestronHomeShade(coordinator, entry, SHADE_ID)
    other_shade = CrestronHomeShade(coordinator, entry, "shade-2")
    await asyncio.wait_for(
        asyncio.gather(shade.async_close_cover(), other_shade.async_close_cover()),
        timeout=5,
    )
    assert len(controller.writes) == 1
    assert {item["id"]: item["position"] for item in controller.writes[0]} == {
        SHADE_ID: raw_minimum, "shade-2": other_closed,
    }

    for percentage, expected in ((5, raw_minimum), (10, raw_minimum), (25, raw_quarter)):
        await asyncio.wait_for(shade.async_set_cover_position(position=percentage), timeout=5)
        assert controller.writes[-1] == [{"id": SHADE_ID, "position": expected}]

    await _save_shade_minimum(hass, entry, 0)
    assert OPT_MINIMUM_POSITIONS not in entry.options
    await asyncio.wait_for(shade.async_close_cover(), timeout=5)
    assert controller.writes[-1] == [{"id": SHADE_ID, "position": raw_closed}]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "calibration", [{OPT_MINIMUM_POSITIONS: {SHADE_ID: 10}}], indirect=True,
)
@pytest.mark.parametrize("predictive_enabled", [False, True], ids=["direct", "predictive"])
async def test_stop_below_minimum_sends_the_minimum(hass, calibration, predictive_enabled):
    entry, controller, coordinator = calibration
    controller.position = 3277  # About 5% open.
    await coordinator.async_refresh()
    runtime = coordinator.predictive
    runtime.enabled = predictive_enabled
    if predictive_enabled:
        now = time.monotonic()
        runtime.record_poll(SHADE_ID, timestamp=now - 0.05, position=0.04)
        runtime.record_poll(SHADE_ID, timestamp=now, position=0.05)
        plan = runtime.plan_stop([SHADE_ID], timestamp=now)
        assert plan.targets[0].position > 0.10

    shade = CrestronHomeShade(coordinator, entry, SHADE_ID)
    await asyncio.wait_for(shade.async_stop_cover(), timeout=5)
    assert controller.writes == [[{"id": SHADE_ID, "position": 6554}]]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "calibration", [{OPT_MINIMUM_POSITIONS: {SHADE_ID: 10}}], indirect=True,
)
async def test_assisted_calibration_skips_moves_and_anchors_below_minimum(hass, calibration):
    entry, controller, coordinator = calibration
    controller.position = 4200
    await coordinator.async_refresh()
    flow_id = await _start_assisted(hass, entry)
    options = hass.config_entries.options
    stage = await asyncio.wait_for(
        options.async_configure(
            flow_id, {"target_percent": 5, "mode": "automatic", "action": "stage"},
        ),
        timeout=5,
    )
    assert "below its minimum position" in stage["description_placeholders"]["warnings"]
    assert not controller.writes

    result = await options.async_configure(flow_id, {"action": "record"})
    assert "skipped Test shade" in result["description_placeholders"]["status"]
    await options.async_configure(flow_id, {"action": "back"})
    await _finish_assisted(hass, flow_id)
    assert OPT_CALIBRATION not in entry.options


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "calibration", [{OPT_MINIMUM_POSITIONS: {SHADE_ID: 10}}], indirect=True,
)
@pytest.mark.parametrize(
    ("mode", "reconnect"),
    [("automatic", False), ("automatic", True), ("current", False)],
    ids=["automatic-offline", "automatic-reconnected", "from-current-location"],
)
async def test_offline_assisted_shade_records_only_from_current_location(
    hass, calibration, mode, reconnect,
):
    entry, controller, coordinator = calibration
    controller.position = 1000
    controller.connection_status = "offline"
    await coordinator.async_refresh()
    flow_id = await _start_assisted(hass, entry)
    options = hass.config_entries.options
    stage = await asyncio.wait_for(
        options.async_configure(
            flow_id, {"target_percent": 5, "mode": mode, "action": "stage"},
        ),
        timeout=5,
    )
    assert "offline" in stage["description_placeholders"]["warnings"]
    assert not controller.writes
    if reconnect:
        controller.connection_status = "connected"
        await coordinator.async_refresh()

    result = await options.async_configure(flow_id, {"action": "record"})
    await options.async_configure(flow_id, {"action": "back"})
    await _finish_assisted(hass, flow_id)
    assert entry.options[OPT_MINIMUM_POSITIONS] == {SHADE_ID: 10}
    status = result["description_placeholders"]["status"]
    if mode == "automatic":
        assert "skipped Test shade" in status
        assert OPT_CALIBRATION not in entry.options
    else:
        assert "saved Test shade" in status
        assert entry.options[OPT_CALIBRATION][SHADE_ID]["anchors"][1] == {
            "pc": 5, "raw": 1000,
        }


@pytest.mark.asyncio
async def test_calibration_picker_uses_renamed_entity_and_keeps_shade_identity(hass, calibration):
    entry, _, _ = calibration
    registry = er.async_get(hass)
    entity = registry.async_get_or_create(
        "cover", DOMAIN, f"shade:{entry.entry_id.lower()}:{SHADE_ID}",
        suggested_object_id="test_shade", original_name="Test shade", config_entry=entry,
    )
    options = hass.config_entries.options
    menu = await options.async_init(entry.entry_id)
    flow_id = menu["flow_id"]
    picker = await options.async_configure(flow_id, {"next_step_id": "select_shade"})
    assert picker["data_schema"].schema["shade"].config["options"] == [
        {"value": SHADE_ID, "label": "Test shade (shade-1)"}
    ]
    options.async_abort(flow_id)

    registry.async_update_entity(entity.entity_id, name="Reading nook")
    menu = await options.async_init(entry.entry_id)
    flow_id = menu["flow_id"]
    picker = await options.async_configure(flow_id, {"next_step_id": "select_shade"})
    picked, = picker["data_schema"].schema["shade"].config["options"]
    assert picked == {"value": SHADE_ID, "label": "Reading nook (shade-1)"}
    editor = await options.async_configure(flow_id, {"shade": picked["value"]})
    assert editor["step_id"] == "edit_shade"
    await _submit_manual_anchor(hass, flow_id, action="save")
    await _finish_manual(hass, flow_id)
    assert entry.options[OPT_CALIBRATION][SHADE_ID]["anchors"][1] == {"pc": 50, "raw": 36000}


@pytest.mark.asyncio
async def test_manual_calibration_saves_at_finish_and_reopens_with_saved_curve(hass, calibration):
    entry, _, _ = calibration
    editor = await _open_manual_editor(hass, entry)
    flow_id = editor["flow_id"]
    await _submit_manual_anchor(hass, flow_id, action="save")
    assert OPT_CALIBRATION not in entry.options

    await _finish_manual(hass, flow_id)
    assert entry.options[OPT_CALIBRATION][SHADE_ID]["anchors"] == [
        {"pc": 0, "raw": 0},
        {"pc": 50, "raw": 36000},
        {"pc": 100, "raw": 65535},
    ]

    reopened = await _open_manual_editor(hass, entry)
    assert reopened["data_schema"]({})["raw_1"] == 36000
    hass.config_entries.options.async_abort(reopened["flow_id"])


@pytest.mark.asyncio
async def test_closing_manual_calibration_discards_pending_curve(hass, calibration):
    entry, _, _ = calibration
    original_options = dict(entry.options)
    editor = await _open_manual_editor(hass, entry)
    flow_id = editor["flow_id"]
    await _submit_manual_anchor(hass, flow_id, action="save")

    hass.config_entries.options.async_abort(flow_id)
    assert entry.options == original_options


@pytest.mark.asyncio
async def test_manual_editor_back_discards_current_edit_before_finish(hass, calibration):
    entry, _, _ = calibration
    editor = await _open_manual_editor(hass, entry)
    flow_id = editor["flow_id"]
    await _submit_manual_anchor(hass, flow_id, action="cancel")
    await _finish_manual(hass, flow_id)

    assert OPT_CALIBRATION not in entry.options
