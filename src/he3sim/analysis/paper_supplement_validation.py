"""Pre-registered diagnostics needed by the software-only manuscript.

This module contains two deliberately separate experiments:

1. a high-count-rate waveform diagnostic that distinguishes linear pulse
   superposition from clipping/ADC/trigger distortion; and
2. a development/holdout Feynman-alpha gate-width scan that prevents selecting
   a gate range on the same realizations used to support the final claim.

All configurations remain ``synthetic_demo``.  The high-rate experiment does
not model space charge, physical preamplifier recovery, or any other measured
detector nonlinearity.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import numpy.typing as npt

from he3sim.acquisition.dead_time import apply_dead_time
from he3sim.acquisition.trigger import ThresholdTrigger
from he3sim.analysis.noise import feynman_alpha
from he3sim.config import He3SimConfig, SourceModelKind, config_hash
from he3sim.physics.pulse_models import double_exponential_peak_time_s
from he3sim.synthesis.renderers import render_direct_sparse_block
from he3sim.synthesis.streaming import iter_waveform_blocks, prepare_waveform_simulation


@dataclass(frozen=True, slots=True)
class HighRateProtocol:
    """Frozen design and thresholds for the high-rate diagnostic."""

    rates_cps: tuple[float, ...] = (1.0e3, 1.0e4, 1.0e5, 1.0e6, 1.0e7)
    durations_s: tuple[float, ...] = (0.1, 0.1, 0.05, 0.01, 0.002)
    seeds: tuple[int, ...] = (2026082501, 2026082502, 2026082503)
    overlap_tail_multiples: float = 5.0
    maximum_overlap_fraction: float = 0.10
    maximum_peak_bias_p90: float = 0.10
    maximum_clipping_nrmse: float = 0.01
    maximum_saturation_fraction: float = 0.001
    minimum_trigger_efficiency: float = 0.95
    maximum_false_trigger_fraction: float = 0.05
    linearity_reference_samples: int = 5_000
    peak_shift_event_cap: int = 512

    def __post_init__(self) -> None:
        if len(self.rates_cps) != len(self.durations_s):
            raise ValueError("rates_cps and durations_s must have identical lengths")
        if any(rate <= 0.0 for rate in self.rates_cps):
            raise ValueError("high-rate protocol rates must be positive")
        if any(duration <= 0.0 for duration in self.durations_s):
            raise ValueError("high-rate protocol durations must be positive")


@dataclass(frozen=True, slots=True)
class HighRatePoint:
    """Metrics for one rate and seed realization."""

    true_rate_cps: float
    duration_s: float
    seed: int
    true_event_count: int
    overlap_load_rate_tau: float
    overlap_fraction: float
    preclip_peak_V: float
    clipped_peak_V: float
    peak_bias_median_abs: float
    peak_bias_p90_abs: float
    peak_time_shift_median_us: float
    linear_renderer_nrmse: float
    clipping_nrmse: float
    adc_quantization_nrmse: float
    saturation_fraction: float
    trigger_candidate_count: int
    trigger_efficiency: float
    false_trigger_fraction: float
    within_applicability_limits: bool


@dataclass(frozen=True, slots=True)
class HighRateSummary:
    """Aggregate applicability boundary across fixed rate points."""

    protocol: HighRateProtocol
    points: tuple[HighRatePoint, ...]
    rate_summaries: tuple[dict[str, Any], ...]
    maximum_usable_rate_cps: float | None
    interpretation: str = (
        "Boundary of the configured synthetic linear-superposition, clipping, ADC, "
        "and trigger chain; not a validated physical He-3 nonlinearity boundary."
    )


@dataclass(frozen=True, slots=True)
class FeynmanGateProtocol:
    """Frozen development/holdout protocol for gate-width selection."""

    alpha_true_s_inv: float = 1_000.0
    true_rate_cps: float = 3_000.0
    duration_s: float = 0.5
    sample_rate_hz: float = 100_000_000.0
    dead_time_s: float = 4.0e-6
    development_seeds: tuple[int, ...] = (
        2026082511,
        2026082512,
        2026082513,
        2026082514,
    )
    holdout_seeds: tuple[int, ...] = (
        2026082521,
        2026082522,
        2026082523,
        2026082524,
        2026082525,
        2026082526,
        2026082527,
        2026082528,
    )
    candidate_alpha_t_ranges: tuple[tuple[str, float, float], ...] = (
        ("baseline_20us_10ms", 0.02, 10.0),
        ("trim_0p05_to_8", 0.05, 8.0),
        ("trim_0p10_to_8", 0.10, 8.0),
        ("trim_0p20_to_8", 0.20, 8.0),
        ("focus_0p05_to_5", 0.05, 5.0),
        ("focus_0p10_to_5", 0.10, 5.0),
    )
    gates_per_candidate: int = 32
    required_relative_median_error_reduction: float = 0.20
    required_improved_holdout_fraction: float = 0.75
    required_bootstrap_ci_lower_s_inv: float = 0.0
    accuracy_tolerance_rel: float = 0.05
    paired_bootstrap_replicates: int = 10_000
    paired_bootstrap_seed: int = 2026082599

    def __post_init__(self) -> None:
        if set(self.development_seeds) & set(self.holdout_seeds):
            raise ValueError("development and holdout seeds must be disjoint")
        if self.gates_per_candidate < 8:
            raise ValueError("each gate candidate requires at least eight widths")


@dataclass(frozen=True, slots=True)
class FeynmanGateFitPoint:
    """One Feynman-alpha fit produced under a fixed gate strategy."""

    split: str
    seed: int
    strategy: str
    event_count: int
    alpha_hat_s_inv: float
    relative_error: float
    r_squared: float
    minimum_gate_s: float
    maximum_gate_s: float


@dataclass(frozen=True, slots=True)
class FeynmanGateSummary:
    """Selection and untouched-holdout comparison for Feynman gate widths."""

    protocol: FeynmanGateProtocol
    selected_strategy: str
    development_scores: tuple[dict[str, Any], ...]
    development_points: tuple[FeynmanGateFitPoint, ...]
    holdout_points: tuple[FeynmanGateFitPoint, ...]
    baseline_median_relative_error: float
    selected_median_relative_error: float
    relative_median_error_reduction: float
    improved_holdout_fraction: float
    paired_improvement_median_s_inv: float
    paired_improvement_ci95_s_inv: tuple[float, float]
    selected_meets_accuracy_tolerance: bool
    improvement_claim_supported: bool
    interpretation: str


@dataclass(frozen=True, slots=True)
class PaperSupplementResult:
    """Combined result for the two manuscript supplement experiments."""

    base_config_hash: str
    protocol_sha256: str
    high_rate: HighRateSummary
    feynman_gate: FeynmanGateSummary
    scope: str = (
        "synthetic_demo software verification only; no physical detector or reactor "
        "calibration is claimed"
    )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation."""

        return asdict(self)


