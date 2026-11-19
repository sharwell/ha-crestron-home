from home_assistant_stubs import home_assistant_stubs

with home_assistant_stubs():
    from custom_components.crestron_home.learning import LearningManager
    from custom_components.crestron_home.predictive_stop import (
        PredictiveRuntime,
        PredictiveStopPlanner,
        ShadeStopInput,
    )


def _make_input(**kwargs) -> ShadeStopInput:
    defaults = {
        "shade_id": "shade-1",
        "position": 0.5,
        "velocity": 0.3,
        "direction": 1,
        "baseline": 0.2,
        "tau_resp": 0.2,
        "tau_acc": 1.0,
        "tau_dec": 1.0,
        "v0": 0.4,
        "v1": 0.05,
        "confidence": 0.9,
    }
    defaults.update(kwargs)
    return ShadeStopInput(**defaults)


def test_plan_targets_no_backtrack() -> None:
    planner = PredictiveStopPlanner(tau_acc=1.0, tau_dec=1.0)
    result = planner.plan_targets([_make_input(position=0.45, velocity=0.25)])
    assert result.targets[0].position >= 0.45
    assert 0.0 <= result.targets[0].position <= 1.0


def test_group_planner_returns_consistent_targets_for_both_shades() -> None:
    planner = PredictiveStopPlanner(tau_acc=1.0, tau_dec=1.0)
    inputs = [
        _make_input(shade_id="s1", position=0.6, velocity=0.32, baseline=0.25),
        _make_input(
            shade_id="s2",
            position=0.55,
            velocity=0.28,
            baseline=0.20,
        ),
    ]
    result = planner.plan_targets(inputs)
    assert sorted(target.shade_id for target in result.targets) == ["s1", "s2"]
    positions = {target.shade_id: target.position for target in result.targets}
    first_offset = positions["s1"] - 0.25
    second_offset = positions["s2"] - 0.20
    assert abs(first_offset - second_offset) < 0.05


def test_planner_clamps_to_range() -> None:
    planner = PredictiveStopPlanner(tau_acc=1.0, tau_dec=1.0)
    result = planner.plan_targets(
        [_make_input(position=0.99, velocity=0.5, baseline=0.95)]
    )
    assert result.targets[0].position <= 1.0


def test_runtime_learns_from_motion() -> None:
    defaults = {
        "v0": 0.3,
        "v1": 0.0,
        "tau_resp": 0.15,
        "forgetting": 0.98,
        "tau_resp_alpha": 0.5,
    }
    manager = LearningManager.from_dict({}, defaults=defaults)
    runtime = PredictiveRuntime(
        learning=manager,
        tau_acc=1.0,
        tau_dec=1.0,
        tau_resp_init=0.2,
        min_confidence_scale=0.25,
        history_size=5,
    )

    speed_model = manager.get_state("shade").rls
    initial_speed = speed_model.predict(0.1)
    runtime.record_poll("shade", timestamp=1.0, position=0.1)
    runtime.record_poll("shade", timestamp=2.0, position=0.6)
    observed_speed = 0.5  # Half the travel range in one second.
    learned_speed = manager.get_state("shade").rls.predict(0.1)
    assert abs(learned_speed - observed_speed) < abs(initial_speed - observed_speed)

    state = runtime.get_state("shade")
    assert state.last_sample is not None
    assert state.last_direction == 1

    plan = runtime.plan_stop(["shade"], timestamp=2.1)
    target = next(item for item in plan.targets if item.shade_id == "shade")
    assert target.position >= state.last_sample.position
