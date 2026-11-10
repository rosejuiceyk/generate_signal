"""Paired multi-condition event-level alpha-recovery pilot."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import yaml

from he3sim.analysis.noise import analyze_event_noise
from he3sim.config import He3SimConfig, SourceModelKind, config_hash
from he3sim.physics.events import simulate_true_events

DEFAULT_EXPECTED_EVENTS = 30_000
DEFAULT_SEEDS = (101, 203, 307, 401)
PILOT_SCENARIOS = (
    ("center", 1000.0, 3000.0, 0.70, 0.30),
    ("alpha_low", 500.0, 3000.0, 0.70, 0.30),
    ("alpha_high", 2000.0, 3000.0, 0.70, 0.30),
    ("rate_low", 1000.0, 1000.0, 0.70, 0.30),
    ("rate_high", 1000.0, 10_000.0, 0.70, 0.30),
    ("k_low", 1000.0, 3000.0, 0.30, 0.30),
    ("k_high", 1000.0, 3000.0, 0.85, 0.30),
    ("efficiency_low", 1000.0, 3000.0, 0.70, 0.15),
    ("efficiency_high", 1000.0, 3000.0, 0.70, 0.50),
    ("low_alpha_high_rate", 500.0, 10_000.0, 0.85, 0.15),
    ("high_alpha_low_rate", 2000.0, 1000.0, 0.30, 0.50),
    ("mixed_center", 1000.0, 10_000.0, 0.50, 0.50),
)
PHYSICS_CONSISTENT_K_VALUES = (0.30, 0.50, 0.70, 0.85)
PHYSICS_CONSISTENT_EXPECTED_EVENTS = {
    0.30: 100_000,
    0.50: 60_000,
    0.70: 30_000,
    0.85: 30_000,
}


@dataclass(frozen=True, slots=True)
class EventPrecisionPoint:
    scenario: str
    seed: int
    alpha_true_per_s: float
    true_rate_cps: float
    k_eff: float
    detection_efficiency: float
    duration_s: float
    event_count: int
    rossi_alpha_per_s: float
    feynman_alpha_per_s: float
    psd_alpha_per_s: float
    rossi_relative_error: float
    feynman_relative_error: float
    psd_relative_error: float
    configuration_hash: str


@dataclass(frozen=True, slots=True)
class EventPrecisionSummary:
    scenario: str
    replicate_count: int
    mean_absolute_relative_error: tuple[float, float, float]
    p90_absolute_relative_error: tuple[float, float, float]
    mean_inter_method_spread: float


@dataclass(frozen=True, slots=True)
class EventPrecisionPilot:
    expected_events_per_run: int
    seeds: tuple[int, ...]
    points: tuple[EventPrecisionPoint, ...]
    summaries: tuple[EventPrecisionSummary, ...]
    scope: str = "synthetic_demo; event-time generator consistency only"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def derive_alpha_from_k_eff(k_eff: float, prompt_generation_time_s: float) -> float:
    """Return the pure-prompt alpha coupled to ``k_eff`` by a fixed Lambda."""
    if not 0.0 < k_eff < 1.0:
        raise ValueError("k_eff must be strictly between zero and one")
    if prompt_generation_time_s <= 0.0:
        raise ValueError("prompt_generation_time_s must be positive")
    return (1.0 - k_eff) / prompt_generation_time_s


def physics_consistent_scenarios(
    *,
    baseline_k_eff: float = 0.85,
    baseline_alpha_per_s: float = 1_000.0,
    true_rate_cps: float = 3_000.0,
    detection_efficiency: float = 0.30,
) -> tuple[tuple[str, float, float, float, float, int], ...]:
    """Build the next pilot's alpha-coupled scenarios from one selected baseline."""
    generation_time_s = (1.0 - baseline_k_eff) / baseline_alpha_per_s
    return tuple(
        (
            f"physics_k_{k_eff:.2f}",
            derive_alpha_from_k_eff(k_eff, generation_time_s),
            true_rate_cps,
            k_eff,
            detection_efficiency,
            PHYSICS_CONSISTENT_EXPECTED_EVENTS[k_eff],
        )
        for k_eff in PHYSICS_CONSISTENT_K_VALUES
    )