def _override_config(
    config: He3SimConfig,
    *,
    true_rate_cps: float,
    duration_s: float,
    seed: int,
    sample_rate_hz: float | None = None,
    alpha_s_inv: float | None = None,
    noise_enabled: bool,
    dead_time_mode: str,
    dead_time_s: float,
) -> He3SimConfig:
    """Create one synthetic arm while preserving all documented parameter states."""

    if config.source_model.kind is not SourceModelKind.CORRELATED:
        raise ValueError("paper supplement validation requires a correlated source")
    raw = config.model_dump(mode="python")
    k_eff = float(raw["source_model"]["k_eff"]["value"])
    efficiency = float(raw["source_model"]["detection_efficiency"]["value"])
    raw["metadata"]["seed"]["value"] = seed
    raw["simulation"]["true_rate_cps"]["value"] = true_rate_cps
    if sample_rate_hz is not None:
        raw["simulation"]["sample_rate_hz"]["value"] = sample_rate_hz
    if alpha_s_inv is not None:
        raw["source_model"]["alpha"]["value"] = alpha_s_inv
    source_rate_cps = true_rate_cps * (1.0 - k_eff) / efficiency
    # Correct only round-off within a few ulps at the existing source-rate bounds.
    # Genuinely out-of-range configurations still fail the original validation.
    for boundary_cps in (10.0, 1.0e7):
        if math.isclose(source_rate_cps, boundary_cps, rel_tol=1e-15, abs_tol=0.0):
            source_rate_cps = boundary_cps
    raw["source_model"]["source_rate_cps"]["value"] = source_rate_cps
    raw["observation"]["mode"] = "fixed_duration"
    raw["observation"]["duration_s"]["value"] = duration_s
    raw["noise"]["enabled"] = noise_enabled
    raw["trigger"]["enabled"] = True
    raw["dead_time"]["mode"] = dead_time_mode
    raw["dead_time"]["duration_s"]["value"] = dead_time_s
    return He3SimConfig.model_validate(raw)


def _required_number(value: float | int | None, name: str) -> float:
    """Return a configured numeric value without inventing missing parameters."""

    if value is None:
        raise ValueError(f"{name} requires an explicit configured value")
    return float(value)


