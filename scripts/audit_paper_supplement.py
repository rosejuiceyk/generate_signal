"""Independently recompute frozen decisions and audit supplement source tables.

This is an engineering/data-integrity audit, not an additional hypothesis test.
It never selects a new strategy or changes the frozen scientific thresholds.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
import platform
import subprocess
from pathlib import Path

import numpy as np

from he3sim.config import config_hash, load_config
from he3sim.synthesis.renderers import render_direct_sparse, render_recursive_fixed_tau
from he3sim.types import TRUE_EVENT_DTYPE


def audit(output: Path, config: Path, reproduction: Path | None = None) -> dict:
    """Recompute all decision gates from the saved per-seed measurements."""
    result = json.loads((output / "paper_supplement_validation.json").read_text("utf-8"))
    protocol = json.loads((output / "preregistered_protocol.json").read_text("utf-8"))
    checks: list[str] = []

    def require(condition: bool, label: str) -> None:
        if not condition:
            raise AssertionError(label)
        checks.append(label)

    canonical = json.dumps(protocol, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    require(
        hashlib.sha256(canonical.encode()).hexdigest() == result["protocol_sha256"],
        "Frozen protocol canonical hash matches result",
    )
    require(
        config_hash(load_config(config)) == result["base_config_hash"],
        "Base configuration hash matches result",
    )
    high, gate = result["high_rate"], result["feynman_gate"]
    hp, gp = protocol["high_rate"], protocol["feynman_gate"]
    require(hp == high["protocol"] and gp == gate["protocol"], "Embedded protocols unchanged")
    require(
        not (set(gp["development_seeds"]) & set(gp["holdout_seeds"])),
        "Development and holdout seeds disjoint",
    )
    expected_high = {(r, s) for r in hp["rates_cps"] for s in hp["seeds"]}
    observed_high = {(p["true_rate_cps"], p["seed"]) for p in high["points"]}
    require(
        expected_high == observed_high and len(high["points"]) == len(expected_high),
        "Complete high-rate grid; no duplicate or excluded seeds",
    )
    failures = []
    for point in high["points"]:
        comparisons = {
            "overlap": point["overlap_fraction"] <= hp["maximum_overlap_fraction"],
            "peak_bias": point["peak_bias_p90_abs"] <= hp["maximum_peak_bias_p90"],
            "clipping": point["clipping_nrmse"] <= hp["maximum_clipping_nrmse"],
            "saturation": point["saturation_fraction"] <= hp["maximum_saturation_fraction"],
            "trigger_efficiency": point["trigger_efficiency"] >= hp["minimum_trigger_efficiency"],
            "false_triggers": point["false_trigger_fraction"]
            <= hp["maximum_false_trigger_fraction"],
        }
        require(
            all(comparisons.values()) == point["within_applicability_limits"],
            f"High-rate decision recomputed: {point['true_rate_cps']:g}/{point['seed']}",
        )
        failures.append(
            {
                "rate_cps": point["true_rate_cps"],
                "seed": point["seed"],
                "failed_criteria": [k for k, passed in comparisons.items() if not passed],
            }
        )
    maximum = None
    for rate in hp["rates_cps"]:
        if all(
            p["within_applicability_limits"] for p in high["points"] if p["true_rate_cps"] == rate
        ):
            maximum = rate
        else:
            break
    require(maximum == high["maximum_usable_rate_cps"], "Contiguous rate boundary recomputed")

    strategies = [s[0] for s in gp["candidate_alpha_t_ranges"]]
    dev = gate["development_points"]
    expected_dev = {(s, strategy) for s in gp["development_seeds"] for strategy in strategies}
    require(
        {(p["seed"], p["strategy"]) for p in dev} == expected_dev and len(dev) == len(expected_dev),
        "All frozen development candidates retained",
    )
    rankings = []
    for strategy in strategies:
        rows = [p for p in dev if p["strategy"] == strategy]
        errors = [p["relative_error"] for p in rows]
        rankings.append(
            (
                np.median(errors),
                np.mean(errors),
                -np.median([p["r_squared"] for p in rows]),
                strategy,
            )
        )
    selected = sorted(rankings)[0][-1]
    require(selected == gate["selected_strategy"], "Selection uses development ranking only")
    baseline = "baseline_20us_10ms"
    holdout = gate["holdout_points"]
    expected_holdout = {
        (s, strategy) for s in gp["holdout_seeds"] for strategy in {baseline, selected}
    }
    require(
        {(p["seed"], p["strategy"]) for p in holdout} == expected_holdout
        and len(holdout) == len(expected_holdout),
        "Holdout contains baseline and frozen strategy only",
    )
    for point in dev + holdout:
        require(
            np.isclose(
                point["relative_error"],
                abs(point["alpha_hat_s_inv"] / gp["alpha_true_s_inv"] - 1),
                rtol=1e-12,
                atol=1e-15,
            ),
            f"Relative error recomputed: {point['seed']}/{point['strategy']}",
        )
    lookup = {(p["seed"], p["strategy"]): p for p in holdout}
    b = np.array([lookup[s, baseline]["relative_error"] for s in gp["holdout_seeds"]])
    a = np.array([lookup[s, selected]["relative_error"] for s in gp["holdout_seeds"]])
    require(
        all(
            lookup[s, baseline]["event_count"] == lookup[s, selected]["event_count"]
            for s in gp["holdout_seeds"]
        ),
        "Holdout pairs have identical observed event counts",
    )
    improvement = (b - a) * gp["alpha_true_s_inv"]
    rng = np.random.default_rng(gp["paired_bootstrap_seed"])
    draws = rng.integers(0, len(a), size=(gp["paired_bootstrap_replicates"], len(a)))
    ci = np.quantile(np.median(improvement[draws], axis=1), [0.025, 0.975])
    reduction = (np.median(b) - np.median(a)) / np.median(b) if np.median(b) else 0.0
    recomputed = {
        "baseline_median_relative_error": np.median(b),
        "selected_median_relative_error": np.median(a),
        "relative_median_error_reduction": reduction,
        "improved_holdout_fraction": np.mean(a < b),
        "paired_improvement_median_s_inv": np.median(improvement),
    }
    for key, value in recomputed.items():
        require(
            np.isclose(value, gate[key], rtol=1e-12, atol=1e-12),
            f"Holdout summary recomputed: {key}",
        )
    require(
        np.allclose(ci, gate["paired_improvement_ci95_s_inv"], rtol=1e-12, atol=1e-12),
        "Paired bootstrap 95% interval recomputed",
    )
    supported = (
        selected != baseline
        and reduction >= gp["required_relative_median_error_reduction"]
        and np.mean(a < b) >= gp["required_improved_holdout_fraction"]
        and ci[0] > gp["required_bootstrap_ci_lower_s_inv"]
    )
    require(
        bool(supported) == gate["improvement_claim_supported"], "Improvement claim gate recomputed"
    )
    require(
        bool(np.median(a) <= gp["accuracy_tolerance_rel"])
        == gate["selected_meets_accuracy_tolerance"],
        "Accuracy gate recomputed separately from improvement",
    )
    for name, rows in [
        ("high_rate_diagnostic.csv", high["points"]),
        ("feynman_gate_scan.csv", dev + holdout),
    ]:
        with (output / name).open(encoding="utf-8-sig", newline="") as handle:
            csv_rows = list(csv.DictReader(handle))
        require(len(csv_rows) == len(rows), f"CSV row count matches JSON: {name}")
        require(
            all(
                {key: str(value) for key, value in row.items()} == saved
                for row, saved in zip(rows, csv_rows, strict=True)
            ),
            f"Every CSV field matches JSON: {name}",
        )

    # Non-vacuous deterministic implementation controls, not new scientific rate points.
    controls = []
    for count in (1, 10, 100):
        events = np.zeros(count, dtype=TRUE_EVENT_DTYPE)
        events["t_s"] = 1.2345e-6 + np.arange(count) * 1.1e-7
        events["tau_r_s"], events["tau_d_s"] = 1e-6, 1e-5
        events["amplitude_peak_V"], events["polarity"] = 0.05, 1
        direct = render_direct_sparse(events, 8000, 1e8)
        recursive = render_recursive_fixed_tau(events, 8000, 1e8)
        nrmse = float(np.linalg.norm(recursive - direct) / np.linalg.norm(direct))
        require(
            np.linalg.norm(direct) > 0 and nrmse < 1e-10,
            f"Nonempty linear-renderer control: {count} pulses",
        )
        controls.append(
            {
                "pulse_count": count,
                "reference_rms_V": float(np.sqrt(np.mean(direct**2))),
                "recursive_direct_nrmse": nrmse,
                "preclip_peak_V": float(direct.max()),
            }
        )

    reproduction_files = {}
    if reproduction is not None:
        for name in (
            "preregistered_protocol.json",
            "paper_supplement_validation.json",
            "high_rate_diagnostic.csv",
            "feynman_gate_scan.csv",
        ):
            exact = (output / name).read_bytes() == (reproduction / name).read_bytes()
            require(exact, f"Full same-seed reproduction byte-identical: {name}")
            reproduction_files[name] = exact
    nominal_alpha = float(load_config(config).source_model.alpha.value)
    rate_table = []
    for point in high["points"]:
        alpha_duration = nominal_alpha * point["duration_s"]
        startup_fraction = 1.0 + np.expm1(-alpha_duration) / alpha_duration
        rate_table.append(
            {
                "nominal_asymptotic_rate_cps": point["true_rate_cps"],
                "seed": point["seed"],
                "duration_s": point["duration_s"],
                "realized_window_mean_rate_cps": point["true_event_count"] / point["duration_s"],
                "source_on_expected_mean_rate_cps": point["true_rate_cps"] * startup_fraction,
                "source_on_expected_fraction_of_asymptotic_rate": float(startup_fraction),
            }
        )
    return {
        "audit_passed": True,
        "scope": "software integrity; scientific failures are retained",
        "checks_passed": len(checks),
        "checks": checks,
        "high_rate_failed_criteria": failures,
        "nonempty_linearity_controls": controls,
        "source_on_rate_accounting": rate_table,
        "holdout_paired_improvements_s_inv": improvement.tolist(),
        "reproduction": reproduction_files,
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "packages": {
                p: importlib.metadata.version(p)
                for p in ("numpy", "scipy", "matplotlib", "pydantic", "pytest")
            },
        },
        "caveats": [
            "Three seeds per rate and eight holdout seeds are small simulation samples.",
            "The first-5000-sample linearity metric may compare empty low-rate windows; "
            "controls above are nonempty.",
            "Gate ranges use the known nominal alpha a priori; "
            "this is not unknown-alpha automatic tuning.",
            "Holdout seeds cover one physical condition, not independent parameter conditions.",
            "Triggering uses analog samples, not ADC-reconstructed samples.",
            "Source starts at time zero with an empty chain population; "
            "rate labels are asymptotic, not stationary window means.",
            "High-rate durations change across rates; "
            "the shortest 2-ms window contains a substantial source-on transient.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("outputs/paper_supplement_validation"))
    parser.add_argument("--config", type=Path, default=Path("configs/demo_correlated.yaml"))
    parser.add_argument("--reproduction", type=Path)
    args = parser.parse_args()
    report = audit(args.output, args.config, args.reproduction)
    path = args.output / "independent_audit.json"
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
    )
    config_snapshot = args.output / "base_config_snapshot.json"
    config_snapshot.write_text(load_config(args.config).model_dump_json(indent=2), encoding="utf-8")
    repo = Path(__file__).resolve().parents[1]
    source_paths = sorted((repo / "src").rglob("*.py"))
    source_paths += [
        Path(__file__).resolve(),
        repo / "scripts/plot_paper_supplement.py",
        repo / "scripts/run_paper_supplement_validation.py",
        args.config.resolve(),
    ]
    code_hashes = {
        str(p.relative_to(repo)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in source_paths
    }
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()
    manifest = {
        "git_head": head,
        "note": "Dirty-worktree source hashes are authoritative; HEAD alone is insufficient.",
        "source_sha256": code_hashes,
        "artifacts_sha256": {
            str(p.relative_to(args.output)).replace("\\", "/"): hashlib.sha256(
                p.read_bytes()
            ).hexdigest()
            for p in sorted(args.output.rglob("*"))
            if p.is_file() and p.name != "provenance_manifest.json"
        },
    }
    (args.output / "provenance_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"PASS: {report['checks_passed']} integrity checks; {path}")


if __name__ == "__main__":
    main()
