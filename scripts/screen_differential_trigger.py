"""Screen finite-difference onset triggers against a fixed synthetic truth.

This diagnostic is deliberately distinct from a manuscript validation run.  It
uses a short, fixed realization to select a single prospective trigger setting
before any new multi-seed acceptance experiment is frozen.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from he3sim.acquisition.trigger import DifferentialThresholdTrigger, ThresholdTrigger
from he3sim.analysis.paper_supplement_validation import _trigger_metrics
from he3sim.analysis.waveform_alpha_validation import _derived_config, _paired_base_config
from he3sim.config import load_config
from he3sim.synthesis.streaming import iter_waveform_blocks, prepare_waveform_simulation


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/demo_correlated.yaml"))
    parser.add_argument("--duration-s", type=float, default=0.5)
    parser.add_argument("--seed", type=int, default=20260902)
    parser.add_argument(
        "--noise", action="store_true", help="Include the configured white-noise arm."
    )
    parser.add_argument(
        "--smoothing-s",
        type=float,
        default=0.0,
        help="Trailing boxcar averaging before the delayed difference.",
    )
    args = parser.parse_args()
    if args.duration_s <= 0.0:
        raise ValueError("duration-s must be positive")

    base = load_config(args.config)
    paired = _paired_base_config(
        base,
        duration_s=args.duration_s,
        true_rate_cps=3_000.0,
        alpha_s_inv=1_000.0,
        sample_rate_hz=100_000_000.0,
        seed=args.seed,
    )
    config = _derived_config(
        paired,
        noise_enabled=args.noise,
        dead_time_mode="none",
        dead_time_s=0.0,
        duration_s=None,
    )
    simulation = prepare_waveform_simulation(
        config,
        max_expected_events=10_000,
        max_waveform_samples=int(args.duration_s * 100_000_000) + 1,
    )
    sample_rate_hz = float(config.simulation.sample_rate_hz.value)
    threshold = ThresholdTrigger(sample_rate_hz, 1, 0.01, 0.001, 1.0e-6)
    threshold_state = None
    baseline_candidates: list[int] = []
    settings = (0.001, 0.002, 0.004, 0.008, 0.012)
    differential = {
        setting: (
            DifferentialThresholdTrigger(
                sample_rate_hz,
                1,
                setting,
                setting * 0.2,
                1e-7,
                5e-7,
                args.smoothing_s,
            ),
            None,
            [],
        )
        for setting in settings
    }
    for block in iter_waveform_blocks(simulation, config):
        if block.analog_samples_V is None:
            raise RuntimeError("screen requires analog waveform samples")
        found, threshold_state = threshold.process_block(
            block.analog_samples_V, block.sample_index_start, threshold_state
        )
        baseline_candidates.extend(found.tolist())
        for setting, (trigger, state, candidates) in tuple(differential.items()):
            found, state = trigger.process_block(
                block.analog_samples_V, block.sample_index_start, state
            )
            candidates.extend(found.tolist())
            differential[setting] = (trigger, state, candidates)
    truth_count = int(simulation.true_events.events.size)
    truth_events = simulation.true_events.events
    baseline_times = np.asarray(baseline_candidates, dtype=np.float64) / sample_rate_hz
    baseline_efficiency, baseline_false_fraction = _trigger_metrics(
        baseline_times, truth_events, config
    )
    payload = {
        "scope": "short ideal-waveform diagnostic; not an acceptance result",
        "seed": args.seed,
        "duration_s": args.duration_s,
        "noise_enabled": args.noise,
        "smoothing_s": args.smoothing_s,
        "truth_event_count": truth_count,
        "threshold_candidate_count": len(baseline_candidates),
        "threshold_candidates_per_truth": len(baseline_candidates) / truth_count,
        "threshold_one_to_one_efficiency": baseline_efficiency,
        "threshold_false_trigger_fraction": baseline_false_fraction,
        "differential_candidates": {
            str(setting): {
                "candidate_count": len(item[2]),
                "candidates_per_truth": len(item[2]) / truth_count,
                "one_to_one_efficiency": _trigger_metrics(
                    np.asarray(item[2], dtype=np.float64) / sample_rate_hz,
                    truth_events,
                    config,
                )[0],
                "false_trigger_fraction": _trigger_metrics(
                    np.asarray(item[2], dtype=np.float64) / sample_rate_hz,
                    truth_events,
                    config,
                )[1],
            }
            for setting, item in differential.items()
        },
    }
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
