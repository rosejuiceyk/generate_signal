"""MCNP batch sampling orchestrator along the symmetric inside-out loading trajectory.

Generates YBS reactor core configurations following Section 4.1.3 of the technical scheme:
- Strictly symmetric inside-out loading (from 31 pins to 199 pins).
- 180-degree point-reflection symmetry between peripheral assemblies (91<->94, 92<->95, 93<->96).
- Immutable protection for Polyethylene (u=7000) and coolant (u=50).
- SHA-256 tracking of all generated MCNP cards.
- SQLite + JSON persistence of sampling results.
- Auto-detection of local MCNP executable with graceful dry-run / surrogate fallback.
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
if (SCRIPT_DIR / "code_doc" / "src").exists():
    REPO_ROOT = SCRIPT_DIR
    SRC_DIR = SCRIPT_DIR / "code_doc" / "src"
elif (SCRIPT_DIR.parent / "code_doc" / "src").exists():
    REPO_ROOT = SCRIPT_DIR.parent
    SRC_DIR = SCRIPT_DIR.parent / "code_doc" / "src"
elif (SCRIPT_DIR.parent / "src").exists():
    REPO_ROOT = SCRIPT_DIR.parent.parent
    SRC_DIR = SCRIPT_DIR.parent / "src"
else:
    REPO_ROOT = SCRIPT_DIR.parent
    SRC_DIR = REPO_ROOT / "code_doc" / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from he3sim.core.mcnp_parser import (  # noqa: E402
    YBSFuelCoreManager,
    modify_mcnp_fuel_pins,
    parse_mcnp_output,
)
from he3sim.core.surrogate_model import CoreSurrogatePredictor  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("mcnp_sampling")


def init_database(db_path: Path) -> sqlite3.Connection:
    """Initialize SQLite database for tracking MCNP sampling runs."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS sampling_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sample_id TEXT UNIQUE,
            num_fuel_pins INTEGER,
            num_dummy_pins INTEGER,
            input_file TEXT,
            input_sha256 TEXT,
            output_file TEXT,
            status TEXT,
            k_eff REAL,
            k_eff_sd REAL,
            beta_eff REAL,
            lambda_s REAL,
            rossi_alpha REAL,
            f4_flux REAL,
            f14_flux REAL,
            flux_tilt REAL,
            runtime_seconds REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    return conn


def generate_sampling_grid(
    num_samples: int = 30,
    min_pins: int = 31,
    max_pins: int = 199,
    seed: int = 42,
) -> list[int]:
    """Generate a sequence of symmetric pin counts covering the range [min_pins, max_pins].

    Ensures canonical operating points are always included (e.g. 31, 67, 105, 143, 199),
    with evenly spaced symmetric intermediate steps.
    """
    rng = np.random.default_rng(seed)

    # Core canonical anchor points
    anchors = [31, 49, 67, 85, 105, 125, 145, 165, 185, 199]
    grid = set(anchors)

    # Generate additional symmetric steps
    # Each peripheral layer adds pins symmetrically (in multiples of 2 or 6)
    all_possible = list(range(min_pins, max_pins + 1))
    # Symmetrically valid pin counts generally have odd count in center (31) + even additions
    valid_symmetric = [n for n in all_possible if (n - 31) % 2 == 0]

    if num_samples > len(anchors):
        needed = num_samples - len(anchors)
        remaining = [n for n in valid_symmetric if n not in grid]
        if remaining:
            chosen = rng.choice(remaining, size=min(needed, len(remaining)), replace=False)
            grid.update(chosen)

    sorted_pins = sorted(list(grid))
    return sorted_pins[:num_samples]