def _event_peak_indices(events: np.ndarray, sample_rate_hz: float) -> npt.NDArray[np.int64]:
    """Return the discrete sample where each isolated event reaches its target peak."""

    indices = np.empty(events.size, dtype=np.int64)
    for index, event in enumerate(events):
        event_time = float(event["t_s"])
        tau_r = float(event["tau_r_s"])
        tau_d = float(event["tau_d_s"])
        peak = event_time + double_exponential_peak_time_s(tau_r, tau_d)
        onset = math.ceil(event_time * sample_rate_hz)
        candidates = np.asarray(
            [
                onset,
                max(onset, math.floor(peak * sample_rate_hz)),
                math.ceil(peak * sample_rate_hz),
            ],
            dtype=np.int64,
        )
        delays = candidates / sample_rate_hz - event_time
        raw = np.exp(-delays / tau_d) - np.exp(-delays / tau_r)
        indices[index] = int(candidates[int(np.argmax(raw))])
    return indices


def _safe_nrmse(
    observed: npt.NDArray[np.float64],
    reference: npt.NDArray[np.float64],
) -> float:
    """Return RMS error normalized by reference RMS with a stable zero case."""

    denominator = float(np.sqrt(np.mean(np.square(reference))))
    numerator = float(np.sqrt(np.mean(np.square(observed - reference))))
    if denominator > 0.0:
        return numerator / denominator
    if numerator == 0.0:
        return 0.0
    raise ValueError("NRMSE is undefined for a zero reference with nonzero error")


def _overlap_fraction(times_s: npt.NDArray[np.float64], support_s: float) -> float:
    """Fraction of events with either neighbor inside the declared pulse support."""

    if times_s.size < 2:
        return 0.0
    gaps = np.diff(times_s)
    previous = np.concatenate(([np.inf], gaps))
    following = np.concatenate((gaps, [np.inf]))
    return float(np.mean(np.minimum(previous, following) < support_s))


def _trigger_metrics(
    candidates_s: npt.NDArray[np.float64],
    true_events: np.ndarray,
    config: He3SimConfig,
) -> tuple[float, float]:
    """Compute greedy one-to-one trigger efficiency and unmatched fraction.

    The dataset association table is intentionally many-to-many.  Reusing its
    unique truth IDs would overstate high-rate resolution because one broad
    event window can contain many piled-up events.  This diagnostic therefore
    consumes each truth event at most once.
    """

    if candidates_s.size == 0:
        return 0.0, 0.0
    event_times = true_events["t_s"]
    used = np.zeros(event_times.size, dtype=np.bool_)
    matched = 0
    unmatched = 0
    before_s = _required_number(config.trigger.pre_trigger_s.value, "pre_trigger_s")
    after_s = _required_number(config.trigger.post_trigger_s.value, "post_trigger_s")
    for trigger_s in candidates_s:
        start = int(np.searchsorted(event_times, trigger_s - before_s, side="left"))
        stop = int(np.searchsorted(event_times, trigger_s + after_s, side="right"))
        local = np.flatnonzero(~used[start:stop]) + start
        if local.size == 0:
            unmatched += 1
            continue
        nearest = int(local[int(np.argmin(np.abs(event_times[local] - trigger_s)))])
        used[nearest] = True
        matched += 1
    efficiency = matched / true_events.size if true_events.size else 0.0
    return float(efficiency), float(unmatched / candidates_s.size)


