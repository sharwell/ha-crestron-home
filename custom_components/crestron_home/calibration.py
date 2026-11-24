"""Calibration helpers for Crestron Home shades."""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
import math
from typing import Any, Iterable, Mapping, MutableMapping, Sequence

__all__ = [
    "CalibrationCollection",
    "DEFAULT_ANCHORS",
    "InvalidCalibrationError",
    "ShadeCalibration",
    "parse_calibration_options",
    "pct_to_raw",
    "raw_to_pct",
    "remove_calibration_option",
    "update_calibration_option",
    "update_minimum_position",
    "validate_anchors",
]


from .const import (
    CAL_ANCHOR_PC_MAX,
    CAL_ANCHOR_PC_MIN,
    CAL_ANCHOR_RAW_MAX,
    CAL_ANCHOR_RAW_MIN,
    CAL_DEFAULT_ANCHORS,
    CAL_KEY_ANCHORS,
    CAL_KEY_INVERT,
    CONF_INVERT,
    DEFAULT_INVERT,
    ERR_ANCHORS_ENDPOINT,
    ERR_ANCHORS_PC_ORDER,
    ERR_ANCHORS_PC_RANGE,
    ERR_ANCHORS_RAW_MONOTONIC,
    ERR_ANCHORS_RAW_RANGE,
    ERR_ANCHORS_TOO_FEW,
    ERR_MINIMUM_POSITION_UNREACHABLE,
    OPT_CALIBRATION,
    OPT_MINIMUM_POSITIONS,
)

_LOGGER = logging.getLogger(__name__)

Anchor = tuple[int, int]

DEFAULT_ANCHORS: tuple[Anchor, ...] = tuple(
    (int(item["pc"]), int(item["raw"])) for item in CAL_DEFAULT_ANCHORS
)


