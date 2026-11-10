from pathlib import Path

import numpy as np

from he3sim.analysis.waveform_alpha_validation import (
    _derived_config,
    _one_to_one_trigger_metrics,
    _paired_base_config,
    collect_waveform_candidates,
)
from he3sim.config import load_config
from he3sim.synthesis.streaming import prepare_waveform_simulation
from he3sim.types import TRUE_EVENT_DTYPE


def test_waveform_candidate_collection_uses_rendered_blocks() -> None:
    root = Path(__file__).parents[2]
    base = load_config(root / "configs" / "demo_correlated.yaml")
    config = _derived_config(
        base,
        noise_enabled=False,
        dead_time_mode="none",
        dead_time_s=0.0,
        duration_s=0.002,
    )
    simulation = prepare_waveform_simulation(
        config, max_expected_events=1_000, max_waveform_samples=1_000_000
    )

    candidates = collect_waveform_candidates(simulation, config)

    assert candidates.ndim == 1
    assert np.all(np.diff(candidates) > 0.0)
    assert np.all(candidates >= 0.0)
    assert np.all(candidates < 0.002)


def test_paired_waveform_condition_preserves_source_and_observation_controls() -> None:
    root = Path(__file__).parents[2]
    base = load_config(root / "configs" / "demo_correlated.yaml")
    event_level = _derived_config(
        base,
        noise_enabled=False,
        dead_time_mode="none",
        dead_time_s=0.0,
        duration_s=0.01,
    )
    waveform_level = _derived_config(
        base,
        noise_enabled=True,
        dead_time_mode="nonparalyzable",
        dead_time_s=4e-6,
        duration_s=0.01,
    )

    assert event_level.metadata.seed.value == waveform_level.metadata.seed.value
    assert event_level.observation.duration_s.value == waveform_level.observation.duration_s.value
    assert event_level.source_model.model_dump() == waveform_level.source_model.model_dump()
    assert event_level.simulation.model_dump() == waveform_level.simulation.model_dump()


def test_paired_base_config_applies_shared_ui_style_controls() -> None:
    root = Path(__file__).parents[2]
    base = load_config(root / "configs" / "demo_correlated.yaml")

    paired = _paired_base_config(
        base,
        duration_s=10.0,
        true_rate_cps=3_000.0,
        alpha_s_inv=1_000.0,
        sample_rate_hz=None,
        seed=42,
    )

    assert paired.metadata.seed.value == 42
    assert paired.observation.duration_s.value == 10.0
    assert paired.simulation.true_rate_cps.value == 3_000.0
    assert paired.source_model.alpha.value == 1_000.0
    assert paired.simulation.sample_rate_hz.value == base.simulation.sample_rate_hz.value
    assert np.isclose(paired.source_model.source_rate_cps.value, 3_000.0)


def test_waveform_metric_does_not_credit_one_trigger_to_multiple_truth_events() -> None:
    root = Path(__file__).parents[2]
    config = _derived_config(
        load_config(root / "configs" / "demo_correlated.yaml"),
        noise_enabled=False,
        dead_time_mode="none",
        dead_time_s=0.0,
        duration_s=0.01,
    )
    events = np.zeros(3, dtype=TRUE_EVENT_DTYPE)
    events["t_s"] = [0.001, 0.001001, 0.001002]

    matched, efficiency, false_fraction = _one_to_one_trigger_metrics(
        np.asarray([0.0010005]), events, config
    )

    assert matched == 1
    assert efficiency == 1 / 3
    assert false_fraction == 0.0
