"""Unit tests for Crestron Home calibration helpers."""

from __future__ import annotations

import pytest

from home_assistant_stubs import home_assistant_stubs

with home_assistant_stubs():
    from custom_components.crestron_home.calibration import (
        DEFAULT_ANCHORS,
        InvalidCalibrationError,
        pct_to_raw,
        raw_to_pct,
        validate_anchors,
    )
    from custom_components.crestron_home.const import (
        CAL_ANCHOR_RAW_MAX,
        ERR_ANCHORS_PC_ORDER,
        ERR_ANCHORS_RAW_MONOTONIC,
        ERR_ANCHORS_TOO_FEW,
    )


def test_pct_to_raw_default_mapping() -> None:
    """Default anchors should provide linear mapping across the range."""

    assert pct_to_raw(23, DEFAULT_ANCHORS, False) == 15073
    assert pct_to_raw(-5, DEFAULT_ANCHORS, False) == 0
    assert pct_to_raw(120, DEFAULT_ANCHORS, False) == CAL_ANCHOR_RAW_MAX


def test_raw_to_pct_default_mapping() -> None:
    """Default anchors should map raw values back to percentages."""

    raw_value = pct_to_raw(40, DEFAULT_ANCHORS, False)
    assert raw_to_pct(raw_value, DEFAULT_ANCHORS, False) == 40
    assert raw_to_pct(None, DEFAULT_ANCHORS, False) is None


def test_pct_to_raw_invert_axis() -> None:
    """Inverting the axis should mirror the output."""

    assert pct_to_raw(10, DEFAULT_ANCHORS, True) == pct_to_raw(90, DEFAULT_ANCHORS, False)


def test_raw_to_pct_flat_segment() -> None:
    """Flat raw spans should snap to the higher percentage anchor."""

    anchors = validate_anchors(
        [
            {"pc": 0, "raw": 0},
            {"pc": 40, "raw": 0},
            {"pc": 100, "raw": CAL_ANCHOR_RAW_MAX},
        ]
    )
    assert raw_to_pct(0, anchors, False) == 40
    assert raw_to_pct(10, anchors, True) == 60


def test_validate_anchors_errors() -> None:
    """Validation should reject insufficient, unsorted, or decreasing anchors."""

    with pytest.raises(InvalidCalibrationError) as too_few:
        validate_anchors([{"pc": 0, "raw": 0}])
    assert too_few.value.code == ERR_ANCHORS_TOO_FEW

    with pytest.raises(InvalidCalibrationError) as unsorted:
        validate_anchors(
            [
                {"pc": 0, "raw": 0},
                {"pc": 0, "raw": 100},
                {"pc": 100, "raw": CAL_ANCHOR_RAW_MAX},
            ]
        )
    assert unsorted.value.code == ERR_ANCHORS_PC_ORDER

    with pytest.raises(InvalidCalibrationError) as decreasing:
        validate_anchors(
            [
                {"pc": 0, "raw": 0},
                {"pc": 40, "raw": 30000},
                {"pc": 100, "raw": 20000},
            ]
        )
    assert decreasing.value.code == ERR_ANCHORS_RAW_MONOTONIC


def test_round_trip_custom_curve() -> None:
    """Custom curves should remain consistent when converting both directions."""

    anchors = validate_anchors(
        [
            {"pc": 0, "raw": 0},
            {"pc": 30, "raw": 12000},
            {"pc": 60, "raw": 40000},
            {"pc": 100, "raw": CAL_ANCHOR_RAW_MAX},
        ]
    )
    raw_value = pct_to_raw(23, anchors, False)
    assert raw_value == 9200
    assert raw_to_pct(raw_value, anchors, False) == 23

