"""Reactor Core Digital Twin Dashboard with MCNP & ML Surrogate Inference."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure workspace root is in sys.path
for parent in Path(__file__).resolve().parents:
    if (parent / "reactor_twin").is_dir():
        if str(parent) not in sys.path:
            sys.path.insert(0, str(parent))
        break

from reactor_twin.app import (
    create_assembly_pin_figure,
    create_core_assembly_figure,
    get_surrogate_predictor,
    main,
)

if __name__ == "__main__":
    main()