def _high_rate_point(
    base_config: He3SimConfig,
    protocol: HighRateProtocol,
    *,
    rate_cps: float,
    duration_s: float,
    seed: int,
    max_expected_events: int,
    max_waveform_samples: int,
) -> HighRatePoint:
    """Run one fixed high-rate diagnostic realization."""

    config = _override_config(
        base_config,
        true_rate_cps=rate_cps,
        duration_s=duration_s,
        seed=seed,
        noise_enabled=False,
        dead_time_mode="none",
        dead_time_s=0.0,
    )
    simulation = prepare_waveform_simulation(
        config,
        max_expected_events=max_expected_events,
        max_waveform_samples=max_waveform_samples,
    )
    trigger = ThresholdTrigger(
        sample_rate_hz=simulation.sample_rate_hz,
        polarity=int(_required_number(config.trigger.polarity.value, "trigger polarity")),
        threshold_V=_required_number(config.trigger.threshold_V.value, "trigger threshold"),
        hysteresis_V=_required_number(config.trigger.hysteresis_V.value, "trigger hysteresis"),
        min_hold_s=_required_number(config.trigger.min_hold_s.value, "trigger hold time"),
    )
    trigger_state = None
    preclip_chunks: list[npt.NDArray[np.float32]] = []
    clipped_chunks: list[npt.NDArray[np.float32]] = []
    adc_chunks: list[npt.NDArray[np.uint16]] = []
    saturation_count = 0
    sample_count = 0
    candidate_chunks: list[npt.NDArray[np.int64]] = []
    for block in iter_waveform_blocks(simulation, config):
        if block.preclip_analog_samples_V is None or block.analog_samples_V is None:
            raise RuntimeError("high-rate diagnostics require saved analog samples")
        preclip_chunks.append(block.preclip_analog_samples_V)
        clipped_chunks.append(block.analog_samples_V)
        if block.adc_samples is not None:
            adc_chunks.append(block.adc_samples)
        if block.saturation_mask is not None:
            saturation_count += int(np.count_nonzero(block.saturation_mask))
        sample_count += int(block.analog_samples_V.size)
        indices, trigger_state = trigger.process_block(
            block.analog_samples_V,
            block.sample_index_start,
            trigger_state,
        )
        if indices.size:
            candidate_chunks.append(indices)

    preclip = np.concatenate(preclip_chunks).astype(np.float64, copy=False)
    clipped = np.concatenate(clipped_chunks).astype(np.float64, copy=False)
    candidates = (
        np.concatenate(candidate_chunks).astype(np.float64) / simulation.sample_rate_hz
        if candidate_chunks
        else np.empty(0, dtype=np.float64)
    )
    events = simulation.true_events.events
    baseline = (
        _required_number(config.baseline.offset_V.value, "baseline offset")
        if config.baseline.enabled
        else 0.0
    )
    signal_reference = preclip - baseline
    clipping_nrmse = _safe_nrmse(clipped - baseline, signal_reference)
    adc_nrmse = 0.0
    if adc_chunks:
        adc = np.concatenate(adc_chunks).astype(np.float64)
        bits = int(_required_number(config.adc.bits.value, "ADC bits"))
        low = _required_number(config.adc.input_min_V.value, "ADC input minimum")
        high = _required_number(config.adc.input_max_V.value, "ADC input maximum")
        offset = _required_number(config.adc.offset_V.value, "ADC offset")
        reconstructed = low + adc * (high - low) / ((1 << bits) - 1) - offset
        adc_nrmse = _safe_nrmse(reconstructed - baseline, clipped - baseline)

    reference_count = min(protocol.linearity_reference_samples, preclip.size)
    direct = render_direct_sparse_block(
        events,
        0,
        reference_count,
        simulation.sample_rate_hz,
    )
    linear_renderer_nrmse = _safe_nrmse(
        signal_reference[:reference_count],
        direct,
    )

    peak_indices = _event_peak_indices(events, simulation.sample_rate_hz)
    valid = peak_indices < preclip.size
    peak_indices = peak_indices[valid]
    valid_events = events[valid]
    ideal_peaks = valid_events["amplitude_peak_V"].astype(np.float64) * valid_events[
        "polarity"
    ].astype(np.float64)
    measured_peaks = preclip[peak_indices] - baseline
    peak_bias = np.abs((measured_peaks - ideal_peaks) / np.abs(ideal_peaks))

    peak_shift_us: list[float] = []
    if valid_events.size:
        selected = np.linspace(
            0,
            valid_events.size - 1,
            min(protocol.peak_shift_event_cap, valid_events.size),
            dtype=np.int64,
        )
        for event_index in selected:
            event = valid_events[event_index]
            onset = int(math.ceil(float(event["t_s"]) * simulation.sample_rate_hz))
            stop = min(
                preclip.size,
                onset
                + max(
                    3,
                    int(
                        math.ceil(
                            protocol.overlap_tail_multiples
                            * float(event["tau_d_s"])
                            * simulation.sample_rate_hz
                        )
                    ),
                ),
            )
            if stop <= onset:
                continue
            local_peak = onset + int(np.argmax(preclip[onset:stop]))
            shift = abs(local_peak - int(peak_indices[event_index])) / simulation.sample_rate_hz
            peak_shift_us.append(shift * 1.0e6)

    tau_d_s = _required_number(config.pulse_shape.tau_d_s.value, "pulse tau_d")
    support_s = protocol.overlap_tail_multiples * tau_d_s
    trigger_efficiency, false_fraction = _trigger_metrics(candidates, events, config)
    overlap_fraction = _overlap_fraction(events["t_s"], support_s)
    p90_bias = float(np.quantile(peak_bias, 0.90)) if peak_bias.size else float("nan")
    saturation_fraction = saturation_count / sample_count if sample_count else 0.0
    within = bool(
        overlap_fraction <= protocol.maximum_overlap_fraction
        and p90_bias <= protocol.maximum_peak_bias_p90
        and clipping_nrmse <= protocol.maximum_clipping_nrmse
        and saturation_fraction <= protocol.maximum_saturation_fraction
        and trigger_efficiency >= protocol.minimum_trigger_efficiency
        and false_fraction <= protocol.maximum_false_trigger_fraction
    )
    return HighRatePoint(
        true_rate_cps=rate_cps,
        duration_s=duration_s,
        seed=seed,
        true_event_count=int(events.size),
        overlap_load_rate_tau=rate_cps * tau_d_s,
        overlap_fraction=overlap_fraction,
        preclip_peak_V=float(np.max(np.abs(preclip - baseline))),
        clipped_peak_V=float(np.max(np.abs(clipped - baseline))),
        peak_bias_median_abs=float(np.median(peak_bias)) if peak_bias.size else float("nan"),
        peak_bias_p90_abs=p90_bias,
        peak_time_shift_median_us=(
            float(np.median(peak_shift_us)) if peak_shift_us else float("nan")
        ),
        linear_renderer_nrmse=linear_renderer_nrmse,
        clipping_nrmse=clipping_nrmse,
        adc_quantization_nrmse=adc_nrmse,
        saturation_fraction=saturation_fraction,
        trigger_candidate_count=int(candidates.size),
        trigger_efficiency=trigger_efficiency,
        false_trigger_fraction=false_fraction,
        within_applicability_limits=within,
    )


