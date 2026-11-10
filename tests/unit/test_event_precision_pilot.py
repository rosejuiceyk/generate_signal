from pathlib import Path

import numpy as np

from he3sim.analysis.event_precision_pilot import (
    PILOT_SCENARIOS,
    _scenario_config,
    load_medium_scale_scenarios,
    load_physics_consistent_scenarios,
    physics_consistent_scenarios,
)
from he3sim.config import load_config


def test_event_precision_scenario_preserves_common_expected_event_count() -> None:
    base = load_config(Path(__file__).parents[2] / "configs" / "demo_correlated.yaml")
    config = _scenario_config(base, 1_000.0, 3_000.0, 0.70, 0.30, 30_000, 101)

    assert config.observation.duration_s.value == 10.0
    assert config.simulation.true_rate_cps.value == 3_000.0
    assert np.isclose(config.source_model.source_rate_cps.value, 3_000.0)
    assert config.source_model.max_chain_generation == 1_024
    assert len(PILOT_SCENARIOS) == 12


def test_physics_consistent_scenarios_derive_alpha_from_selected_baseline() -> None:
    scenarios = physics_consistent_scenarios()

    assert [round(item[1], 6) for item in scenarios] == [4666.666667, 3333.333333, 2000.0, 1000.0]
    assert [item[-1] for item in scenarios] == [100_000, 60_000, 30_000, 30_000]


def test_physics_consistent_yaml_is_loaded_with_derived_alpha() -> None:
    path = Path(__file__).parents[2] / "configs" / "event_precision_physics_consistent.yaml"
    scenarios, seeds = load_physics_consistent_scenarios(path)

    assert seeds == (101, 203, 307, 401)
    assert [round(item[1], 6) for item in scenarios] == [4666.666667, 3333.333333, 2000.0, 1000.0]


def test_medium_scale_yaml_expands_the_approved_grouped_matrix() -> None:
    path = Path(__file__).parents[2] / "configs" / "event_precision_medium_scale.yaml"
    main, seeds, stress, stress_seeds = load_medium_scale_scenarios(path)

    assert len(main) == 108
    assert seeds == (101, 203, 307, 401, 503, 601, 701, 809)
    assert len(main) * len(seeds) == 864
    assert stress[0][0].startswith("stress_near_critical_k_0.93")
    assert round(stress[0][1], 6) == 466.666667
    assert len(stress_seeds) == 16