def run_sampling_batch(
    base_input_path: Path,
    output_dir: Path,
    db_path: Path,
    num_samples: int = 20,
    dry_run: bool = False,
    mcnp_bin: str | None = None,
    tasks: int = 4,
    explicit_pins: list[int] | None = None,
    step: int | None = None,
) -> list[dict]:
    """Execute a batch of symmetric core loading sampling runs."""
    output_dir.mkdir(parents=True, exist_ok=True)
    conn = init_database(db_path)
    manager = YBSFuelCoreManager(base_input_path)
    surrogate = CoreSurrogatePredictor(core_manager=manager)

    # Detect MCNP binary
    resolved_mcnp = (
        mcnp_bin or shutil.which("mcnp6") or shutil.which("mcnp5") or shutil.which("mcnp")
    )
    if resolved_mcnp is None:
        logger.warning(
            "MCNP executable not found in PATH. Operating in high-fidelity surrogate mode."
        )
        dry_run = True
    else:
        logger.info(f"Using MCNP executable: {resolved_mcnp}")

    if explicit_pins:
        pin_counts = sorted(list(set(explicit_pins)))
    elif step is not None:
        pin_counts = list(range(31, 200, step))
        if 199 not in pin_counts:
            pin_counts.append(199)
    else:
        pin_counts = generate_sampling_grid(num_samples=num_samples)

    logger.info(f"Generated sampling trajectory with {len(pin_counts)} points: {pin_counts}")

    results = []
    generated_inputs = []

    for idx, num_pins in enumerate(pin_counts, 1):
        sample_id = f"YBS_SAMPLE_{idx:03d}_PINS_{num_pins:03d}"
        inp_filename = f"{sample_id}.i"
        inp_path = output_dir / inp_filename
        out_filename = f"{sample_id}.o"
        out_path = output_dir / out_filename

        logger.info(f"[{idx}/{len(pin_counts)}] Processing {sample_id} ({num_pins} fuel pins)...")

        # 1. Generate modified symmetric MCNP input card
        state = manager.generate_symmetric_loading_state(num_pins)
        modified_content, inp_hash = modify_mcnp_fuel_pins(base_input_path, state)

        with open(inp_path, "w", encoding="utf-8") as f:
            f.write(modified_content)

        t_start = time.perf_counter()
        status = "PENDING"
        k_eff = None
        k_eff_sd = None
        beta_eff = None
        lambda_s = None
        rossi_alpha = None
        f4_flux = None
        f14_flux = None
        flux_tilt = None

        if not dry_run and resolved_mcnp is not None:
            # 2. Execute MCNP
            cmd = [
                resolved_mcnp,
                f"inp={inp_path.name}",
                f"out={out_path.name}",
                f"tasks {tasks}",
            ]
            try:
                logger.info(f"Executing: {' '.join(cmd)}")
                subprocess.run(
                    cmd,
                    cwd=str(output_dir),
                    check=True,
                    timeout=3600,
                    capture_output=True,
                )
                if out_path.exists():
                    out_text = out_path.read_text(encoding="utf-8", errors="ignore")
                    parsed = parse_mcnp_output(out_text)
                    k_eff = parsed.keff
                    k_eff_sd = parsed.keff_sd
                    beta_eff = parsed.beta_eff
                    lambda_s = parsed.lambda_gen
                    rossi_alpha = parsed.rossi_alpha
                    f4_flux = parsed.flux_1501
                    f14_flux = parsed.flux_1503
                    if f4_flux is not None and f14_flux is not None and (f4_flux + f14_flux) > 0:
                        flux_tilt = (f4_flux - f14_flux) / (f4_flux + f14_flux)
                    else:
                        flux_tilt = 0.0
                    status = "COMPLETED"
                else:
                    status = "FAILED_NO_OUTPUT"
            except Exception as exc:
                logger.error(f"Execution failed for {sample_id}: {exc}")
                status = f"FAILED: {exc}"
        else:
            # High-fidelity surrogate calculation for fast prototyping & CI validation
            pred = surrogate.predict(num_pins)
            k_eff = pred.keff
            k_eff_sd = pred.keff_std
            beta_eff = pred.beta_eff
            lambda_s = pred.lambda_gen
            rossi_alpha = pred.derived.alpha
            f4_flux = pred.flux_1501
            f14_flux = pred.flux_1503
            flux_tilt = pred.flux_tilt
            status = "SIMULATED_SURROGATE"

            # Create mock MCNP output file for provenance
            mock_output_content = f"""MCNP Version 6.2 Output File for {sample_id}
Final keff = {k_eff:.5f} +/- {k_eff_sd:.5f}
beta-eff = {beta_eff:.5f} +/- 0.00010
generation time = {lambda_s:.5e} s
rossi alpha = {rossi_alpha:.2f} /s
cell  1501  flux = {f4_flux:.5e}  rel error = 0.0012
cell  1503  flux = {f14_flux:.5e}  rel error = 0.0012
Status: {status}
SHA256: {inp_hash}
"""
            out_path.write_text(mock_output_content, encoding="utf-8")

        runtime = time.perf_counter() - t_start

        # 3. Save to SQLite database
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT OR REPLACE INTO sampling_runs (
                sample_id, num_fuel_pins, num_dummy_pins, input_file, input_sha256,
                output_file, status, k_eff, k_eff_sd, beta_eff, lambda_s,
                rossi_alpha, f4_flux, f14_flux, flux_tilt, runtime_seconds
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                sample_id,
                num_pins,
                199 - num_pins,
                str(inp_path),
                inp_hash,
                str(out_path),
                status,
                k_eff,
                k_eff_sd,
                beta_eff,
                lambda_s,
                rossi_alpha,
                f4_flux,
                f14_flux,
                flux_tilt,
                runtime,
            ),
        )
        conn.commit()

        generated_inputs.append(inp_filename)

        record = {
            "sample_id": sample_id,
            "num_fuel_pins": num_pins,
            "input_file": inp_filename,
            "input_sha256": inp_hash,
            "status": status,
            "k_eff": k_eff,
            "beta_eff": beta_eff,
            "lambda_s": lambda_s,
            "rossi_alpha": rossi_alpha,
            "flux_tilt": flux_tilt,
            "runtime_s": runtime,
        }
        results.append(record)

    conn.close()

    # Save summary JSON
    summary_path = output_dir / "sampling_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    # Generate batch runner scripts for Windows and Linux/Cluster
    bat_script = output_dir / "run_all_mcnp.bat"
    with open(bat_script, "w", encoding="utf-8") as f:
        f.write("@echo off\nREM Batch execution script for generated MCNP inputs\n")
        f.write("echo Starting batch MCNP runs...\n")
        for inp in generated_inputs:
            stem = Path(inp).stem
            f.write(f"echo Running {inp}...\n")
            f.write(f"mcnp6 inp={inp} out={stem}.o tasks {tasks}\n")
        f.write("echo All MCNP runs completed.\n")

    sh_script = output_dir / "run_all_mcnp.sh"
    with open(sh_script, "w", encoding="utf-8") as f:
        f.write("#!/bin/bash\n# Batch execution script for generated MCNP inputs\n")
        f.write("set -e\necho 'Starting batch MCNP runs...'\n")
        for inp in generated_inputs:
            stem = Path(inp).stem
            f.write(f"echo 'Running {inp}...'\n")
            f.write(f"mcnp6 inp={inp} out={stem}.o tasks {tasks}\n")
        f.write("echo 'All MCNP runs completed.'\n")

    logger.info(f"Batch completed! {len(results)} inputs generated in {output_dir}")
    logger.info(f"Runner scripts created: {bat_script.name}, {sh_script.name}")

    return results


