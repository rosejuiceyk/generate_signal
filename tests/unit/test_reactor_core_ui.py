"""Unit tests for reactor core UI components and figure generation."""

from __future__ import annotations

import importlib

from he3sim.core.surrogate_model import CoreSurrogatePredictor


def test_core_ui_figures() -> None:
    mod = importlib.import_module("he3sim.ui.pages.00_reactor_core")
    create_core_fig = mod.create_core_assembly_figure
    create_pin_fig = mod.create_assembly_pin_figure

    predictor = CoreSurrogatePredictor()
    manager = predictor.manager
    config = manager.generate_symmetric_loading_state(105)

    fuel_counts = {
        u: sum(1 for tok in config.get(u, {}).values() if tok == "9000") for u in range(90, 97)
    }

    # Test core figure creation
    core_fig = create_core_fig(selected_u=91, fuel_counts=fuel_counts)
    assert core_fig is not None
    assert len(core_fig.data) > 0

    # Test assembly pin figure creation for central 90 and peripheral 91
    pin_fig_90 = create_pin_fig(manager, selected_u=90, config=config)
    assert pin_fig_90 is not None
    assert len(pin_fig_90.data) > 0

    pin_fig_91 = create_pin_fig(manager, selected_u=91, config=config)
    assert pin_fig_91 is not None
    assert len(pin_fig_91.data) > 0