class InvalidCalibrationError(ValueError):
    """Raised when calibration data fails validation."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ShadeCalibration:
    """Calibration parameters for a single shade."""

    anchors: tuple[Anchor, ...] = DEFAULT_ANCHORS
    invert_override: bool | None = None

    def resolved_invert(self, global_invert: bool) -> bool:
        """Return the effective invert flag for the shade."""

        if self.invert_override is None:
            return global_invert
        return self.invert_override

    def minimum_raw_target(self, minimum: int, global_invert: bool) -> int:
        """Return an allowed raw bound for a positive Home Assistant minimum.

        Round toward open and skip a flat span's raw value when it reports a
        position below the minimum. Raise InvalidCalibrationError if reaching
        the minimum would require moving beyond the calibrated open endpoint.
        """
        invert = self.resolved_invert(global_invert)
        threshold = _interpolate_raw(minimum, self.anchors, invert)
        raw = math.floor(threshold) if invert else math.ceil(threshold)
        reported = raw_to_pct(raw, self.anchors, invert)
        assert reported is not None
        if reported >= minimum:
            return raw

        # The first matching segment can report the closed side of a plateau.
        open_endpoint = self.anchors[0 if invert else -1][1]
        if raw != open_endpoint:
            raw += -1 if invert else 1
            reported = raw_to_pct(raw, self.anchors, invert)
            if reported is not None and reported >= minimum:
                return raw
        raise InvalidCalibrationError(
            ERR_MINIMUM_POSITION_UNREACHABLE,
            "The shade's calibration cannot reach its minimum position.",
        )


@dataclass(frozen=True)
class CalibrationCollection:
    """In-memory cache of calibration data for an entry."""

    global_invert: bool
    per_shade: Mapping[str, ShadeCalibration]
    minimum_positions: Mapping[str, int] = field(default_factory=dict)

    def for_shade(self, shade_id: str) -> ShadeCalibration:
        """Return calibration data for a shade."""

        if shade_id in self.per_shade:
            return self.per_shade[shade_id]
        return ShadeCalibration()

    def minimum_position(self, shade_id: str) -> int:
        """Return the minimum Home Assistant position, with 0 allowing full travel."""
        return self.minimum_positions.get(shade_id, CAL_ANCHOR_PC_MIN)

    def limit_raw_target(self, shade_id: str, raw: int) -> int:
        """Keep a controller target at or above the shade's configured minimum.

        Preserve the supplied raw position when there is no minimum or it is
        already allowed. Raise InvalidCalibrationError when the calibration
        cannot represent the minimum within its travel range.
        """
        minimum = self.minimum_position(shade_id)
        if minimum == CAL_ANCHOR_PC_MIN:
            return raw
        calibration = self.for_shade(shade_id)
        limit = calibration.minimum_raw_target(minimum, self.global_invert)
        if calibration.resolved_invert(self.global_invert):
            return min(raw, limit)
        return max(raw, limit)


def _coerce_int(value: Any) -> int:
    if isinstance(value, bool):
        raise TypeError("Boolean values are not valid integers")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(round(value))
    if isinstance(value, str):
        return int(float(value.strip()))
    return int(value)


def validate_anchors(raw_anchors: Iterable[Any]) -> tuple[Anchor, ...]:
    """Validate and normalize anchors supplied by the user."""

    anchors: list[Anchor] = []
    for index, item in enumerate(raw_anchors):
        if isinstance(item, Mapping):
            pc_value = item.get("pc")
            raw_value = item.get("raw")
        elif isinstance(item, (tuple, list)) and len(item) >= 2:
            pc_value, raw_value = item[0], item[1]
        else:
            raise InvalidCalibrationError(
                ERR_ANCHORS_PC_RANGE,
                f"Anchor #{index} is not a mapping with 'pc' and 'raw' entries",
            )

        try:
            pc = _coerce_int(pc_value)
        except (ValueError, TypeError) as err:
            raise InvalidCalibrationError(
                ERR_ANCHORS_PC_RANGE,
                f"Anchor #{index} percent value {pc_value!r} is not a number",
            ) from err

        try:
            raw = _coerce_int(raw_value)
        except (ValueError, TypeError) as err:
            raise InvalidCalibrationError(
                ERR_ANCHORS_RAW_RANGE,
                f"Anchor #{index} raw value {raw_value!r} is not a number",
            ) from err

        anchors.append((pc, raw))

    if len(anchors) < 2:
        raise InvalidCalibrationError(
            ERR_ANCHORS_TOO_FEW,
            "At least two anchors are required",
        )

    if anchors[0][0] != CAL_ANCHOR_PC_MIN or anchors[-1][0] != CAL_ANCHOR_PC_MAX:
        raise InvalidCalibrationError(
            ERR_ANCHORS_ENDPOINT,
            "First anchor must start at 0% and last anchor must end at 100%",
        )

    for index, (pc, raw) in enumerate(anchors):
        if not (CAL_ANCHOR_PC_MIN <= pc <= CAL_ANCHOR_PC_MAX):
            raise InvalidCalibrationError(
                ERR_ANCHORS_PC_RANGE,
                f"Anchor #{index} percent {pc} is outside the 0-100 range",
            )
        if not (CAL_ANCHOR_RAW_MIN <= raw <= CAL_ANCHOR_RAW_MAX):
            raise InvalidCalibrationError(
                ERR_ANCHORS_RAW_RANGE,
                f"Anchor #{index} raw {raw} is outside the valid range",
            )

    for index in range(1, len(anchors)):
        prev_pc, prev_raw = anchors[index - 1]
        pc, raw = anchors[index]
        if pc <= prev_pc:
            raise InvalidCalibrationError(
                ERR_ANCHORS_PC_ORDER,
                "Anchor percentages must be strictly increasing",
            )
        if raw < prev_raw:
            raise InvalidCalibrationError(
                ERR_ANCHORS_RAW_MONOTONIC,
                "Anchor raw values must be monotonically non-decreasing",
            )

    return tuple(anchors)


def _normalize_invert(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
        if lowered in {"none", "null", "default"}:
            return None
    return bool(value)


def _parse_shade_calibration(data: Mapping[str, Any]) -> ShadeCalibration:
    anchors = validate_anchors(data.get(CAL_KEY_ANCHORS, CAL_DEFAULT_ANCHORS))
    invert_override = _normalize_invert(data.get(CAL_KEY_INVERT))
    return ShadeCalibration(anchors=anchors, invert_override=invert_override)


def parse_calibration_options(options: Mapping[str, Any]) -> CalibrationCollection:
    """Parse calibration and per-shade minimum positions from config entry options."""

    global_invert = bool(options.get(CONF_INVERT, DEFAULT_INVERT))
    per_shade: dict[str, ShadeCalibration] = {}
    raw_minimums = options.get(OPT_MINIMUM_POSITIONS, {})
    minimums: dict[str, int] = {}
    if isinstance(raw_minimums, Mapping):
        minimums = {
            str(shade_id): minimum
            for shade_id, minimum in raw_minimums.items()
            if type(minimum) is int and CAL_ANCHOR_PC_MIN < minimum <= CAL_ANCHOR_PC_MAX
        }
    raw_calibration = options.get(OPT_CALIBRATION, {})

    if not isinstance(raw_calibration, Mapping):
        _LOGGER.warning("Calibration options were not a mapping; ignoring")
        return CalibrationCollection(global_invert, per_shade, minimums)

    for raw_shade_id, raw_data in raw_calibration.items():
        shade_id = str(raw_shade_id)
        if not isinstance(raw_data, Mapping):
            _LOGGER.warning("Ignoring a calibration entry because it is not a mapping")
            continue
        try:
            per_shade[shade_id] = _parse_shade_calibration(raw_data)
        except InvalidCalibrationError:
            _LOGGER.warning("Ignoring an invalid shade calibration entry")

    return CalibrationCollection(global_invert, per_shade, minimums)


def pct_to_raw(pct: int, anchors: Sequence[Anchor], invert_axis: bool) -> int:
    """Convert a Home Assistant percentage to a Crestron raw position.

    Supply validated (percent, raw position) anchors from 0% through 100%,
    with strictly increasing percentages and non-decreasing raw positions.
    Clamp `pct` to 0–100 and mirror it as 100 minus the value when
    `invert_axis` is true. Interpolate between the adjacent anchors,
    round to the nearest integer, and clamp the result to 0–65535.
    """

    raw = round(_interpolate_raw(pct, anchors, invert_axis))
    return max(CAL_ANCHOR_RAW_MIN, min(CAL_ANCHOR_RAW_MAX, raw))


def _interpolate_raw(pct: int, anchors: Sequence[Anchor], invert_axis: bool) -> float:
    pct_value = max(CAL_ANCHOR_PC_MIN, min(CAL_ANCHOR_PC_MAX, int(pct)))
    if invert_axis:
        pct_value = CAL_ANCHOR_PC_MAX - pct_value

    if pct_value <= anchors[0][0]:
        raw = anchors[0][1]
    elif pct_value >= anchors[-1][0]:
        raw = anchors[-1][1]
    else:
        raw = anchors[-1][1]
        for index in range(len(anchors) - 1):
            pc_start, raw_start = anchors[index]
            pc_end, raw_end = anchors[index + 1]
            if pct_value <= pc_end:
                span = pc_end - pc_start
                if span <= 0:
                    raw = raw_end
                    break
                ratio = (pct_value - pc_start) / span
                raw = raw_start + (raw_end - raw_start) * ratio
                break

    return raw


def raw_to_pct(raw: int | None, anchors: Sequence[Anchor], invert_axis: bool) -> int | None:
    """Convert a Crestron raw position to a Home Assistant percentage.

    Return None for a missing position. Otherwise, clamp `raw` to 0–65535.
    Supply validated (percent, raw position) anchors from 0% through 100%,
    with strictly increasing percentages and non-decreasing raw positions.

    Use the first segment whose ending raw position reaches the input.
    Positions outside the calibrated range use its endpoint percentage.
    When the selected segment is flat and matches the raw position, use
    its higher percentage. Round to an integer and, when `invert_axis`
    is true, mirror it as 100 minus the rounded value.
    """

    if raw is None:
        return None

    raw_value = max(CAL_ANCHOR_RAW_MIN, min(CAL_ANCHOR_RAW_MAX, int(raw)))

    pct = anchors[-1][0]
    for index in range(len(anchors) - 1):
        pc_start, raw_start = anchors[index]
        pc_end, raw_end = anchors[index + 1]
        if raw_value > raw_end:
            continue
        if raw_end == raw_start:
            if raw_value < raw_start:
                pct = pc_start
            else:
                pct = pc_end
            break
        if raw_value <= raw_start:
            pct = pc_start
            break
        span = raw_end - raw_start
        ratio = (raw_value - raw_start) / span
        pct = pc_start + (pc_end - pc_start) * ratio
        break

    pct_int = int(round(pct))
    if invert_axis:
        pct_int = CAL_ANCHOR_PC_MAX - pct_int
    if pct_int < CAL_ANCHOR_PC_MIN:
        return CAL_ANCHOR_PC_MIN
    if pct_int > CAL_ANCHOR_PC_MAX:
        return CAL_ANCHOR_PC_MAX
    return pct_int


def update_calibration_option(
    options: MutableMapping[str, Any], shade_id: str, calibration: ShadeCalibration
) -> None:
    """Persist calibration values back into the config entry options structure."""

    calibration_root = options.setdefault(OPT_CALIBRATION, {})
    if not isinstance(calibration_root, MutableMapping):
        calibration_root = {}
        options[OPT_CALIBRATION] = calibration_root

    anchors_payload = [
        {"pc": anchor[0], "raw": anchor[1]} for anchor in calibration.anchors
    ]
    payload: dict[str, Any] = {CAL_KEY_ANCHORS: anchors_payload}
    if calibration.invert_override is not None:
        payload[CAL_KEY_INVERT] = calibration.invert_override
    else:
        payload[CAL_KEY_INVERT] = None

    calibration_root[str(shade_id)] = payload


def remove_calibration_option(options: MutableMapping[str, Any], shade_id: str) -> None:
    """Remove stored calibration for a shade when defaults are requested."""

    calibration_root = options.get(OPT_CALIBRATION)
    if not isinstance(calibration_root, MutableMapping):
        return
    if str(shade_id) in calibration_root:
        calibration_root.pop(str(shade_id))
    if not calibration_root:
        options.pop(OPT_CALIBRATION, None)


def update_minimum_position(
    options: MutableMapping[str, Any], shade_id: str, minimum: int,
) -> None:
    """Store a validated 0–100 minimum, removing the limit when it is zero."""
    stored = options.get(OPT_MINIMUM_POSITIONS)
    minimums = dict(stored) if isinstance(stored, Mapping) else {}
    if minimum:
        minimums[shade_id] = minimum
    else:
        minimums.pop(shade_id, None)
    if minimums:
        options[OPT_MINIMUM_POSITIONS] = minimums
    else:
        options.pop(OPT_MINIMUM_POSITIONS, None)