def run_high_rate_diagnostic(
    config: He3SimConfig,
    protocol: HighRateProtocol | None = None,
    *,
    max_expected_events: int = 100_000,
    max_waveform_samples: int = 20_000_000,
) -> HighRateSummary:
    """Run the pre-registered rate-by-seed grid and derive a conservative boundary."""

    design = protocol or HighRateProtocol()
    points = tuple(
        _high_rate_point(
            config,
            design,
            rate_cps=rate,
            duration_s=duration,
            seed=seed,
            max_expected_events=max_expected_events,
            max_waveform_samples=max_waveform_samples,
        )
        for rate, duration in zip(design.rates_cps, design.durations_s, strict=True)
        for seed in design.seeds
    )
    summaries: list[dict[str, Any]] = []
    usable_rates: list[float] = []
    contiguous = True
    for rate in design.rates_cps:
        selected = [point for point in points if point.true_rate_cps == rate]
        all_pass = all(point.within_applicability_limits for point in selected)
        summaries.append(
            {
                "true_rate_cps": rate,
                "replicates": len(selected),
                "all_seeds_within_limits": all_pass,
                "median_overlap_fraction": float(
                    np.median([point.overlap_fraction for point in selected])
                ),
                "median_peak_bias_p90_abs": float(
                    np.median([point.peak_bias_p90_abs for point in selected])
                ),
                "median_saturation_fraction": float(
                    np.median([point.saturation_fraction for point in selected])
                ),
                "median_trigger_efficiency": float(
                    np.median([point.trigger_efficiency for point in selected])
                ),
            }
        )
        if contiguous and all_pass:
            usable_rates.append(rate)
        else:
            # The paper boundary is the contiguous region from the lowest rate.
            contiguous = False
    maximum = usable_rates[-1] if usable_rates else None
    return HighRateSummary(
        protocol=design,
        points=points,
        rate_summaries=tuple(summaries),
        maximum_usable_rate_cps=maximum,
    )


def _gate_widths(
    protocol: FeynmanGateProtocol,
    strategy: tuple[str, float, float],
) -> npt.NDArray[np.float64]:
    """Convert a frozen dimensionless alpha-T range into physical gate widths."""

    _, lower_alpha_t, upper_alpha_t = strategy
    lower = lower_alpha_t / protocol.alpha_true_s_inv
    upper = min(upper_alpha_t / protocol.alpha_true_s_inv, protocol.duration_s / 20.0)
    if upper <= lower:
        raise ValueError("gate strategy is incompatible with duration and alpha")
    return np.geomspace(lower, upper, protocol.gates_per_candidate)


