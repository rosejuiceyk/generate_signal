"""Unit tests for CoreSurrogatePredictor ML surrogate model."""

from __future__ import annotations

import math
import os
import tempfile

from he3sim.core.surrogate_model import CoreSurrogatePredictor

TEMPLATE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "MCNP_input", "YBS-0.84329.i"
)


def test_surrogate_baseline_prediction() -> None:
    predictor = CoreSurrogatePredictor()

    # Predict at baseline 105 fuel pins
    pred = predictor.predict(105)

    assert math.isclose(pred.keff, 0.84329, abs_tol=0.005)
    assert pred.derived.rho < 0.0
    assert pred.derived.alpha > 0.0
    assert pred.flux_1501 > 0.0
    assert pred.flux_1503 > 0.0
    assert pred.is_high_confidence is True
    assert pred.inference_time_ms < 5.0  # Ultra-fast CPU inference


def test_surrogate_monotonicity() -> None:
    predictor = CoreSurrogatePredictor()

    pred_sub = predictor.predict(60)
    pred_base = predictor.predict(105)
    pred_crit = predictor.predict(140)

    # Adding fuel pins strictly increases keff and reactivity
    assert pred_sub.keff < pred_base.keff < pred_crit.keff
    assert pred_sub.derived.rho < pred_base.derived.rho < pred_crit.derived.rho

    # As core approaches criticality, alpha = (beta - rho)/Lambda decreases
    assert pred_sub.derived.alpha > pred_base.derived.alpha > pred_crit.derived.alpha


def test_surrogate_save_and_load() -> None:
    predictor = CoreSurrogatePredictor()
    pred_orig = predictor.predict(105)

    with tempfile.NamedTemporaryFile(suffix=".joblib", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        predictor.save(tmp_path)
        loaded = CoreSurrogatePredictor.load(tmp_path)
        pred_loaded = loaded.predict(105)

        assert math.isclose(pred_orig.keff, pred_loaded.keff, rel_tol=1e-9)
        assert math.isclose(pred_orig.derived.alpha, pred_loaded.derived.alpha, rel_tol=1e-9)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def test_flux_tilt_symmetry() -> None:
    predictor = CoreSurrogatePredictor()
    # In perfectly symmetric 105-pin configuration, flux tilt should be near zero
    pred = predictor.predict(105)
    assert abs(pred.flux_tilt) < 0.05
