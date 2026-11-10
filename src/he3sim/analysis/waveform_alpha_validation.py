"""Waveform-level prompt-decay-constant recovery validation.

Unlike the Phase-B event-time validation, this module deliberately passes the
same correlated-neutron truth through waveform rendering, threshold triggering
and (optionally) the observation dead-time layer before estimating alpha.  It
is a synthetic software verification; it is not a calibration of a physical
detector.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

import numpy as np

from he3sim.acquisition.dead_time import apply_dead_time
from he3sim.acquisition.trigger import DifferentialThresholdTrigger, ThresholdTrigger
from he3sim.analysis.figures import (
    phase_b_alpha_parity_figure,
    phase_b_feynman_figure,
    phase_b_psd_figure,
    phase_b_rossi_figure,
    waveform_event_pairwise_figure,
)
from he3sim.analysis.noise import NoiseAnalysis, analyze_event_noise
from he3sim.config import He3SimConfig, SourceModelKind
from he3sim.synthesis.streaming import (
    WaveformSimulation,
    iter_waveform_blocks,
    prepare_waveform_simulation,
)

_CONDITIONS = (
    ("G1_ideal_waveform", False, "none", 0.0),
    ("G2_noisy_waveform", True, "none", 0.0),
    ("G3_noisy_waveform_deadtime", True, "nonparalyzable", 4e-6),
)


@dataclass(frozen=True)
class WaveformAlphaCondition:
    """Recovery result for one synthetic observation condition."""

    name: str
    candidate_count: int
    accepted_count: int
    unique_true_events_observed: int
    waveform_trigger_efficiency: float
    false_trigger_fraction: float
    alpha_rossi_s_inv: float
    alpha_feynman_s_inv: float
    alpha_psd_s_inv: float
    alpha_rossi_rel_error: float
    alpha_feynman_rel_error: float
    alpha_psd_rel_error: float
    rossi_fit: dict[str, Any]
    feynman_fit: dict[str, Any]
    psd_fit: dict[str, Any]


@dataclass(frozen=True)
class WaveformAlphaValidationResult:
    """Machine-readable result of a waveform-to-alpha closed-loop run."""

    alpha_true_s_inv: float
    duration_s: float
    true_event_count: int
    shared_truth_seed: int
    reference: WaveformAlphaCondition
    conditions: tuple[WaveformAlphaCondition, ...]
    pairwise_comparisons: tuple[WaveformEventComparison, ...]
    alpha_tolerance_rel: float
    passed_reference_and_ideal: bool
    trigger_algorithm: str
    trigger_settings: dict[str, float]
    scope: str = (
        "synthetic_demo; waveform-level methodological verification only; "
        "not a physical detector calibration"
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WaveformEventComparison:
    """One waveform condition compared with its paired event-time reference."""

    condition: str
    rossi_relative_to_event: float
    feynman_relative_to_event: float
    psd_relative_to_event: float


def _derived_config(
    config: He3SimConfig,
    *,
    noise_enabled: bool,
    dead_time_mode: str,
    dead_time_s: float,
    duration_s: float | None,
) -> He3SimConfig:
    """Create one virtual acquisition condition without changing source truth."""

    raw = config.model_dump(mode="python")
    raw["trigger"]["enabled"] = True
    raw["noise"]["enabled"] = noise_enabled
    raw["dead_time"]["mode"] = dead_time_mode
    raw["dead_time"]["duration_s"]["value"] = dead_time_s
    if duration_s is not None:
        raw["observation"]["duration_s"]["value"] = duration_s
    return He3SimConfig.model_validate(raw)


def _paired_base_config(
    config: He3SimConfig,
    *,
    duration_s: float | None,
    true_rate_cps: float | None,
    alpha_s_inv: float | None,
    sample_rate_hz: float | None,
    seed: int | None,
) -> He3SimConfig:
    """Apply shared experimental controls before deriving any observation arm."""

    raw = config.model_dump(mode="python")
    if seed is not None:
        raw["metadata"]["seed"]["value"] = seed
    if alpha_s_inv is not None:
        raw["source_model"]["alpha"]["value"] = alpha_s_inv
    if sample_rate_hz is not None:
        raw["simulation"]["sample_rate_hz"]["value"] = sample_rate_hz
    if true_rate_cps is not None:
        k_eff = float(raw["source_model"]["k_eff"]["value"])
        efficiency = float(raw["source_model"]["detection_efficiency"]["value"])
        raw["simulation"]["true_rate_cps"]["value"] = true_rate_cps
        raw["source_model"]["source_rate_cps"]["value"] = true_rate_cps * (1.0 - k_eff) / efficiency
    if duration_s is not None:
        raw["observation"]["duration_s"]["value"] = duration_s
    return He3SimConfig.model_validate(raw)


def collect_waveform_candidates(
    simulation: WaveformSimulation,
    config: He3SimConfig,
    *,
    algorithm: Literal["level", "differential"] = "level",
    derivative_threshold_V: float = 0.004,
    derivative_delay_s: float = 5.0e-7,
    derivative_smoothing_s: float = 2.0e-7,
) -> np.ndarray:
    """Render blocks and extract reproducible observation candidates.

    ``level`` is the original voltage-level discriminator.  ``differential``
    applies a fixed, documented smoothing and delayed difference before the
    same hysteretic discriminator, making a new pulse onset detectable above
    the tail of an earlier pulse.  Neither mode reads event truth.
    """

    sample_rate_hz = float(config.simulation.sample_rate_hz.value)
    polarity = int(config.trigger.polarity.value)
    if algorithm == "level":
        trigger: ThresholdTrigger | DifferentialThresholdTrigger = ThresholdTrigger(
            sample_rate_hz=sample_rate_hz,
            polarity=polarity,
            threshold_V=float(config.trigger.threshold_V.value),
            hysteresis_V=float(config.trigger.hysteresis_V.value),
            min_hold_s=float(config.trigger.min_hold_s.value),
        )
    elif algorithm == "differential":
        trigger = DifferentialThresholdTrigger(
            sample_rate_hz=sample_rate_hz,
            polarity=polarity,
            derivative_threshold_V=derivative_threshold_V,
            hysteresis_V=derivative_threshold_V * 0.2,
            min_hold_s=float(config.trigger.min_hold_s.value),
            delay_s=derivative_delay_s,
            smoothing_s=derivative_smoothing_s,
        )
    else:
        raise ValueError(f"unknown waveform trigger algorithm: {algorithm}")
    state = None
    chunks: list[np.ndarray] = []
    for block in iter_waveform_blocks(simulation, config):
        if block.analog_samples_V is None:
            raise RuntimeError("Waveform validation requires analog waveform samples.")
        indices, state = trigger.process_block(
            block.analog_samples_V, block.sample_index_start, state
        )
        if indices.size:
            chunks.append(indices)
    if not chunks:
        return np.empty(0, dtype=np.float64)
    return np.concatenate(chunks).astype(np.float64) / sample_rate_hz


def _fit_payload(analysis: NoiseAnalysis) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    def payload(fit: Any) -> dict[str, Any]:
        values = asdict(fit)
        bootstrap = np.asarray(values.pop("bootstrap_alpha_per_s"), dtype=np.float64)
        for key, value in tuple(values.items()):
            if isinstance(value, float) and not np.isfinite(value):
                values[key] = None
        values["bootstrap_replicate_count"] = int(bootstrap.size)
        values["bootstrap_mean_alpha_per_s"] = float(np.mean(bootstrap)) if bootstrap.size else None
        return values

    return (payload(analysis.rossi.fit), payload(analysis.feynman.fit), payload(analysis.psd.fit))


def _one_to_one_trigger_metrics(
    candidate_times_s: np.ndarray, true_events: np.ndarray, config: He3SimConfig
) -> tuple[int, float, float]:
    """Match trigger candidates to truth once each for diagnostic reporting.

    The storage association window is intentionally many-to-many and cannot
    serve as a resolution metric: a single trigger may cover multiple closely
    spaced truth events.  This greedy matching is diagnostic only; the alpha
    estimators still receive the untouched observed candidate sequence.
    """

    if candidate_times_s.size == 0:
        return 0, 0.0, 0.0
    pre = config.trigger.pre_trigger_s
    post = config.trigger.post_trigger_s
    if pre is None or post is None or pre.value is None or post.value is None:
        raise ValueError("waveform validation requires trigger association windows")
    event_times = true_events["t_s"]
    used = np.zeros(event_times.size, dtype=np.bool_)
    matched = 0
    unmatched = 0
    for candidate_s in candidate_times_s:
        start = int(np.searchsorted(event_times, candidate_s - pre.value, side="left"))
        stop = int(np.searchsorted(event_times, candidate_s + post.value, side="right"))
        available = np.flatnonzero(~used[start:stop]) + start
        if available.size == 0:
            unmatched += 1
            continue
        nearest = int(available[int(np.argmin(np.abs(event_times[available] - candidate_s)))])
        used[nearest] = True
        matched += 1
    return (
        matched,
        matched / event_times.size if event_times.size else 0.0,
        unmatched / candidate_times_s.size,
    )


def _condition_result(
    name: str,
    true_events: np.ndarray,
    candidate_times_s: np.ndarray,
    config: He3SimConfig,
    alpha_true_s_inv: float,
    *,
    bootstrap_replicates: int,
) -> tuple[WaveformAlphaCondition, NoiseAnalysis]:
    duration_s = float(config.observation.duration_s.value)
    dead = apply_dead_time(
        candidate_times_s,
        float(config.dead_time.duration_s.value),
        config.dead_time.mode,
    )
    accepted = candidate_times_s[dead.accepted]
    matched_count, efficiency, false_fraction = _one_to_one_trigger_metrics(
        accepted, true_events, config
    )
    analysis = analyze_event_noise(
        accepted,
        duration_s,
        bootstrap_replicates=bootstrap_replicates,
        seed=int(config.metadata.seed.value) + 911,
    )
    rossi_fit, feynman_fit, psd_fit = _fit_payload(analysis)
    estimates = (
        analysis.rossi.fit.alpha_per_s,
        analysis.feynman.fit.alpha_per_s,
        analysis.psd.fit.alpha_per_s,
    )
    return (
        WaveformAlphaCondition(
            name=name,
            candidate_count=int(candidate_times_s.size),
            accepted_count=int(accepted.size),
            unique_true_events_observed=matched_count,
            waveform_trigger_efficiency=efficiency,
            false_trigger_fraction=false_fraction,
            alpha_rossi_s_inv=float(estimates[0]),
            alpha_feynman_s_inv=float(estimates[1]),
            alpha_psd_s_inv=float(estimates[2]),
            alpha_rossi_rel_error=float(abs(estimates[0] / alpha_true_s_inv - 1.0)),
            alpha_feynman_rel_error=float(abs(estimates[1] / alpha_true_s_inv - 1.0)),
            alpha_psd_rel_error=float(abs(estimates[2] / alpha_true_s_inv - 1.0)),
            rossi_fit=rossi_fit,
            feynman_fit=feynman_fit,
            psd_fit=psd_fit,
        ),
        analysis,
    )


def _paired_comparison(
    reference: WaveformAlphaCondition, condition: WaveformAlphaCondition
) -> WaveformEventComparison:
    """Express one waveform result relative to the same realization's G0 fit."""

    return WaveformEventComparison(
        condition=condition.name,
        rossi_relative_to_event=(condition.alpha_rossi_s_inv / reference.alpha_rossi_s_inv - 1.0),
        feynman_relative_to_event=(
            condition.alpha_feynman_s_inv / reference.alpha_feynman_s_inv - 1.0
        ),
        psd_relative_to_event=(condition.alpha_psd_s_inv / reference.alpha_psd_s_inv - 1.0),
    )