def _waveform_observed_times(
    config: He3SimConfig,
    protocol: FeynmanGateProtocol,
    seed: int,
    *,
    max_expected_events: int,
    max_waveform_samples: int,
) -> npt.NDArray[np.float64]:
    """Render the frozen noisy/dead-time waveform arm for one seed."""

    arm = _override_config(
        config,
        true_rate_cps=protocol.true_rate_cps,
        duration_s=protocol.duration_s,
        seed=seed,
        sample_rate_hz=protocol.sample_rate_hz,
        alpha_s_inv=protocol.alpha_true_s_inv,
        noise_enabled=True,
        dead_time_mode="nonparalyzable",
        dead_time_s=protocol.dead_time_s,
    )
    simulation = prepare_waveform_simulation(
        arm,
        max_expected_events=max_expected_events,
        max_waveform_samples=max_waveform_samples,
    )
    trigger = ThresholdTrigger(
        sample_rate_hz=protocol.sample_rate_hz,
        polarity=int(_required_number(arm.trigger.polarity.value, "trigger polarity")),
        threshold_V=_required_number(arm.trigger.threshold_V.value, "trigger threshold"),
        hysteresis_V=_required_number(arm.trigger.hysteresis_V.value, "trigger hysteresis"),
        min_hold_s=_required_number(arm.trigger.min_hold_s.value, "trigger hold time"),
    )
    state = None
    chunks: list[npt.NDArray[np.int64]] = []
    for block in iter_waveform_blocks(simulation, arm):
        if block.analog_samples_V is None:
            raise RuntimeError("Feynman gate scan requires analog waveform samples")
        indices, state = trigger.process_block(
            block.analog_samples_V,
            block.sample_index_start,
            state,
        )
        if indices.size:
            chunks.append(indices)
    candidates = (
        np.concatenate(chunks).astype(np.float64) / protocol.sample_rate_hz
        if chunks
        else np.empty(0, dtype=np.float64)
    )
    dead = apply_dead_time(candidates, protocol.dead_time_s, arm.dead_time.mode)
    return candidates[dead.accepted]


def _feynman_fit_point(
    times_s: npt.NDArray[np.float64],
    protocol: FeynmanGateProtocol,
    *,
    split: str,
    seed: int,
    strategy: tuple[str, float, float],
) -> FeynmanGateFitPoint:
    """Fit one frozen gate strategy to one observed realization."""

    gates = _gate_widths(protocol, strategy)
    curve = feynman_alpha(
        times_s,
        protocol.duration_s,
        gate_widths_s=gates,
    )
    estimate = float(curve.fit.alpha_per_s)
    return FeynmanGateFitPoint(
        split=split,
        seed=seed,
        strategy=strategy[0],
        event_count=int(times_s.size),
        alpha_hat_s_inv=estimate,
        relative_error=abs(estimate / protocol.alpha_true_s_inv - 1.0),
        r_squared=float(curve.fit.r_squared),
        minimum_gate_s=float(gates[0]),
        maximum_gate_s=float(gates[-1]),
    )


def _paired_bootstrap_ci(
    improvements_s_inv: npt.NDArray[np.float64],
    protocol: FeynmanGateProtocol,
) -> tuple[float, float]:
    """Bootstrap the median paired absolute-error improvement across holdout seeds."""

    rng = np.random.default_rng(protocol.paired_bootstrap_seed)
    indices = rng.integers(
        0,
        improvements_s_inv.size,
        size=(protocol.paired_bootstrap_replicates, improvements_s_inv.size),
    )
    medians = np.median(improvements_s_inv[indices], axis=1)
    low, high = np.quantile(medians, [0.025, 0.975])
    return float(low), float(high)