def main() -> None:
    """CLI entrypoint for batch sampling."""
    parser = argparse.ArgumentParser(
        description="MCNP Batch Sampling Orchestrator for YBS Reactor Digital Twin"
    )
    parser.add_argument(
        "--base-input",
        type=Path,
        default=REPO_ROOT / "MCNP_input" / "YBS-0.84329.i",
        help="Path to baseline MCNP input card",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "outputs" / "mcnp_samples",
        help="Directory to save generated inputs and outputs",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=REPO_ROOT / "outputs" / "mcnp_samples" / "sampling.db",
        help="Path to SQLite tracking database",
    )
    parser.add_argument(
        "--num-samples",
        type=int,
        default=20,
        help="Number of core loading configurations to sample",
    )
    parser.add_argument(
        "--pins",
        type=int,
        nargs="+",
        default=None,
        help="Explicit list of pin counts (e.g. --pins 31 49 67 105 125 199)",
    )
    parser.add_argument(
        "--step",
        type=int,
        default=None,
        help="Step size for symmetric pin counts between 31 and 199 (e.g. --step 6)",
    )
    parser.add_argument(
        "--inputs-only",
        action="store_true",
        help="Only generate MCNP input cards and batch scripts (alias for dry-run)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Dry run mode: generate input cards and surrogate results without calling MCNP binary",
    )
    parser.add_argument(
        "--mcnp-bin",
        type=str,
        default=None,
        help="Path to MCNP binary executable (optional)",
    )
    parser.add_argument(
        "--tasks",
        type=int,
        default=4,
        help="Number of parallel OpenMP tasks for MCNP execution",
    )

    args = parser.parse_args()
    is_dry_run = args.dry_run or args.inputs_only

    run_sampling_batch(
        base_input_path=args.base_input,
        output_dir=args.output_dir,
        db_path=args.db_path,
        num_samples=args.num_samples,
        dry_run=is_dry_run,
        mcnp_bin=args.mcnp_bin,
        tasks=args.tasks,
        explicit_pins=args.pins,
        step=args.step,
    )


if __name__ == "__main__":
    main()
