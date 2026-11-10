"""Run the two pre-registered validation experiments for the first manuscript."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from he3sim.analysis.paper_supplement_validation import (
    FeynmanGateProtocol,
    HighRateProtocol,
    preregistered_protocol_payload,
    protocol_sha256,
    run_paper_supplement_validation,
    write_paper_supplement_report,
)
from he3sim.config import load_config


def build_parser() -> argparse.ArgumentParser:
    """Build the standalone, auditable experiment command."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/demo_correlated.yaml"),
        help="Correlated synthetic YAML configuration.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/paper_supplement_validation"),
        help="New output directory for protocol, results, tables, and figures.",
    )
    return parser


def main() -> int:
    """Write the frozen protocol first, execute once, and report claim gates."""

    args = build_parser().parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    high_rate = HighRateProtocol()
    feynman_gate = FeynmanGateProtocol()
    protocol_path = args.output / "preregistered_protocol.json"
    protocol_payload = preregistered_protocol_payload(high_rate, feynman_gate)
    protocol_path.write_text(
        json.dumps(
            protocol_payload,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    result = run_paper_supplement_validation(
        load_config(args.config),
        high_rate,
        feynman_gate,
    )
    files = write_paper_supplement_report(result, args.output)
    print(f"protocol: {protocol_path}")
    print(f"protocol_sha256: {protocol_sha256(protocol_payload)}")
    print(f"result: {files['json']}")
    print(f"maximum_usable_rate_cps: {result.high_rate.maximum_usable_rate_cps}")
    print(f"selected_gate_strategy: {result.feynman_gate.selected_strategy}")
    print(
        "feynman_gate_improvement_claim_supported: "
        f"{result.feynman_gate.improvement_claim_supported}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
