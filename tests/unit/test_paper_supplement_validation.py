from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from he3sim.analysis import paper_supplement_validation as supplement
from he3sim.analysis.paper_supplement_validation import (
    FeynmanGateProtocol,
    HighRateProtocol,
    _gate_widths,
    _overlap_fraction,
    _override_config,
    _paired_bootstrap_ci,
    _safe_nrmse,
    preregistered_protocol_payload,
    protocol_sha256,
)
from he3sim.config import load_config
from he3sim.types import TRUE_EVENT_DTYPE


def test_high_rate_protocol_pairs_rates_and_durations() -> None:
    protocol = HighRateProtocol()

    assert len(protocol.rates_cps) == len(protocol.durations_s)
    assert protocol.rates_cps[0] == 1.0e3
    assert protocol.rates_cps[-1] == 1.0e7


def test_overlap_fraction_marks_either_close_neighbor() -> None:
    times = np.asarray([0.0, 1.0e-6, 20.0e-6, 21.0e-6, 100.0e-6])

    fraction = _overlap_fraction(times, 5.0e-6)

    assert np.isclose(fraction, 4.0 / 5.0)


def test_safe_nrmse_is_zero_for_equal_nonzero_signals() -> None:
    values = np.asarray([0.0, 1.0, -1.0])

    assert _safe_nrmse(values, values) == 0.0


def test_safe_nrmse_does_not_hide_nonzero_error_on_zero_reference() -> None:
    zeros = np.zeros(3)
    assert _safe_nrmse(zeros, zeros) == 0.0
    with pytest.raises(ValueError, match="zero reference"):
        _safe_nrmse(np.ones(3), zeros)


def test_gate_widths_are_frozen_in_dimensionless_alpha_t() -> None:
    protocol = FeynmanGateProtocol()
    strategy = protocol.candidate_alpha_t_ranges[2]

    gates = _gate_widths(protocol, strategy)

    assert gates.size == protocol.gates_per_candidate
    assert np.isclose(gates[0] * protocol.alpha_true_s_inv, 0.10)
    assert np.isclose(gates[-1] * protocol.alpha_true_s_inv, 8.0)


def test_development_and_holdout_seeds_are_disjoint_and_serialized() -> None:
    protocol = FeynmanGateProtocol()
    payload = preregistered_protocol_payload(feynman_gate=protocol)

    assert not set(protocol.development_seeds) & set(protocol.holdout_seeds)
    assert payload["frozen_before_result_inspection"] is True
    assert payload["feynman_gate"]["development_seeds"] == protocol.development_seeds
    assert len(protocol_sha256(payload)) == 64


def test_config_override_preserves_synthetic_state_and_rate_identity() -> None:
    root = Path(__file__).parents[2]
    base = load_config(root / "configs" / "demo_correlated.yaml")

    arm = _override_config(
        base,
        true_rate_cps=3_000.0,
        duration_s=0.5,
        seed=99,
        sample_rate_hz=100_000_000.0,
        noise_enabled=True,
        dead_time_mode="nonparalyzable",
        dead_time_s=4.0e-6,
    )

    assert arm.metadata.seed.value == 99
    assert arm.simulation.true_rate_cps.value == 3_000.0
    assert np.isclose(arm.source_model.source_rate_cps.value, 3_000.0, rtol=1e-12, atol=0.0)
    assert arm.observation.duration_s.value == 0.5
    assert arm.metadata.seed.status.value == "synthetic_demo"


def test_paired_bootstrap_ci_is_positive_for_uniform_improvements() -> None:
    protocol = FeynmanGateProtocol(paired_bootstrap_replicates=500)
    improvements = np.asarray([10.0, 12.0, 9.0, 8.0, 11.0, 10.0, 13.0, 9.0])

    low, high = _paired_bootstrap_ci(improvements, protocol)

    assert low > 0.0
    assert high >= low