def run_waveform_alpha_validation(
    config: He3SimConfig,
    *,
    duration_s: float | None = None,
    bootstrap_replicates: int = 80,
    alpha_tolerance_rel: float = 0.05,
    max_expected_events: int = 100_000,
    max_waveform_samples: int = 100_000_000,
    true_rate_cps: float | None = None,
    alpha_s_inv: float | None = None,
    sample_rate_hz: float | None = None,
    seed: int | None = None,
    trigger_algorithm: Literal["level", "differential"] = "level",
    derivative_threshold_V: float = 0.004,
    derivative_delay_s: float = 5.0e-7,
    derivative_smoothing_s: float = 2.0e-7,
) -> tuple[WaveformAlphaValidationResult, dict[str, NoiseAnalysis]]:
    """Run G0--G3 with a paired correlated-neutron truth realization.

    G0 is direct event-time recovery. G1, G2 and G3 respectively add ideal
    waveform triggering, waveform noise, and a 4-us nonparalyzable observation
    dead time.  A fixed seed makes every condition share the same true events.
    """

    if config.source_model.kind is not SourceModelKind.CORRELATED:
        raise ValueError("Waveform alpha validation requires source_model.kind='correlated'.")
    if config.observation.mode.value != "fixed_duration":
        raise ValueError("Waveform alpha validation requires fixed_duration observation.")
    if duration_s is not None and duration_s <= 0:
        raise ValueError("duration_s must be positive when provided.")
    if true_rate_cps is not None and true_rate_cps <= 0:
        raise ValueError("true_rate_cps must be positive when provided.")
    if alpha_s_inv is not None and alpha_s_inv <= 0:
        raise ValueError("alpha_s_inv must be positive when provided.")

    paired_input = _paired_base_config(
        config,
        duration_s=duration_s,
        true_rate_cps=true_rate_cps,
        alpha_s_inv=alpha_s_inv,
        sample_rate_hz=sample_rate_hz,
        seed=seed,
    )
    base = _derived_config(
        paired_input,
        noise_enabled=paired_input.noise.enabled,
        dead_time_mode="none",
        dead_time_s=0.0,
        duration_s=None,
    )
    simulation = prepare_waveform_simulation(
        base,
        max_expected_events=max_expected_events,
        max_waveform_samples=max_waveform_samples,
    )
    true_events = simulation.true_events.events
    alpha_true = float(base.source_model.alpha.value)
    direct_analysis = analyze_event_noise(
        true_events["t_s"],
        float(base.observation.duration_s.value),
        bootstrap_replicates=bootstrap_replicates,
        seed=int(base.metadata.seed.value) + 911,
    )
    reference, _ = _condition_result(
        "G0_event_time_reference",
        true_events,
        true_events["t_s"],
        base,
        alpha_true,
        bootstrap_replicates=bootstrap_replicates,
    )
    analyses: dict[str, NoiseAnalysis] = {"G0_event_time_reference": direct_analysis}
    conditions: list[WaveformAlphaCondition] = []
    for name, noise_enabled, dead_mode, dead_s in _CONDITIONS:
        condition_config = _derived_config(
            paired_input,
            noise_enabled=noise_enabled,
            dead_time_mode=dead_mode,
            dead_time_s=dead_s,
            duration_s=None,
        )
        candidates = collect_waveform_candidates(
            simulation,
            condition_config,
            algorithm=trigger_algorithm,
            derivative_threshold_V=derivative_threshold_V,
            derivative_delay_s=derivative_delay_s,
            derivative_smoothing_s=derivative_smoothing_s,
        )
        result, analysis = _condition_result(
            name,
            true_events,
            candidates,
            condition_config,
            alpha_true,
            bootstrap_replicates=bootstrap_replicates,
        )
        conditions.append(result)
        analyses[name] = analysis

    reference_errors = (
        reference.alpha_rossi_rel_error,
        reference.alpha_feynman_rel_error,
        reference.alpha_psd_rel_error,
    )
    ideal = conditions[0]
    ideal_errors = (
        ideal.alpha_rossi_rel_error,
        ideal.alpha_feynman_rel_error,
        ideal.alpha_psd_rel_error,
    )
    return (
        WaveformAlphaValidationResult(
            alpha_true_s_inv=alpha_true,
            duration_s=float(base.observation.duration_s.value),
            true_event_count=int(true_events.shape[0]),
            shared_truth_seed=int(base.metadata.seed.value),
            reference=reference,
            conditions=tuple(conditions),
            pairwise_comparisons=tuple(_paired_comparison(reference, item) for item in conditions),
            alpha_tolerance_rel=alpha_tolerance_rel,
            passed_reference_and_ideal=bool(
                max(reference_errors + ideal_errors) <= alpha_tolerance_rel
            ),
            trigger_algorithm=trigger_algorithm,
            trigger_settings={
                "derivative_threshold_V": derivative_threshold_V,
                "derivative_delay_s": derivative_delay_s,
                "derivative_smoothing_s": derivative_smoothing_s,
            },
        ),
        analyses,
    )


