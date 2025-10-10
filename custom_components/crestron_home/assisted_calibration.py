"""Helpers for the assisted calibration wizard."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Sequence

from .calibration import ShadeCalibration, validate_anchors

__all__ = [
    "ASSISTED_PERCENT_EPSILON",
    "ASSISTED_RAW_EPSILON",
    "AssistedCalibrationRun",
    "apply_assisted_anchor",
    "largest_gap_target",
]

ASSISTED_PERCENT_EPSILON = 1
ASSISTED_RAW_EPSILON = 4


def _normalized_percent_points(
    calibrations: Iterable[ShadeCalibration],
    *,
    epsilon: int,
) -> list[int]:
    """Return sorted percent anchors with epsilon coalescing."""

    points: list[int] = []
    for calibration in calibrations:
        for percent, _ in calibration.anchors:
            inserted = False
            for index, existing in enumerate(points):
                if abs(existing - percent) <= epsilon:
                    inserted = True
                    break
                if percent < existing:
                    points.insert(index, percent)
                    inserted = True
                    break
            if not inserted:
                points.append(percent)
    points.sort()
    return points


def largest_gap_target(
    calibrations: Sequence[ShadeCalibration],
    *,
    epsilon: int = ASSISTED_PERCENT_EPSILON,
    default: int = 50,
) -> int:
    """Return the midpoint of the largest remaining calibration gap."""

    if not calibrations:
        return default

    points = _normalized_percent_points(calibrations, epsilon=epsilon)
    if len(points) < 2:
        return default

    largest_gap = -1
    target = default
    for index in range(len(points) - 1):
        start = points[index]
        end = points[index + 1]
        gap = end - start
        if gap > largest_gap:
            largest_gap = gap
            target = start + gap // 2
    return max(0, min(100, target))


def apply_assisted_anchor(
    calibration: ShadeCalibration,
    percent: int,
    raw: int,
    *,
    percent_epsilon: int = ASSISTED_PERCENT_EPSILON,
    raw_epsilon: int = ASSISTED_RAW_EPSILON,
) -> tuple[tuple[int, int], bool]:
    """Return anchors with an assisted entry inserted if changed."""

    anchors = list(calibration.anchors)
    percent_value = max(0, min(100, int(percent)))
    raw_value = int(raw)

    for index, (existing_percent, existing_raw) in enumerate(anchors):
        if abs(existing_percent - percent_value) <= percent_epsilon:
            if abs(existing_raw - raw_value) <= raw_epsilon:
                return calibration.anchors, False
            anchors[index] = (existing_percent, raw_value)
            normalized = validate_anchors(anchors)
            return normalized, True

    inserted = False
    for index, (existing_percent, _) in enumerate(anchors):
        if percent_value < existing_percent:
            anchors.insert(index, (percent_value, raw_value))
            inserted = True
            break
    if not inserted:
        anchors.append((percent_value, raw_value))

    normalized = validate_anchors(anchors)
    return normalized, True


@dataclass(frozen=True)
class AssistedCalibrationRun:
    """Diagnostics payload for an assisted calibration run."""

    group_id: str
    target_percent: int
    saved: tuple[str, ...]
    skipped: tuple[str, ...]
    timestamp: datetime

    def as_diagnostics(self) -> dict[str, object]:
        return {
            "group_id": self.group_id,
            "target_percent": self.target_percent,
            "saved": list(self.saved),
            "skipped": list(self.skipped),
            "timestamp": self.timestamp.isoformat(),
        }