def _scenario_config(
    base: He3SimConfig,
    alpha: float,
    rate: float,
    k_eff: float,
    efficiency: float,
    expected_events: int,
    seed: int,
) -> He3SimConfig:
    raw = base.model_dump(mode="python")
    raw["metadata"]["seed"]["value"] = seed
    raw["source_model"]["kind"] = "correlated"
    raw["source_model"]["alpha"]["value"] = alpha
    raw["source_model"]["k_eff"]["value"] = k_eff
    raw["source_model"]["detection_efficiency"]["value"] = efficiency
    raw["source_model"]["source_rate_cps"]["value"] = rate * (1.0 - k_eff) / efficiency
    # Near-critical synthetic chains can legitimately extend beyond the demo
    # configuration's 128 generations.  This remains a finite safety limit.
    raw["source_model"]["max_chain_generation"] = 1_024
    raw["simulation"]["true_rate_cps"]["value"] = rate
    raw["observation"]["mode"] = "fixed_duration"
    raw["observation"]["duration_s"] = {
        "value": expected_events / rate,
        "status": "synthetic_demo",
        "notes": "Event-precision pilot: common expected event count.",
    }
    raw["observation"].pop("target_event_count", None)
    raw["observation"].pop("min_duration_s", None)
    raw["observation"].pop("max_duration_s", None)
    return He3SimConfig.model_validate(raw)


def run_event_precision_pilot(
    base: He3SimConfig,
    *,
    expected_events: int = DEFAULT_EXPECTED_EVENTS,
    seeds: tuple[int, ...] = DEFAULT_SEEDS,
) -> EventPrecisionPilot:
    """Run the pre-registered 12-condition, event-time-only pilot."""
    if expected_events < 1_000:
        raise ValueError("expected_events must be at least 1,000 for this pilot")
    if not seeds:
        raise ValueError("at least one seed is required")
    scenarios = tuple((*item, expected_events) for item in PILOT_SCENARIOS)
    return _run_scenarios(base, scenarios, seeds)


def load_physics_consistent_scenarios(
    path: str | Path,
) -> tuple[tuple[tuple[str, float, float, float, float, int], ...], tuple[int, ...]]:
    """Load shared controls and derive alpha values from the YAML Lambda setting."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("physics-consistent experiment config must be a mapping")
    controls = raw["shared_controls"]
    generation_time_s = float(raw["prompt_generation_time_s"])
    rate = float(controls["true_rate_cps"])
    efficiency = float(controls["detection_efficiency"])
    scenarios = tuple(
        (
            f"physics_k_{float(item['k_eff']):.2f}",
            derive_alpha_from_k_eff(float(item["k_eff"]), generation_time_s),
            rate,
            float(item["k_eff"]),
            efficiency,
            int(item["expected_events"]),
        )
        for item in raw["scenarios"]
    )
    return scenarios, tuple(int(seed) for seed in controls["seeds"])


def run_physics_consistent_pilot(
    base: He3SimConfig, experiment_config: str | Path
) -> EventPrecisionPilot:
    scenarios, seeds = load_physics_consistent_scenarios(experiment_config)
    return _run_scenarios(base, scenarios, seeds)


def load_medium_scale_scenarios(
    path: str | Path,
) -> tuple[
    tuple[tuple[str, float, float, float, float, int], ...],
    tuple[int, ...],
    tuple[tuple[str, float, float, float, float, int], ...],
    tuple[int, ...],
]:
    """Load the approved grouped k_eff matrix and its separate stress point."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("medium-scale experiment config must be a mapping")
    controls = raw["shared_controls"]
    generation_time_s = float(raw["prompt_generation_time_s"])
    rates = tuple(float(item) for item in controls["true_rate_cps"])
    efficiencies = tuple(float(item) for item in controls["detection_efficiency"])
    seeds = tuple(int(seed) for seed in controls["seeds"])
    scenarios: list[tuple[str, float, float, float, float, int]] = []
    for group, settings in raw["groups"].items():
        expected_events = int(settings["expected_events"])
        for k_eff_raw in settings["k_eff"]:
            k_eff = float(k_eff_raw)
            alpha = derive_alpha_from_k_eff(k_eff, generation_time_s)
            for rate in rates:
                for efficiency in efficiencies:
                    scenarios.append(
                        (
                            f"{group}_k_{k_eff:.2f}_r_{rate:g}_e_{efficiency:.2f}",
                            alpha,
                            rate,
                            k_eff,
                            efficiency,
                            expected_events,
                        )
                    )
    stress = raw["stress_test"]
    stress_k_eff = float(stress["k_eff"])
    stress_scenario = (
        "stress_near_critical"
        f"_k_{stress_k_eff:.2f}_r_{float(stress['true_rate_cps']):g}"
        f"_e_{float(stress['detection_efficiency']):.2f}",
        derive_alpha_from_k_eff(stress_k_eff, generation_time_s),
        float(stress["true_rate_cps"]),
        stress_k_eff,
        float(stress["detection_efficiency"]),
        int(stress["expected_events"]),
    )
    return tuple(scenarios), seeds, (stress_scenario,), tuple(int(seed) for seed in stress["seeds"])