def run_feynman_gate_validation(
    config: He3SimConfig,
    protocol: FeynmanGateProtocol | None = None,
    *,
    max_expected_events: int = 100_000,
    max_waveform_samples: int = 60_000_000,
) -> FeynmanGateSummary:
    """Select on development seeds, freeze, then evaluate only on holdout seeds."""

    design = protocol or FeynmanGateProtocol()
    development: list[FeynmanGateFitPoint] = []
    for seed in design.development_seeds:
        times = _waveform_observed_times(
            config,
            design,
            seed,
            max_expected_events=max_expected_events,
            max_waveform_samples=max_waveform_samples,
        )
        development.extend(
            _feynman_fit_point(
                times,
                design,
                split="development",
                seed=seed,
                strategy=strategy,
            )
            for strategy in design.candidate_alpha_t_ranges
        )

    scores: list[dict[str, Any]] = []
    for strategy in design.candidate_alpha_t_ranges:
        development_subset = [point for point in development if point.strategy == strategy[0]]
        scores.append(
            {
                "strategy": strategy[0],
                "median_relative_error": float(
                    np.median([point.relative_error for point in development_subset])
                ),
                "mean_relative_error": float(
                    np.mean([point.relative_error for point in development_subset])
                ),
                "median_r_squared": float(
                    np.median([point.r_squared for point in development_subset])
                ),
            }
        )
    ranked = sorted(
        scores,
        key=lambda item: (
            item["median_relative_error"],
            item["mean_relative_error"],
            -item["median_r_squared"],
            item["strategy"],
        ),
    )
    selected_name = str(ranked[0]["strategy"])
    strategy_by_name = {item[0]: item for item in design.candidate_alpha_t_ranges}
    baseline_strategy = strategy_by_name["baseline_20us_10ms"]
    selected_strategy = strategy_by_name[selected_name]

    holdout: list[FeynmanGateFitPoint] = []
    for seed in design.holdout_seeds:
        times = _waveform_observed_times(
            config,
            design,
            seed,
            max_expected_events=max_expected_events,
            max_waveform_samples=max_waveform_samples,
        )
        holdout.append(
            _feynman_fit_point(
                times,
                design,
                split="holdout",
                seed=seed,
                strategy=baseline_strategy,
            )
        )
        if selected_name != baseline_strategy[0]:
            holdout.append(
                _feynman_fit_point(
                    times,
                    design,
                    split="holdout",
                    seed=seed,
                    strategy=selected_strategy,
                )
            )

    baseline = {point.seed: point for point in holdout if point.strategy == baseline_strategy[0]}
    selected = {point.seed: point for point in holdout if point.strategy == selected_name}
    if selected_name == baseline_strategy[0]:
        selected = baseline
    baseline_errors = np.asarray(
        [baseline[seed].relative_error for seed in design.holdout_seeds],
        dtype=np.float64,
    )
    selected_errors = np.asarray(
        [selected[seed].relative_error for seed in design.holdout_seeds],
        dtype=np.float64,
    )
    baseline_median = float(np.median(baseline_errors))
    selected_median = float(np.median(selected_errors))
    reduction = (
        (baseline_median - selected_median) / baseline_median if baseline_median > 0.0 else 0.0
    )
    absolute_improvements = (baseline_errors - selected_errors) * design.alpha_true_s_inv
    improved_fraction = float(np.mean(selected_errors < baseline_errors))
    ci95 = _paired_bootstrap_ci(absolute_improvements, design)
    accuracy_met = selected_median <= design.accuracy_tolerance_rel
    claim_supported = bool(
        selected_name != baseline_strategy[0]
        and reduction >= design.required_relative_median_error_reduction
        and improved_fraction >= design.required_improved_holdout_fraction
        and ci95[0] > design.required_bootstrap_ci_lower_s_inv
    )
    if claim_supported and accuracy_met:
        interpretation = (
            "The frozen gate strategy improved holdout Feynman-alpha recovery and met "
            "the pre-registered accuracy tolerance."
        )
    elif claim_supported:
        interpretation = (
            "The frozen gate strategy improved holdout recovery, but the absolute "
            "accuracy tolerance was not met."
        )
    else:
        interpretation = (
            "The pre-registered holdout criteria do not support claiming that gate-width "
            "adjustment improves waveform-triggered Feynman-alpha recovery."
        )
    return FeynmanGateSummary(
        protocol=design,
        selected_strategy=selected_name,
        development_scores=tuple(scores),
        development_points=tuple(development),
        holdout_points=tuple(holdout),
        baseline_median_relative_error=baseline_median,
        selected_median_relative_error=selected_median,
        relative_median_error_reduction=float(reduction),
        improved_holdout_fraction=improved_fraction,
        paired_improvement_median_s_inv=float(np.median(absolute_improvements)),
        paired_improvement_ci95_s_inv=ci95,
        selected_meets_accuracy_tolerance=accuracy_met,
        improvement_claim_supported=claim_supported,
        interpretation=interpretation,
    )


def preregistered_protocol_payload(
    high_rate: HighRateProtocol | None = None,
    feynman_gate: FeynmanGateProtocol | None = None,
) -> dict[str, Any]:
    """Return the complete protocol that must be written before execution."""

    return {
        "protocol_version": "1.0",
        "frozen_before_result_inspection": True,
        "high_rate": asdict(high_rate or HighRateProtocol()),
        "feynman_gate": asdict(feynman_gate or FeynmanGateProtocol()),
        "scope": (
            "synthetic_demo; physical space-charge and preamplifier recovery "
            "nonlinearities are outside this experiment"
        ),
    }


def protocol_sha256(payload: dict[str, Any]) -> str:
    """Hash the frozen protocol using a canonical JSON representation."""

    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def run_paper_supplement_validation(
    config: He3SimConfig,
    high_rate_protocol: HighRateProtocol | None = None,
    feynman_protocol: FeynmanGateProtocol | None = None,
) -> PaperSupplementResult:
    """Execute both pre-registered manuscript supplement experiments."""

    protocol_payload = preregistered_protocol_payload(high_rate_protocol, feynman_protocol)
    return PaperSupplementResult(
        base_config_hash=config_hash(config),
        protocol_sha256=protocol_sha256(protocol_payload),
        high_rate=run_high_rate_diagnostic(config, high_rate_protocol),
        feynman_gate=run_feynman_gate_validation(config, feynman_protocol),
    )