@pytest.mark.parametrize("rate_cps", [10.0, 1.0e3, 1.0e4, 1.0e5, 1.0e6, 1.0e7])
def test_source_rate_override_handles_closed_interval_boundaries(rate_cps: float) -> None:
    base = load_config(Path(__file__).parents[2] / "configs" / "demo_correlated.yaml")
    arm = _override_config(
        base,
        true_rate_cps=rate_cps,
        duration_s=0.002,
        seed=99,
        noise_enabled=False,
        dead_time_mode="none",
        dead_time_s=0.0,
    )
    assert arm.source_model.source_rate_cps.value is not None
    assert 10.0 <= arm.source_model.source_rate_cps.value <= 1.0e7
    assert np.isclose(arm.source_model.source_rate_cps.value, rate_cps, rtol=1e-12)


def test_source_rate_override_does_not_clamp_genuinely_invalid_source() -> None:
    base = load_config(Path(__file__).parents[2] / "configs" / "demo_correlated.yaml")
    raw = base.model_dump(mode="python")
    raw["source_model"]["detection_efficiency"]["value"] = 0.15
    raw["source_model"]["source_rate_cps"]["value"] = 4000.0
    base = type(base).model_validate(raw)
    with pytest.raises(ValidationError, match="source_rate_cps must be within"):
        _override_config(
            base,
            true_rate_cps=1.0e7,
            duration_s=0.002,
            seed=99,
            noise_enabled=False,
            dead_time_mode="none",
            dead_time_s=0.0,
        )


def test_trigger_efficiency_never_credits_one_trigger_to_multiple_truths() -> None:
    base = load_config(Path(__file__).parents[2] / "configs" / "demo_correlated.yaml")
    events = np.zeros(3, dtype=TRUE_EVENT_DTYPE)
    events["t_s"] = [0.001, 0.001001, 0.001002]
    efficiency, false_fraction = supplement._trigger_metrics(np.array([0.0010005]), events, base)
    assert efficiency == pytest.approx(1 / 3)
    assert false_fraction == 0.0
    efficiency, false_fraction = supplement._trigger_metrics(
        np.array([0.0010005, 0.0010015, 0.0010025, 0.0010035]), events, base
    )
    assert efficiency == 1.0
    assert false_fraction == 0.25


def test_holdout_cannot_change_development_selected_strategy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = load_config(Path(__file__).parents[2] / "configs" / "demo_correlated.yaml")
    protocol = FeynmanGateProtocol(paired_bootstrap_replicates=100)
    chosen = "trim_0p20_to_8"
    calls: list[tuple[str, int, str]] = []

    def fake_times(*args: object, **kwargs: object) -> np.ndarray:
        return np.linspace(0, 0.49, 30)

    def fake_fit(
        times_s: np.ndarray,
        protocol: FeynmanGateProtocol,
        *,
        split: str,
        seed: int,
        strategy: tuple[str, float, float],
    ) -> supplement.FeynmanGateFitPoint:
        calls.append((split, seed, strategy[0]))
        # The winner on development deliberately loses on holdout.
        error = 0.01 if strategy[0] == chosen else 0.1
        if split == "holdout":
            error = 0.4 if strategy[0] == chosen else 0.02
        return supplement.FeynmanGateFitPoint(
            split,
            seed,
            strategy[0],
            times_s.size,
            protocol.alpha_true_s_inv * (1 + error),
            error,
            0.99,
            strategy[1] / protocol.alpha_true_s_inv,
            strategy[2] / protocol.alpha_true_s_inv,
        )

    monkeypatch.setattr(supplement, "_waveform_observed_times", fake_times)
    monkeypatch.setattr(supplement, "_feynman_fit_point", fake_fit)
    result = supplement.run_feynman_gate_validation(base, protocol)
    assert result.selected_strategy == chosen
    assert not result.improvement_claim_supported
    assert not result.selected_meets_accuracy_tolerance
    assert len(calls) == 4 * 6 + 8 * 2
    assert {name for split, _seed, name in calls if split == "holdout"} == {
        "baseline_20us_10ms",
        chosen,
    }
    assert [split for split, _seed, _name in calls] == ["development"] * 24 + ["holdout"] * 16
