from collections import deque
from datetime import UTC, datetime

import pytest

from custom_components.crestron_home import coordinator as coordinator_module
from custom_components.crestron_home.predictive_stop import PlanResult, ShadeStopTarget
from custom_components.crestron_home.coordinator import StopPlanGroup, ShadesCoordinator
from custom_components.crestron_home.visual_groups import (
    IMPLICIT_GROUP_ID,
    STANDALONE_PREFIX,
    VISUAL_GROUPS_VERSION,
    VisualGroupEntry,
    VisualGroupsConfig,
    parse_visual_groups,
    update_visual_groups_option,
)


def _make_config(groups=None, membership=None):
    return VisualGroupsConfig(
        version=VISUAL_GROUPS_VERSION,
        groups=groups or {},
        membership=membership or {},
    )


def test_partition_implicit_group() -> None:
    config = _make_config()
    partitions, invalid = config.partition_shades(["a", "b"])
    assert list(partitions.keys()) == [IMPLICIT_GROUP_ID]
    assert partitions[IMPLICIT_GROUP_ID] == ["a", "b"]
    assert not invalid


def test_partition_explicit_groups() -> None:
    config = _make_config(
        groups={
            "left": VisualGroupEntry(name="Left"),
            "right": VisualGroupEntry(name="Right"),
        },
        membership={"shade1": "left", "shade3": "right"},
    )
    partitions, invalid = config.partition_shades(["shade1", "shade2", "shade3"])
    assert list(partitions.keys()) == ["left", f"{STANDALONE_PREFIX}shade2", "right"]
    assert partitions["left"] == ["shade1"]
    assert partitions[f"{STANDALONE_PREFIX}shade2"] == ["shade2"]
    assert partitions["right"] == ["shade3"]
    assert not invalid


def test_partition_invalid_membership() -> None:
    config = _make_config(membership={"shade1": "missing"})
    partitions, invalid = config.partition_shades(["shade1"])
    assert list(partitions.keys()) == [f"{STANDALONE_PREFIX}shade1"]
    assert invalid == {"missing"}


def test_update_visual_groups_option_roundtrip() -> None:
    config = _make_config(
        groups={"group_1": VisualGroupEntry(name="Group 1")},
        membership={"shade1": "group_1"},
    )
    options: dict[str, object] = {}
    update_visual_groups_option(options, config)
    restored = parse_visual_groups(options)
    assert restored.groups["group_1"].name == "Group 1"
    assert restored.membership == {"shade1": "group_1"}


def test_update_visual_groups_option_removes_when_empty() -> None:
    options = {"visual_groups": {"groups": {}, "membership": {}}}
    update_visual_groups_option(options, _make_config())
    assert "visual_groups" not in options


class _PredictiveStub:
    def __init__(self, flush=True) -> None:
        self.calls: list[list[str]] = []
        self.flush = flush

    def plan_stop(self, shade_ids, *, timestamp):
        self.calls.append(list(shade_ids))
        targets = [
            ShadeStopTarget(shade_id=shade_id, position=0.5, clamped=False, distance=0.1)
            for shade_id in shade_ids
        ]
        return PlanResult(targets=targets, flush=self.flush)


def _make_coordinator(config: VisualGroupsConfig, predictive: _PredictiveStub) -> ShadesCoordinator:
    coordinator = object.__new__(ShadesCoordinator)
    coordinator._predictive = predictive
    coordinator._visual_groups = config
    coordinator._plan_history = deque(maxlen=20)
    coordinator._flush_history = deque(maxlen=20)
    return coordinator


def test_plan_stop_single_group() -> None:
    predictive = _PredictiveStub()
    coordinator = _make_coordinator(_make_config(), predictive)
    groups = coordinator.plan_stop(["shade1", "shade2"])
    assert predictive.calls == [["shade1", "shade2"]]
    assert len(groups) == 1
    assert isinstance(groups[0], StopPlanGroup)
    assert groups[0].shade_ids == ["shade1", "shade2"]
    assert groups[0].plan.targets[0].shade_id == "shade1"


def test_plan_stop_multiple_groups() -> None:
    config = _make_config(
        groups={
            "group_a": VisualGroupEntry(name="Group A"),
            "group_b": VisualGroupEntry(name="Group B"),
        },
        membership={"shade1": "group_a", "shade3": "group_b"},
    )
    predictive = _PredictiveStub(flush=False)
    coordinator = _make_coordinator(config, predictive)
    groups = coordinator.plan_stop(["shade1", "shade2", "shade3"])
    assert predictive.calls == [["shade1"], ["shade2"], ["shade3"]]
    assert [group.group_id for group in groups] == ["group_a", f"{STANDALONE_PREFIX}shade2", "group_b"]


def test_plan_stop_invalid_group_logs(caplog: pytest.LogCaptureFixture) -> None:
    config = _make_config(membership={"shade1": "ghost"})
    predictive = _PredictiveStub()
    coordinator = _make_coordinator(config, predictive)
    with caplog.at_level("WARNING"):
        coordinator.plan_stop(["shade1"])
    assert any("ghost" in record.message for record in caplog.records)


def test_handle_write_flush_records_groups() -> None:
    config = _make_config(
        groups={"group_a": VisualGroupEntry(name="Group A")},
        membership={"shade1": "group_a"},
    )
    coordinator = _make_coordinator(config, _PredictiveStub())
    coordinator.handle_write_flush(
        [
            {"id": "shade1", "position": 1000},
            {"id": "shade2", "position": 2000},
        ],
        "success",
    )
    assert len(coordinator.flush_history) == 1
    entry = coordinator.flush_history[0]
    assert entry["status"] == "success"
    assert any(group["group_id"] == "group_a" for group in entry["groups"])
    assert any(
        group["group_id"] == f"{STANDALONE_PREFIX}shade2" for group in entry["groups"]
    )
coordinator_module.utcnow = lambda: datetime.now(UTC)

