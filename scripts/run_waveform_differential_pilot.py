"""Run one non-acceptance waveform pilot for the differential onset trigger."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from he3sim.analysis.waveform_alpha_validation import (
    run_waveform_alpha_validation,
    write_waveform_alpha_report,
)
from he3sim.config import load_config


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/demo_correlated.yaml"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--duration-s", type=float, default=0.5)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    if args.duration_s <= 0.0:
        raise ValueError("duration-s must be positive")
    if args.output.exists() and any(args.output.iterdir()):
        raise FileExistsError(f"refusing to overwrite non-empty output directory: {args.output}")
    args.output.mkdir(parents=True, exist_ok=True)
    config = load_config(args.config)
    result, analyses = run_waveform_alpha_validation(
        config,
        duration_s=args.duration_s,
        bootstrap_replicates=0,
        max_expected_events=30_000,
        max_waveform_samples=int(args.duration_s * 100_000_000) + 1,
        true_rate_cps=3_000.0,
        alpha_s_inv=1_000.0,
        sample_rate_hz=100_000_000.0,
        seed=args.seed,
        trigger_algorithm="differential",
        derivative_threshold_V=0.004,
        derivative_delay_s=5.0e-7,
        derivative_smoothing_s=2.0e-7,
    )
    write_waveform_alpha_report(result, analyses, args.output)
    (args.output / "pilot_protocol.json").write_text(
        json.dumps(
            {
                "scope": "exploratory pilot; not a manuscript acceptance result",
                "duration_s": args.duration_s,
                "seed": args.seed,
                "trigger_algorithm": "differential",
                "derivative_threshold_V": 0.004,
                "derivative_delay_s": 5.0e-7,
                "derivative_smoothing_s": 2.0e-7,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result.to_dict(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
