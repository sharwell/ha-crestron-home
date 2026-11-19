from datetime import datetime, timezone

import pytest

from home_assistant_stubs import home_assistant_stubs

with home_assistant_stubs():
    from custom_components.crestron_home.assisted_calibration import (
        AssistedCalibrationRun,
        apply_assisted_anchor,
        largest_gap_target,
    )
    from custom_components.crestron_home.calibration import ShadeCalibration


def test_largest_gap_default_endpoints() -> None:
    """With only 0% and 100% anchors the midpoint should be selected."""

    calibration = ShadeCalibration()
    assert largest_gap_target([calibration]) == 50


def test_largest_gap_union_midpoint() -> None:
    """Mixed anchors should pick the midpoint of the largest combined gap."""

    group_a = ShadeCalibration(anchors=((0, 0), (20, 2000), (100, 65535)))
    group_b = ShadeCalibration(anchors=((0, 0), (60, 4000), (100, 65535)))

    assert largest_gap_target([group_a, group_b]) == 40


def test_apply_assisted_anchor_skips_unchanged() -> None:
    """Raw differences inside the epsilon should not modify the curve."""

    calibration = ShadeCalibration(anchors=((0, 0), (50, 3000), (100, 65535)))
    anchors, changed = apply_assisted_anchor(calibration, 50, 3002)

    assert not changed
    assert anchors == calibration.anchors


def test_apply_assisted_anchor_inserts() -> None:
    """New anchors should be inserted when outside existing percent slots."""

    calibration = ShadeCalibration(anchors=((0, 0), (100, 65535)))
    anchors, changed = apply_assisted_anchor(calibration, 40, 2000)

    assert changed
    assert (40, 2000) in anchors


def test_assisted_run_diagnostics_payload() -> None:
    """Runs should serialize into diagnostics-friendly dictionaries."""

    timestamp = datetime(2024, 1, 1, tzinfo=timezone.utc)
    run = AssistedCalibrationRun(
        group_id="group-1",
        target_percent=55,
        saved=("shade-1", "shade-2"),
        skipped=("shade-3",),
        timestamp=timestamp,
    )

    payload = run.as_diagnostics()
    assert payload == {
        "group_id": "group-1",
        "target_percent": 55,
        "saved": ["shade-1", "shade-2"],
        "skipped": ["shade-3"],
        "timestamp": timestamp.isoformat(),
    }


@pytest.mark.asyncio
async def test_coordinator_records_assisted_runs(make_coordinator) -> None:
    """Coordinator history should expose assisted calibration runs."""
    from custom_components.crestron_home.assisted_calibration import AssistedCalibrationRun

    coordinator = make_coordinator()
    timestamp = datetime(2024, 2, 2, tzinfo=timezone.utc)
    run = AssistedCalibrationRun(
        group_id="group-2",
        target_percent=42,
        saved=("shade-9",),
        skipped=(),
        timestamp=timestamp,
    )

    coordinator.record_assisted_calibration(run)

    assert coordinator.assisted_history == [run.as_diagnostics()]