def run_medium_scale_scan(
    base: He3SimConfig,
    experiment_config: str | Path,
    *,
    analysis_mode: str = "oracle",
) -> tuple[EventPrecisionPilot, EventPrecisionPilot]:
    """Run the grouped scan with either truth-assisted or blind analysis settings."""
    if analysis_mode not in {"oracle", "blind"}:
        raise ValueError("analysis_mode must be 'oracle' or 'blind'")
    main, seeds, stress, stress_seeds = load_medium_scale_scenarios(experiment_config)
    return (
        _run_scenarios(base, main, seeds, analysis_mode=analysis_mode),
        _run_scenarios(base, stress, stress_seeds, analysis_mode=analysis_mode),
    )


def _adaptive_analysis_settings(alpha_per_s: float, duration_s: float) -> dict[str, object]:
    """Choose estimator windows from the known synthetic alpha for a fair scan.

    This is an oracle-assisted *simulation validation* setting: each method uses
    the same alpha-scaled time domain and broad bounds.  It must not be presented
    as a blind estimator configuration for experimental data.
    """
    maximum_lag_s = min(8.0 / alpha_per_s, duration_s / 5.0)
    largest_gate_s = min(8.0 / alpha_per_s, duration_s / 20.0)
    smallest_gate_s = min(0.1 / alpha_per_s, largest_gate_s / 10.0)
    return {
        "maximum_lag_s": maximum_lag_s,
        "rossi_bins": 80,
        "feynman_gate_widths_s": np.geomspace(smallest_gate_s, largest_gate_s, 32),
        "psd_count_bin_s": min(5.0e-5, 0.05 / alpha_per_s),
        "alpha_bounds_per_s": (max(1.0, alpha_per_s * 0.20), alpha_per_s * 5.0),
    }


def _blind_analysis_settings(duration_s: float) -> dict[str, object]:
    """Pre-specified estimator settings independent of the synthetic input alpha."""
    return {
        "maximum_lag_s": min(0.008, duration_s / 5.0),
        "rossi_bins": 80,
        "feynman_gate_widths_s": None,
        "psd_count_bin_s": 5.0e-5,
        "alpha_bounds_per_s": (50.0, 10_000.0),
    }


