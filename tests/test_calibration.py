"""Unit tests for Crestron Home calibration helpers."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import types
import sys

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = PROJECT_ROOT / "custom_components" / "crestron_home"
PACKAGE_NAME = "custom_components.crestron_home"

if "custom_components" not in sys.modules:
    custom_components_pkg = types.ModuleType("custom_components")
    custom_components_pkg.__path__ = [str(PROJECT_ROOT / "custom_components")]
    sys.modules["custom_components"] = custom_components_pkg

if PACKAGE_NAME not in sys.modules:
    crestron_home_pkg = types.ModuleType(PACKAGE_NAME)
    crestron_home_pkg.__path__ = [str(PACKAGE_ROOT)]
    sys.modules[PACKAGE_NAME] = crestron_home_pkg

calibration_spec = importlib.util.spec_from_file_location(
    f"{PACKAGE_NAME}.calibration", PACKAGE_ROOT / "calibration.py"
)
calibration = importlib.util.module_from_spec(calibration_spec)
assert calibration_spec and calibration_spec.loader
sys.modules[calibration_spec.name] = calibration
calibration_spec.loader.exec_module(calibration)

const_spec = importlib.util.spec_from_file_location(
    f"{PACKAGE_NAME}.const", PACKAGE_ROOT / "const.py"
)
const = importlib.util.module_from_spec(const_spec)
assert const_spec and const_spec.loader
sys.modules[const_spec.name] = const
const_spec.loader.exec_module(const)

DEFAULT_ANCHORS = calibration.DEFAULT_ANCHORS
InvalidCalibrationError = calibration.InvalidCalibrationError
pct_to_raw = calibration.pct_to_raw
raw_to_pct = calibration.raw_to_pct
validate_anchors = calibration.validate_anchors

CAL_ANCHOR_RAW_MAX = const.CAL_ANCHOR_RAW_MAX
ERR_ANCHORS_PC_ORDER = const.ERR_ANCHORS_PC_ORDER
ERR_ANCHORS_RAW_MONOTONIC = const.ERR_ANCHORS_RAW_MONOTONIC
ERR_ANCHORS_TOO_FEW = const.ERR_ANCHORS_TOO_FEW


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