def _write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    """Write a stable UTF-8 CSV table."""

    if not rows:
        return
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_paper_supplement_report(
    result: PaperSupplementResult,
    output_dir: str | Path,
) -> dict[str, Path]:
    """Write JSON, CSV tables, and two paper-oriented diagnostic figures."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    result_json = output / "paper_supplement_validation.json"
    result_json.write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    high_rate_csv = output / "high_rate_diagnostic.csv"
    _write_rows(high_rate_csv, [asdict(point) for point in result.high_rate.points])
    gate_csv = output / "feynman_gate_scan.csv"
    _write_rows(
        gate_csv,
        [asdict(point) for point in result.feynman_gate.development_points]
        + [asdict(point) for point in result.feynman_gate.holdout_points],
    )

    rate_rows = list(result.high_rate.rate_summaries)
    rates = np.asarray([row["true_rate_cps"] for row in rate_rows], dtype=np.float64)
    fig, axes = plt.subplots(2, 2, figsize=(10.0, 7.0), constrained_layout=True)
    axes[0, 0].plot(
        rates,
        [row["median_overlap_fraction"] * 100.0 for row in rate_rows],
        "o-",
    )
    axes[0, 0].axhline(
        result.high_rate.protocol.maximum_overlap_fraction * 100.0,
        color="black",
        linestyle="--",
    )
    axes[0, 0].set_ylabel("Overlapping events (%)")
    axes[0, 1].plot(
        rates,
        [row["median_peak_bias_p90_abs"] * 100.0 for row in rate_rows],
        "o-",
    )
    axes[0, 1].axhline(
        result.high_rate.protocol.maximum_peak_bias_p90 * 100.0,
        color="black",
        linestyle="--",
    )
    axes[0, 1].set_ylabel("Peak bias P90 (%)")
    axes[1, 0].plot(
        rates,
        [row["median_saturation_fraction"] * 100.0 for row in rate_rows],
        "o-",
    )
    axes[1, 0].set_ylabel("Saturated samples (%)")
    axes[1, 1].plot(
        rates,
        [row["median_trigger_efficiency"] * 100.0 for row in rate_rows],
        "o-",
    )
    axes[1, 1].axhline(
        result.high_rate.protocol.minimum_trigger_efficiency * 100.0,
        color="black",
        linestyle="--",
    )
    axes[1, 1].set_ylabel("Matched trigger efficiency (%)")
    for axis in axes.ravel():
        axis.set_xscale("log")
        axis.set_xlabel("Nominal true count rate (cps)")
        axis.grid(alpha=0.25)
    high_rate_figure = output / "high_rate_applicability_boundary.png"
    fig.savefig(high_rate_figure, dpi=180)
    plt.close(fig)

    scores = sorted(
        result.feynman_gate.development_scores,
        key=lambda row: row["median_relative_error"],
    )
    fig, axes = plt.subplots(1, 2, figsize=(11.0, 4.5), constrained_layout=True)
    axes[0].barh(
        [str(row["strategy"]) for row in scores],
        [float(row["median_relative_error"]) * 100.0 for row in scores],
    )
    axes[0].set_xlabel("Development median alpha relative error (%)")
    axes[0].invert_yaxis()
    baseline = {
        point.seed: point.relative_error
        for point in result.feynman_gate.holdout_points
        if point.strategy == "baseline_20us_10ms"
    }
    selected = {
        point.seed: point.relative_error
        for point in result.feynman_gate.holdout_points
        if point.strategy == result.feynman_gate.selected_strategy
    }
    for seed in result.feynman_gate.protocol.holdout_seeds:
        axes[1].plot(
            [0, 1],
            [baseline[seed] * 100.0, selected.get(seed, baseline[seed]) * 100.0],
            "o-",
            alpha=0.7,
        )
    axes[1].set_xticks([0, 1], ["Baseline gates", "Frozen gates"])
    axes[1].set_ylabel("Holdout alpha relative error (%)")
    axes[1].grid(axis="y", alpha=0.25)
    gate_figure = output / "feynman_gate_holdout_comparison.png"
    fig.savefig(gate_figure, dpi=180)
    plt.close(fig)
    return {
        "json": result_json,
        "high_rate_csv": high_rate_csv,
        "gate_csv": gate_csv,
        "high_rate_figure": high_rate_figure,
        "gate_figure": gate_figure,
    }