def _run_scenarios(
    base: He3SimConfig,
    scenarios: tuple[tuple[str, float, float, float, float, int], ...],
    seeds: tuple[int, ...],
    *,
    analysis_mode: str = "oracle",
) -> EventPrecisionPilot:
    points: list[EventPrecisionPoint] = []
    for label, alpha, rate, k_eff, efficiency, expected_events in scenarios:
        for seed in seeds:
            config = _scenario_config(base, alpha, rate, k_eff, efficiency, expected_events, seed)
            simulation = simulate_true_events(
                config,
                source_model=SourceModelKind.CORRELATED,
                max_expected_events=int(expected_events * 1.5),
            )
            analysis_settings = (
                _adaptive_analysis_settings(alpha, simulation.duration_s)
                if analysis_mode == "oracle"
                else _blind_analysis_settings(simulation.duration_s)
            )
            analysis = analyze_event_noise(
                simulation.events["t_s"],
                simulation.duration_s,
                bootstrap_replicates=0,
                seed=seed,
                **analysis_settings,
            )
            estimates = np.asarray(
                [
                    analysis.rossi.fit.alpha_per_s,
                    analysis.feynman.fit.alpha_per_s,
                    analysis.psd.fit.alpha_per_s,
                ]
            )
            points.append(
                EventPrecisionPoint(
                    label,
                    seed,
                    alpha,
                    rate,
                    k_eff,
                    efficiency,
                    simulation.duration_s,
                    int(simulation.events.size),
                    *map(float, estimates),
                    *map(float, estimates / alpha - 1.0),
                    config_hash(config),
                )
            )
    summaries: list[EventPrecisionSummary] = []
    for label, *_ in scenarios:
        selected = [point for point in points if point.scenario == label]
        errors = np.abs(
            np.asarray(
                [
                    [p.rossi_relative_error, p.feynman_relative_error, p.psd_relative_error]
                    for p in selected
                ]
            )
        )
        estimates = np.asarray(
            [[p.rossi_alpha_per_s, p.feynman_alpha_per_s, p.psd_alpha_per_s] for p in selected]
        )
        summaries.append(
            EventPrecisionSummary(
                label,
                len(selected),
                tuple(map(float, errors.mean(axis=0))),
                tuple(map(float, np.quantile(errors, 0.9, axis=0))),
                float(
                    np.mean(
                        (estimates.max(axis=1) - estimates.min(axis=1))
                        / selected[0].alpha_true_per_s
                    )
                ),
            )
        )
    return EventPrecisionPilot(
        max(item[-1] for item in scenarios), seeds, tuple(points), tuple(summaries)
    )


def write_event_precision_pilot(
    pilot: EventPrecisionPilot, output_dir: str | Path
) -> dict[str, Path]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    json_path = output / "event_precision_pilot.json"
    csv_path = output / "event_precision_runs.csv"
    summary_path = output / "event_precision_summary.csv"
    json_path.write_text(json.dumps(pilot.to_dict(), indent=2, allow_nan=False), encoding="utf-8")
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=asdict(pilot.points[0]).keys())
        writer.writeheader()
        writer.writerows(asdict(point) for point in pilot.points)
    with summary_path.open("w", newline="", encoding="utf-8") as stream:
        fieldnames = (
            "scenario",
            "alpha_true_per_s",
            "true_rate_cps",
            "k_eff",
            "detection_efficiency",
            "duration_s",
            "replicate_count",
            "rossi_mean_absolute_relative_error",
            "feynman_mean_absolute_relative_error",
            "psd_mean_absolute_relative_error",
            "rossi_p90_absolute_relative_error",
            "feynman_p90_absolute_relative_error",
            "psd_p90_absolute_relative_error",
            "mean_inter_method_spread",
        )
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for scenario in pilot.summaries:
            point = next(item for item in pilot.points if item.scenario == scenario.scenario)
            writer.writerow(
                {
                    "scenario": scenario.scenario,
                    "alpha_true_per_s": point.alpha_true_per_s,
                    "true_rate_cps": point.true_rate_cps,
                    "k_eff": point.k_eff,
                    "detection_efficiency": point.detection_efficiency,
                    "duration_s": point.duration_s,
                    "replicate_count": scenario.replicate_count,
                    "rossi_mean_absolute_relative_error": scenario.mean_absolute_relative_error[0],
                    "feynman_mean_absolute_relative_error": (
                        scenario.mean_absolute_relative_error[1]
                    ),
                    "psd_mean_absolute_relative_error": scenario.mean_absolute_relative_error[2],
                    "rossi_p90_absolute_relative_error": scenario.p90_absolute_relative_error[0],
                    "feynman_p90_absolute_relative_error": scenario.p90_absolute_relative_error[1],
                    "psd_p90_absolute_relative_error": scenario.p90_absolute_relative_error[2],
                    "mean_inter_method_spread": scenario.mean_inter_method_spread,
                }
            )
    return {"json": json_path, "csv": csv_path, "summary": summary_path}
