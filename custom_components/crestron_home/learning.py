"""Online learning helpers for predictive stop planning."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


def _clamp(value: float, lower: float, upper: float) -> float:
    if value < lower:
        return lower
    if value > upper:
        return upper
    return value


@dataclass
class RecursiveLeastSquares:
    """Two-parameter RLS estimator for v_ss(s) = V0 + V1 * s."""

    theta0: float
    theta1: float
    cov_00: float = 25.0
    cov_01: float = 0.0
    cov_11: float = 25.0
    forgetting: float = 0.98

    def predict(self, position: float) -> float:
        return self.theta0 + self.theta1 * position

    def as_dict(self) -> Dict[str, float]:
        return {
            "theta0": self.theta0,
            "theta1": self.theta1,
            "cov_00": self.cov_00,
            "cov_01": self.cov_01,
            "cov_11": self.cov_11,
            "forgetting": self.forgetting,
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any], *, default_forgetting: float) -> "RecursiveLeastSquares":
        return cls(
            theta0=float(payload.get("theta0", 0.4)),
            theta1=float(payload.get("theta1", 0.0)),
            cov_00=float(payload.get("cov_00", 25.0)),
            cov_01=float(payload.get("cov_01", 0.0)),
            cov_11=float(payload.get("cov_11", 25.0)),
            forgetting=float(payload.get("forgetting", default_forgetting)),
        )

    def update(self, position: float, velocity: float) -> None:
        phi0 = 1.0
        phi1 = position
        cov00 = self.cov_00
        cov01 = self.cov_01
        cov11 = self.cov_11

        gain_denom = (
            self.forgetting
            + phi0 * (cov00 * phi0 + cov01 * phi1)
            + phi1 * (cov01 * phi0 + cov11 * phi1)
        )
        if gain_denom <= 1e-6:
            gain_denom = 1e-6
        gain0 = (cov00 * phi0 + cov01 * phi1) / gain_denom
        gain1 = (cov01 * phi0 + cov11 * phi1) / gain_denom

        estimate = self.theta0 * phi0 + self.theta1 * phi1
        error = velocity - estimate

        self.theta0 += gain0 * error
        self.theta1 += gain1 * error

        cov00 = (cov00 - gain0 * (cov00 * phi0 + cov01 * phi1)) / self.forgetting
        cov01 = (cov01 - gain0 * (cov01 * phi0 + cov11 * phi1)) / self.forgetting
        cov11 = (cov11 - gain1 * (cov01 * phi0 + cov11 * phi1)) / self.forgetting

        self.cov_00 = max(cov00, 1e-3)
        self.cov_01 = cov01
        self.cov_11 = max(cov11, 1e-3)


@dataclass
class ShadeLearningState:
    """Container for per-shade learned parameters."""

    rls: RecursiveLeastSquares
    tau_resp: float
    rmse: float = 0.2
    sample_count: int = 0
    confidence: float = 0.0
    last_updated: float | None = None

    @classmethod
    def create_default(
        cls,
        *,
        v0: float,
        v1: float,
        tau_resp: float,
        forgetting: float,
    ) -> "ShadeLearningState":
        return cls(
            rls=RecursiveLeastSquares(v0, v1, forgetting=forgetting),
            tau_resp=tau_resp,
            rmse=0.2,
            sample_count=0,
            confidence=0.0,
            last_updated=None,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rls": self.rls.as_dict(),
            "tau_resp": self.tau_resp,
            "rmse": self.rmse,
            "sample_count": self.sample_count,
            "confidence": self.confidence,
            "last_updated": self.last_updated,
        }

    @classmethod
    def from_dict(
        cls,
        payload: Dict[str, Any],
        *,
        defaults: Dict[str, float],
    ) -> "ShadeLearningState":
        rls_payload = payload.get("rls", {})
        rls = RecursiveLeastSquares.from_dict(
            rls_payload,
            default_forgetting=defaults["forgetting"],
        )
        return cls(
            rls=rls,
            tau_resp=float(payload.get("tau_resp", defaults["tau_resp"])),
            rmse=float(payload.get("rmse", 0.2)),
            sample_count=int(payload.get("sample_count", 0)),
            confidence=float(payload.get("confidence", 0.0)),
            last_updated=payload.get("last_updated"),
        )

    def update_speed(self, position: float, velocity: float) -> None:
        velocity = max(-2.0, min(2.0, velocity))
        self.rls.update(position, velocity)
        self.sample_count += 1
        residual = velocity - self.rls.predict(position)
        self.rmse = ((self.sample_count - 1) * self.rmse**2 + residual**2) ** 0.5
        self.rmse /= max(self.sample_count, 1) ** 0.5
        self._recompute_confidence()

    def update_tau_resp(self, latency: float, *, alpha: float) -> None:
        latency = max(0.05, min(1.5, latency))
        self.tau_resp = (1 - alpha) * self.tau_resp + alpha * latency
        self._recompute_confidence()

    def _recompute_confidence(self) -> None:
        rmse_term = _clamp(1.0 - self.rmse / 0.15, 0.0, 1.0)
        count_term = _clamp(self.sample_count / 20.0, 0.0, 1.0)
        self.confidence = round(rmse_term * count_term, 6)


@dataclass
class LearningManager:
    """Tracks per-shade learning state."""

    defaults: Dict[str, float]
    states: Dict[str, ShadeLearningState] = field(default_factory=dict)

    def get_state(self, shade_id: str) -> ShadeLearningState:
        if shade_id not in self.states:
            self.states[shade_id] = ShadeLearningState.create_default(
                v0=self.defaults.get("v0", 0.4),
                v1=self.defaults.get("v1", 0.0),
                tau_resp=self.defaults.get("tau_resp", 0.15),
                forgetting=self.defaults.get("forgetting", 0.98),
            )
        return self.states[shade_id]

    def update_speed(self, shade_id: str, position: float, velocity: float) -> None:
        state = self.get_state(shade_id)
        state.update_speed(position, velocity)

    def update_latency(self, shade_id: str, latency: float) -> None:
        state = self.get_state(shade_id)
        state.update_tau_resp(latency, alpha=self.defaults.get("tau_resp_alpha", 0.2))

    def as_dict(self) -> Dict[str, Any]:
        return {shade_id: state.to_dict() for shade_id, state in self.states.items()}

    @classmethod
    def from_dict(
        cls,
        payload: Dict[str, Any] | None,
        *,
        defaults: Dict[str, float],
    ) -> "LearningManager":
        manager = cls(defaults=defaults, states={})
        if not payload:
            return manager
        for shade_id, data in payload.items():
            try:
                manager.states[str(shade_id)] = ShadeLearningState.from_dict(
                    data,
                    defaults=defaults,
                )
            except Exception:
                continue
        return manager

