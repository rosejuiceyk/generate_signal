"""Freeze an independent, waveform-level validation of onset-differential triggering.

The prior level-trigger validation remains an archived negative result.  This
runner freezes a new, independent five-seed protocol after a separate short
screen selected the observer algorithm.  It never changes the physical source
or treats synthetic parameters as detector calibration.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np

from he3sim.analysis.phase_b_validation import (
    build_phase_b_validation,
    write_phase_b_validation_report,
)
from he3sim.analysis.waveform_alpha_validation import (
    run_waveform_alpha_validation,
    write_waveform_alpha_report,
)
from he3sim.config import config_hash, load_config
from he3sim.physics.source_model import PromptSourceModel

EXPECTED_PMF = np.asarray(
    [0.031722, 0.171707, 0.336199, 0.303969, 0.126946, 0.026648, 0.002602, 0.000207],
    dtype=np.float64,
)
EXPECTED_NU_BAR = 2.414097
EVALUATION_SEEDS = (20260911, 20260912, 20260913, 20260914, 20260915)
WAVEFORM_DURATION_S = 30.0
TRUE_RATE_CPS = 3_000.0
ALPHA_S_INV = 1_000.0
SAMPLE_RATE_HZ = 100_000_000.0
ALPHA_TOLERANCE_REL = 0.05
DERIVATIVE_THRESHOLD_V = 0.004
DERIVATIVE_DELAY_S = 5.0e-7
DERIVATIVE_SMOOTHING_S = 2.0e-7


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_hashes(repository: Path) -> dict[str, str]:
    paths = (
        "src/he3sim/acquisition/trigger.py",
        "src/he3sim/analysis/noise.py",
        "src/he3sim/analysis/phase_b_validation.py",
        "src/he3sim/analysis/waveform_alpha_validation.py",
        "src/he3sim/physics/source_model.py",
        "src/he3sim/synthesis/streaming.py",
        "scripts/run_manuscript_v6_differential_freeze.py",
    )
    return {path: _sha256(repository / path) for path in paths}


def _multiplicity_audit(config_path: Path) -> dict[str, Any]:
    config = load_config(config_path)
    model = PromptSourceModel.from_config(config.source_model)
    if not np.allclose(model.nu_pmf, EXPECTED_PMF, rtol=0.0, atol=1.0e-12):
        raise ValueError("the frozen run requires the Zucker & Holden U-235 PMF")
    if not np.isclose(model.nu_bar, EXPECTED_NU_BAR, rtol=0.0, atol=1.0e-12):
        raise ValueError("the frozen run requires nu_bar=2.414097")
    return {
        "distribution_name": "Zucker & Holden U-235 thermal-fission PMF",
        "citation": "Holden and Zucker (1988), Nuclear Science and Engineering 98, 174-181",
        "multiplicities": list(range(model.nu_pmf.size)),
        "pmf": model.nu_pmf.tolist(),
        "nu_bar": model.nu_bar,
        "diven_factor": model.diven_factor,
        "parameter_status": "synthetic_demo",
    }


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _run_seed(job: tuple[str, str, int]) -> dict[str, Any]:
    config_path_text, output_text, seed = job
    config = load_config(Path(config_path_text))
    result, analyses = run_waveform_alpha_validation(
        config,
        duration_s=WAVEFORM_DURATION_S,
        bootstrap_replicates=32,
        alpha_tolerance_rel=ALPHA_TOLERANCE_REL,
        max_expected_events=150_000,
        max_waveform_samples=3_100_000_000,
        true_rate_cps=TRUE_RATE_CPS,
        alpha_s_inv=ALPHA_S_INV,
        sample_rate_hz=SAMPLE_RATE_HZ,
        seed=seed,
        trigger_algorithm="differential",
        derivative_threshold_V=DERIVATIVE_THRESHOLD_V,
        derivative_delay_s=DERIVATIVE_DELAY_S,
        derivative_smoothing_s=DERIVATIVE_SMOOTHING_S,
    )
    seed_dir = Path(output_text) / "waveform_alpha" / f"seed_{seed}"
    write_waveform_alpha_report(result, analyses, seed_dir)
    return result.to_dict()


def _all_arms_within_tolerance(result: dict[str, Any]) -> bool:
    arms = [result["reference"], *result["conditions"]]
    return all(
        max(
            arm["alpha_rossi_rel_error"],
            arm["alpha_feynman_rel_error"],
            arm["alpha_psd_rel_error"],
        )
        <= ALPHA_TOLERANCE_REL
        for arm in arms
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/demo_correlated.yaml"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--waveform-workers", type=int, default=5)
    args = parser.parse_args()
    if args.waveform_workers < 1:
        raise ValueError("waveform-workers must be positive")
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"refusing to overwrite non-empty output directory: {output}")
    output.mkdir(parents=True, exist_ok=True)
    repository = Path.cwd()
    config_path = args.config.resolve()
    config = load_config(config_path)
    frozen_protocol = {
        "artifact": "manuscript_v6_independent_differential_trigger_validation",
        "scope": (
            "synthetic_demo software validation only; not detector calibration, "
            "transport validation, "
            "or a measured-waveform comparison"
        ),
        "selection_history": {
            "screening_seed": 42,
            "screening_duration_s": 0.1,
            "screening_role": "algorithm selection only; excluded from the evaluation seeds",
        },
        "multiplicity_audit": _multiplicity_audit(config_path),
        "config_sha256": config_hash(config),
        "phase_b_event_level": {
            "recovery_events_per_case": 220_000,
            "dead_time_events_per_case": 150_000,
            "bootstrap_replicates": 16,
            "alpha_tolerance_rel": 0.05,
        },
        "waveform_validation": {
            "evaluation_seeds": EVALUATION_SEEDS,
            "duration_s": WAVEFORM_DURATION_S,
            "true_rate_cps": TRUE_RATE_CPS,
            "alpha_true_s_inv": ALPHA_S_INV,
            "sample_rate_hz": SAMPLE_RATE_HZ,
            "bootstrap_replicates": 32,
            "acceptance_rule": (
                "every estimator in G0--G3 of every evaluation seed must have <=5% relative error"
            ),
            "trigger_algorithm": "differential",
            "derivative_threshold_V": DERIVATIVE_THRESHOLD_V,
            "derivative_delay_s": DERIVATIVE_DELAY_S,
            "derivative_smoothing_s": DERIVATIVE_SMOOTHING_S,
        },
        "prior_negative_results": {
            "level_trigger_waveform_validation": (
                "outputs/manuscript_v5_zucker_holden_local/waveform_alpha"
            ),
            "high_rate_and_gate_validation": (
                "outputs/manuscript_v5_zucker_holden_local/supplementary_stress_tests"
            ),
            "rule": "these results remain limitations and are not overwritten by this new protocol",
        },
        "source_sha256": _source_hashes(repository),
        "runtime": {
            "python": sys.version,
            "platform": platform.platform(),
            "numpy": np.__version__,
        },
    }
    _write_json(output / "frozen_protocol.json", frozen_protocol)
    shutil.copy2(config_path, output / "config_snapshot.yaml")

    phase_b = build_phase_b_validation(config)
    write_phase_b_validation_report(output / "phase_b_event_level", config, phase_b)

    workers = min(args.waveform_workers, len(EVALUATION_SEEDS))
    jobs = [(str(config_path), str(output), seed) for seed in EVALUATION_SEEDS]
    with ProcessPoolExecutor(max_workers=workers) as executor:
        waveform = list(executor.map(_run_seed, jobs))
    waveform.sort(key=lambda item: item["shared_truth_seed"])
    _write_json(output / "waveform_alpha" / "all_seed_results.json", waveform)
    result_index = {
        "phase_b_event_level_passed": phase_b.metrics.passed,
        "waveform_seed_count": len(waveform),
        "waveform_strict_all_arms_passed": all(
            _all_arms_within_tolerance(item) for item in waveform
        ),
        "waveform_per_seed_all_arms_passed": {
            str(item["shared_truth_seed"]): _all_arms_within_tolerance(item) for item in waveform
        },
        "manuscript_rule": (
            "A false strict gate must remain a reported limitation; it cannot be "
            "converted into a positive claim."
        ),
    }
    _write_json(output / "result_index.json", result_index)
    print(json.dumps(result_index, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
