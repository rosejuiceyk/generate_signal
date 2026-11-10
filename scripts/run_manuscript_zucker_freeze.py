"""Freeze and execute the software-only validation package for manuscript v5.

This runner is intentionally separate from historical outputs.  It records the
exact Zucker & Holden multiplicity law, configuration snapshot, source hashes,
seed-level results, and claim gates before producing any numerical result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import sys
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np

from he3sim.analysis.paper_supplement_validation import (
    FeynmanGateProtocol,
    HighRateProtocol,
    preregistered_protocol_payload,
    protocol_sha256,
    run_paper_supplement_validation,
    write_paper_supplement_report,
)
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
WAVEFORM_SEEDS = (42, 101, 202, 303, 404)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_hashes(repository: Path) -> dict[str, str]:
    tracked = (
        "src/he3sim/physics/source_model.py",
        "src/he3sim/physics/chains.py",
        "src/he3sim/physics/events.py",
        "src/he3sim/analysis/noise.py",
        "src/he3sim/analysis/phase_b_validation.py",
        "src/he3sim/analysis/waveform_alpha_validation.py",
        "src/he3sim/analysis/paper_supplement_validation.py",
        "src/he3sim/synthesis/streaming.py",
        "src/he3sim/acquisition/trigger.py",
        "scripts/run_manuscript_zucker_freeze.py",
    )
    return {relative: _sha256(repository / relative) for relative in tracked}


def _multiplicity_audit(config_path: Path) -> dict[str, Any]:
    config = load_config(config_path)
    model = PromptSourceModel.from_config(config.source_model)
    if not np.allclose(model.nu_pmf, EXPECTED_PMF, rtol=0.0, atol=1.0e-12):
        raise ValueError("The frozen manuscript run requires the Zucker & Holden PMF.")
    if not np.isclose(model.nu_bar, EXPECTED_NU_BAR, rtol=0.0, atol=1.0e-12):
        raise ValueError("The frozen manuscript run requires nu_bar=2.414097.")
    if not np.isclose(float(np.sum(model.nu_pmf)), 1.0, rtol=0.0, atol=1.0e-12):
        raise ValueError("The multiplicity PMF is not normalized.")
    return {
        "citation": (
            "Zucker & Holden distribution; bibliographic source Holden and Zucker (1988), "
            "thermal-neutron-induced U-235 fission; "
            "Nuclear Science and Engineering 98, 174-181"
        ),
        "multiplicities": list(range(model.nu_pmf.size)),
        "pmf": model.nu_pmf.tolist(),
        "nu_bar": model.nu_bar,
        "factorial_second_moment": float(
            np.sum(
                np.arange(model.nu_pmf.size) * (np.arange(model.nu_pmf.size) - 1.0) * model.nu_pmf
            )
        ),
        "diven_factor": model.diven_factor,
        "parameter_status": "synthetic_demo",
    }


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/demo_correlated.yaml"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/manuscript_v5_zucker_holden"),
        help="Must be a new or empty directory; historical results are never overwritten.",
    )
    parser.add_argument(
        "--waveform-workers",
        type=int,
        default=5,
        help="Parallel workers for independent fixed-seed waveform runs.",
    )
    return parser


def _run_waveform_seed(job: tuple[str, str, int]) -> dict[str, Any]:
    """Run one independent seed and write only to its dedicated directory."""

    config_path_text, output_text, seed = job
    config = load_config(Path(config_path_text))
    result, analyses = run_waveform_alpha_validation(
        config,
        duration_s=10.0,
        bootstrap_replicates=16,
        max_expected_events=100_000,
        max_waveform_samples=1_500_000_000,
        true_rate_cps=3_000.0,
        alpha_s_inv=1_000.0,
        sample_rate_hz=100_000_000.0,
        seed=seed,
    )
    seed_dir = Path(output_text) / "waveform_alpha" / f"seed_{seed}"
    write_waveform_alpha_report(result, analyses, seed_dir)
    return result.to_dict()


def main() -> int:
    args = _parser().parse_args()
    repository = Path.cwd()
    output = args.output.resolve()
    if args.waveform_workers < 1:
        raise ValueError("waveform-workers must be positive")
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"Refusing to overwrite non-empty output directory: {output}")
    output.mkdir(parents=True, exist_ok=True)

    config_path = args.config.resolve()
    config = load_config(config_path)
    pmf_audit = _multiplicity_audit(config_path)
    high_rate = HighRateProtocol()
    feynman_gate = FeynmanGateProtocol()
    frozen_protocol = {
        "artifact": "manuscript_v5_zucker_holden_software_only_validation",
        "scope": (
            "synthetic_demo only; not detector calibration, transport validation, "
            "or measured-data comparison"
        ),
        "multiplicity_audit": pmf_audit,
        "config_sha256": config_hash(config),
        "waveform_alpha_seeds": WAVEFORM_SEEDS,
        "phase_b": {
            "recovery_events_per_case": 220_000,
            "deadtime_events_per_case": 150_000,
            "bootstrap_replicates": 16,
            "alpha_tolerance_rel": 0.05,
        },
        "paper_supplement": preregistered_protocol_payload(high_rate, feynman_gate),
        "paper_supplement_protocol_sha256": protocol_sha256(
            preregistered_protocol_payload(high_rate, feynman_gate)
        ),
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

    worker_count = min(args.waveform_workers, len(WAVEFORM_SEEDS))
    jobs = [(str(config_path), str(output), seed) for seed in WAVEFORM_SEEDS]
    with ProcessPoolExecutor(max_workers=worker_count) as executor:
        waveform_results = list(executor.map(_run_waveform_seed, jobs))
    waveform_results.sort(key=lambda item: item["shared_truth_seed"])
    _write_json(output / "waveform_alpha" / "all_seed_results.json", waveform_results)

    supplement = run_paper_supplement_validation(config, high_rate, feynman_gate)
    write_paper_supplement_report(supplement, output / "supplementary_stress_tests")

    result_index = {
        "phase_b_event_level_passed": phase_b.metrics.passed,
        "phase_b_metrics": asdict(phase_b.metrics),
        "waveform_seed_count": len(waveform_results),
        "waveform_g0_and_g1_all_passed": all(
            item["passed_reference_and_ideal"] for item in waveform_results
        ),
        "high_rate_maximum_usable_rate_cps": supplement.high_rate.maximum_usable_rate_cps,
        "feynman_gate_improvement_claim_supported": (
            supplement.feynman_gate.improvement_claim_supported
        ),
        "feynman_gate_selected_meets_accuracy_tolerance": (
            supplement.feynman_gate.selected_meets_accuracy_tolerance
        ),
        "manuscript_rule": (
            "Any false gate must be reported as a limitation and must not be converted "
            "into a positive claim."
        ),
    }
    _write_json(output / "result_index.json", result_index)
    print(json.dumps(result_index, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
