"""Predictive stop planning for Crestron Home shades."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from statistics import median
from typing import Dict, Sequence

from .learning import LearningManager, ShadeLearningState

VELOCITY_EPS = 0.005


@dataclass
class MotionSample:
    time: float
    position: float


@dataclass
class StopHistoryEntry:
    timestamp: float
    position: float
    velocity: float
    target: float
    settled: float | None
    distance: float


@dataclass
class ShadeStopInput:
    """Information required to plan a stop for a single shade."""

    shade_id: str
    position: float
    velocity: float
    direction: int
    baseline: float | None
    tau_resp: float
    tau_acc: float
    tau_dec: float
    v0: float
    v1: float
    confidence: float
    min_position: float = 0.0
    max_position: float = 1.0
    stale_seconds: float = 0.0
    safe_when_uncertain: bool = True


@dataclass
class ShadeStopTarget:
    """Planned absolute position for a shade in the percent domain."""

    shade_id: str
    position: float
    clamped: bool
    distance: float


@dataclass
class PlanResult:
    """Result returned from :class:`PredictiveStopPlanner`."""

    targets: list[ShadeStopTarget]
    flush: bool


class ShadeModel:
    """Simple kinematic model for shades using steady-state parameters."""

    def __init__(self, *, tau_acc: float, tau_dec: float) -> None:
        self._tau_acc = tau_acc
        self._tau_dec = tau_dec

    @staticmethod
    def steady_speed(v0: float, v1: float, position: float) -> float:
        return max(0.01, v0 + v1 * position)

    def estimate_velocity(
        self,
        *,
        position: float,
        measured_velocity: float,
        v0: float,
        v1: float,
        confidence: float,
        stale_seconds: float,
    ) -> float:
        model_velocity = self.steady_speed(v0, v1, position)
        blend = confidence * max(0.0, 1.0 - stale_seconds / 2.5)
        return blend * measured_velocity + (1.0 - blend) * model_velocity

    def forward_distance(
        self,
        velocity: float,
        *,
        tau_resp: float,
        tau_dec: float | None = None,
    ) -> float:
        if tau_dec is None:
            tau_dec = self._tau_dec
        velocity = max(0.0, velocity)
        d_lat = velocity * max(0.0, tau_resp)
        d_dec = 0.5 * velocity * max(0.0, tau_dec)
        return d_lat + d_dec


class PredictiveStopPlanner:
    """Compute non-backtracking stop positions for one or more shades."""

    def __init__(
        self,
        *,
        tau_acc: float,
        tau_dec: float,
        min_confidence_scale: float = 0.25,
    ) -> None:
        self._model = ShadeModel(tau_acc=tau_acc, tau_dec=tau_dec)
        self._min_conf_scale = min_confidence_scale

    def _safety_scale(self, confidence: float) -> float:
        return max(self._min_conf_scale, min(1.0, confidence))

    def plan_targets(self, inputs: Sequence[ShadeStopInput]) -> PlanResult:
        active_inputs = [item for item in inputs if item.direction != 0]
        if not active_inputs:
            targets = [
                ShadeStopTarget(item.shade_id, item.position, False, 0.0)
                for item in inputs
            ]
            return PlanResult(targets=targets, flush=False)

        distances: list[float] = []
        adjusted: list[tuple[ShadeStopInput, float, float]] = []
        for item in active_inputs:
            predicted_velocity = self._model.estimate_velocity(
                position=item.position,
                measured_velocity=abs(item.velocity),
                v0=item.v0,
                v1=item.v1,
                confidence=item.confidence,
                stale_seconds=item.stale_seconds,
            )
            if predicted_velocity <= 0:
                predicted_velocity = abs(item.velocity)
            forward = self._model.forward_distance(
                predicted_velocity,
                tau_resp=item.tau_resp,
                tau_dec=item.tau_dec,
            )
            forward *= self._safety_scale(item.confidence)
            if item.safe_when_uncertain and item.confidence < 0.05:
                forward = 0.0
            distances.append(forward)
            adjusted.append((item, predicted_velocity, forward))

        baseline_deltas: list[float] = []
        for item in active_inputs:
            if item.baseline is not None:
                baseline_deltas.append(item.position - item.baseline)

        if baseline_deltas:
            group_delta = median(baseline_deltas)
        else:
            group_delta = 0.0

        if distances:
            group_coast = median(distances)
        else:
            group_coast = 0.0

        targets: list[ShadeStopTarget] = []
        for item, _, forward in adjusted:
            direction = 1 if item.direction > 0 else -1
            proposed = item.position + direction * forward
            if item.baseline is not None:
                proposed_group = item.baseline + group_delta + direction * group_coast
                if direction > 0:
                    proposed = max(proposed, proposed_group)
                else:
                    proposed = min(proposed, proposed_group)

            proposed = max(item.min_position, min(item.max_position, proposed))
            if direction > 0 and proposed < item.position:
                proposed = item.position
            elif direction < 0 and proposed > item.position:
                proposed = item.position

            clamped = proposed in (item.min_position, item.max_position)
            targets.append(
                ShadeStopTarget(
                    shade_id=item.shade_id,
                    position=proposed,
                    clamped=clamped,
                    distance=forward,
                )
            )

        remaining_ids = {
            item.shade_id for item in inputs if item.direction == 0
        } - {target.shade_id for target in targets}
        for item in inputs:
            if item.shade_id in remaining_ids:
                targets.append(
                    ShadeStopTarget(
                        shade_id=item.shade_id,
                        position=item.position,
                        clamped=False,
                        distance=0.0,
                    )
                )

        return PlanResult(targets=targets, flush=True)


@dataclass
class ShadeRuntimeState:
    """Runtime tracking of motion, learning and diagnostics for a shade."""

    learning: ShadeLearningState
    last_sample: MotionSample | None = None
    prev_sample: MotionSample | None = None
    last_velocity: float = 0.0
    last_direction: int = 0
    baseline: float | None = None
    command_time: float | None = None
    moving_since: float | None = None
    history: deque[StopHistoryEntry] = field(default_factory=deque)

    def update_samples(self, sample: MotionSample) -> None:
        self.prev_sample = self.last_sample
        self.last_sample = sample

    def record_history(self, entry: StopHistoryEntry, *, max_entries: int) -> None:
        if not self.history.maxlen or self.history.maxlen != max_entries:
            self.history = deque(self.history, maxlen=max_entries)
        self.history.append(entry)


class PredictiveRuntime:
    """High-level controller coordinating predictive stops and learning."""

    def __init__(
        self,
        *,
        learning: LearningManager,
        tau_acc: float,
        tau_dec: float,
        tau_resp_init: float,
        min_confidence_scale: float,
        history_size: int,
    ) -> None:
        self._learning = learning
        self._planner = PredictiveStopPlanner(
            tau_acc=tau_acc,
            tau_dec=tau_dec,
            min_confidence_scale=min_confidence_scale,
        )
        self._tau_acc = tau_acc
        self._tau_dec = tau_dec
        self._tau_resp_init = tau_resp_init
        self._history_size = history_size
        self._states: Dict[str, ShadeRuntimeState] = {}
        self.enabled = True

    def get_state(self, shade_id: str) -> ShadeRuntimeState:
        if shade_id not in self._states:
            learning_state = self._learning.get_state(shade_id)
            state = ShadeRuntimeState(learning=learning_state)
            state.history = deque(maxlen=self._history_size)
            self._states[shade_id] = state
        return self._states[shade_id]

    def record_command(self, shade_id: str, timestamp: float) -> None:
        state = self.get_state(shade_id)
        state.command_time = timestamp

    def record_poll(self, shade_id: str, *, timestamp: float, position: float) -> None:
        state = self.get_state(shade_id)
        sample = MotionSample(timestamp, position)
        state.update_samples(sample)

        if state.prev_sample is None:
            return

        dt = sample.time - state.prev_sample.time
        if dt <= 0:
            return

        velocity = (sample.position - state.prev_sample.position) / dt
        state.last_velocity = velocity

        moving = abs(velocity) >= VELOCITY_EPS
        direction = 0
        if moving:
            direction = 1 if velocity > 0 else -1

        if direction != 0 and state.last_direction == 0:
            state.baseline = state.prev_sample.position
            state.moving_since = state.prev_sample.time
            if state.command_time is not None:
                latency = max(0.0, state.prev_sample.time - state.command_time)
                self._learning.update_latency(shade_id, latency)
                state.command_time = None

        if direction == 0 and state.last_direction != 0:
            state.moving_since = None

        state.last_direction = direction

        if moving and dt >= 0.1:
            self._learning.update_speed(shade_id, state.prev_sample.position, abs(velocity))

    def plan_stop(self, shade_ids: Sequence[str], *, timestamp: float) -> PlanResult:
        inputs: list[ShadeStopInput] = []
        for shade_id in shade_ids:
            state = self.get_state(shade_id)
            sample = state.last_sample
            if sample is None:
                inputs.append(
                    ShadeStopInput(
                        shade_id=shade_id,
                        position=0.0,
                        velocity=0.0,
                        direction=0,
                        baseline=None,
                        tau_resp=self._tau_resp_init,
                        tau_acc=self._tau_acc,
                        tau_dec=self._tau_dec,
                        v0=state.learning.rls.theta0,
                        v1=state.learning.rls.theta1,
                        confidence=0.0,
                    )
                )
                continue

            stale = max(0.0, timestamp - sample.time)
            velocity = state.last_velocity
            direction = state.last_direction
            if stale > 4.0:
                direction = 0
            confidence = state.learning.confidence
            if stale > 2.0:
                confidence *= max(0.0, 1.0 - (stale - 2.0) / 4.0)

            inputs.append(
                ShadeStopInput(
                    shade_id=shade_id,
                    position=sample.position,
                    velocity=velocity,
                    direction=direction,
                    baseline=state.baseline,
                    tau_resp=state.learning.tau_resp,
                    tau_acc=self._tau_acc,
                    tau_dec=self._tau_dec,
                    v0=state.learning.rls.theta0,
                    v1=state.learning.rls.theta1,
                    confidence=confidence,
                    stale_seconds=stale,
                    safe_when_uncertain=stale > 3.0,
                )
            )

        if not self.enabled:
            targets = [
                ShadeStopTarget(shade_id=item.shade_id, position=item.position, clamped=False, distance=0.0)
                for item in inputs
            ]
            return PlanResult(targets=targets, flush=True)

        return self._planner.plan_targets(inputs)

    def moving_shades(self) -> list[str]:
        return [
            shade_id
            for shade_id, state in self._states.items()
            if state.last_direction != 0
        ]

    def record_stop_outcome(
        self,
        shade_id: str,
        *,
        timestamp: float,
        target: float,
        settled: float | None,
    ) -> None:
        state = self.get_state(shade_id)
        sample = state.last_sample
        if sample is None:
            return
        entry = StopHistoryEntry(
            timestamp=timestamp,
            position=sample.position,
            velocity=state.last_velocity,
            target=target,
            settled=settled,
            distance=abs(target - sample.position),
        )
        state.record_history(entry, max_entries=self._history_size)

    def diagnostics(self) -> Dict[str, Dict[str, object]]:
        payload: Dict[str, Dict[str, object]] = {}
        for shade_id, state in self._states.items():
            payload[shade_id] = {
                "v0": state.learning.rls.theta0,
                "v1": state.learning.rls.theta1,
                "tau_resp": state.learning.tau_resp,
                "confidence": state.learning.confidence,
                "history": [entry.__dict__ for entry in state.history],
            }
        return payload

    def serialize_learning(self) -> Dict[str, object]:
        return self._learning.as_dict()

    def reset_shade(self, shade_id: str) -> None:
        if shade_id in self._states:
            self._states.pop(shade_id)
            self._learning.states.pop(shade_id, None)
            # Recreate state with defaults
        self.get_state(shade_id)
