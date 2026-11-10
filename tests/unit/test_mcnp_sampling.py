"""Unit tests for MCNP batch sampling orchestrator (Module 1.3)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from scripts.run_mcnp_sampling import (
    generate_sampling_grid,
    init_database,
    run_sampling_batch,
)


def test_generate_sampling_grid() -> None:
    """Sampling grid must produce strictly monotonic pin counts within [31, 199]."""
    grid = generate_sampling_grid(num_samples=10, min_pins=31, max_pins=199)
    assert len(grid) == 10
    assert grid[0] == 31  # Center assembly only
    assert grid[-1] == 199  # Fully loaded core
    assert sorted(grid) == grid  # Strictly monotonic
    # Symmetrically valid steps
    for n in grid:
        assert 31 <= n <= 199
        assert (n - 31) % 2 == 0 or n == 105


def test_init_database(tmp_path: Path) -> None:
    """Database initialization creates proper schema."""
    db_file = tmp_path / "test_sampling.db"
    conn = init_database(db_file)
    assert db_file.exists()

    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sampling_runs';")
    row = cursor.fetchone()
    assert row is not None
    assert row[0] == "sampling_runs"
    conn.close()


def test_run_sampling_batch_dry_run(tmp_path: Path) -> None:
    """Batch sampling in dry-run mode populates database and outputs files with valid SHA-256."""
    output_dir = tmp_path / "samples"
    db_path = tmp_path / "test.db"

    # Resolve base input file
    candidate_paths = [
        Path("MCNP_input/YBS-0.84329.i"),
        Path("../MCNP_input/YBS-0.84329.i"),
        Path("../../MCNP_input/YBS-0.84329.i"),
    ]
    base_input = None
    for p in candidate_paths:
        if p.exists():
            base_input = p.resolve()
            break
    assert base_input is not None, "Base input card not found"

    results = run_sampling_batch(
        base_input_path=base_input,
        output_dir=output_dir,
        db_path=db_path,
        num_samples=3,
        dry_run=True,
    )

    assert len(results) == 3
    for r in results:
        assert r["status"] == "SIMULATED_SURROGATE"
        assert 0.5 < r["k_eff"] < 1.2
        assert len(r["input_sha256"]) == 64

    # Check database rows
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM sampling_runs WHERE status='SIMULATED_SURROGATE'")
    count = cursor.fetchone()[0]
    assert count == 3
    conn.close()

    # Check generated summary JSON
    summary_file = output_dir / "sampling_summary.json"
    assert summary_file.exists()
    with open(summary_file, encoding="utf-8") as f:
        data = json.load(f)
    assert len(data) == 3