def write_waveform_alpha_report(
    result: WaveformAlphaValidationResult,
    analyses: dict[str, NoiseAnalysis],
    output_dir: str | Path,
) -> dict[str, Path]:
    """Write JSON plus compact paper-ready diagnostic figures."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    json_path = output / "waveform_alpha_validation.json"
    json_path.write_text(json.dumps(result.to_dict(), indent=2, allow_nan=False), encoding="utf-8")

    labels = (result.reference.name,) + tuple(item.name for item in result.conditions)
    values = (result.reference,) + result.conditions
    figures: dict[str, Path] = {"json": json_path}
    parity = output / "waveform_alpha_parity.png"
    methods = ("Rossi-α", "Feynman-α", "PSD")
    estimates = np.asarray(
        [
            estimate
            for item in values
            for estimate in (item.alpha_rossi_s_inv, item.alpha_feynman_s_inv, item.alpha_psd_s_inv)
        ],
        dtype=np.float64,
    )
    deviations = np.asarray(
        [0.0] * estimates.size,
        dtype=np.float64,
    )
    parity_figure = phase_b_alpha_parity_figure(
        np.full(estimates.size, result.alpha_true_s_inv, dtype=np.float64),
        estimates,
        deviations,
        [method for _ in labels for method in methods],
    )
    parity_figure.savefig(parity, dpi=160)
    figures["parity"] = parity
    comparison = output / "waveform_vs_event_pairwise.png"
    pairwise = np.asarray(
        [
            (
                item.rossi_relative_to_event,
                item.feynman_relative_to_event,
                item.psd_relative_to_event,
            )
            for item in result.pairwise_comparisons
        ],
        dtype=np.float64,
    )
    comparison_figure = waveform_event_pairwise_figure(
        [item.condition for item in result.pairwise_comparisons],
        pairwise,
        methods,
    )
    comparison_figure.savefig(comparison, dpi=160)
    figures["pairwise"] = comparison
    final_analysis = analyses["G3_noisy_waveform_deadtime"]
    fit_figures = {
        "rossi": phase_b_rossi_figure(
            final_analysis.rossi.x,
            final_analysis.rossi.observed,
            final_analysis.rossi.fitted,
            final_analysis.rossi.fit.alpha_per_s,
            result.alpha_true_s_inv,
            final_analysis.rossi.fit.amplitude,
            final_analysis.rossi.fit.baseline,
        ),
        "feynman": phase_b_feynman_figure(
            final_analysis.feynman.x,
            final_analysis.feynman.observed,
            final_analysis.feynman.fitted,
            final_analysis.feynman.fit.alpha_per_s,
            result.alpha_true_s_inv,
            final_analysis.feynman.fit.amplitude,
        ),
        "psd": phase_b_psd_figure(
            final_analysis.psd.x,
            final_analysis.psd.observed,
            final_analysis.psd.fitted,
            final_analysis.psd.fit.alpha_per_s,
            result.alpha_true_s_inv,
            final_analysis.psd.fit.amplitude,
        ),
    }
    for key, figure in fit_figures.items():
        path = output / f"waveform_{key}_fit.png"
        figure.savefig(path, dpi=160)
        figures[key] = path
    return figures
