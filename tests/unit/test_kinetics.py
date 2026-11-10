"""Unit tests for reactor point kinetics calculations and ODE solver."""

from __future__ import annotations

import math

import numpy as np
import pytest

from he3sim.core.kinetics import (
    DEFAULT_DELAYED_GROUPS_U235,
    PointKineticsSolver,
    compute_prompt_decay_constant,
    compute_reactivity,
    compute_subcritical_multiplication,
    derive_kinetics_state,
    reactivity_to_dollars,
    reactivity_to_pcm,
    solve_inhour_equation,
)


def test_reactivity_and_conversions() -> None:
    # Critical state
    assert compute_reactivity(1.0) == 0.0
    assert reactivity_to_pcm(0.0) == 0.0
    assert reactivity_to_dollars(0.0, 0.007) == 0.0

    # Subcritical benchmark state: keff = 0.84329
    keff = 0.84329
    rho = compute_reactivity(keff)
    expected_rho = (0.84329 - 1.0) / 0.84329
    assert math.isclose(rho, expected_rho, rel_tol=1e-9)

    pcm = reactivity_to_pcm(rho)
    assert math.isclose(pcm, expected_rho * 1e5, rel_tol=1e-9)

    dollars = reactivity_to_dollars(rho, beta_eff=0.0072)
    assert math.isclose(dollars, expected_rho / 0.0072, rel_tol=1e-9)

    with pytest.raises(ValueError):
        compute_reactivity(0.0)
    with pytest.raises(ValueError):
        compute_reactivity(-0.5)
    with pytest.raises(ValueError):
        reactivity_to_dollars(rho, beta_eff=0.0)


def test_prompt_decay_constant() -> None:
    beta_eff = 0.0072
    lambda_gen = 2.5e-5
    keff = 0.84329
    rho = compute_reactivity(keff)

    alpha = compute_prompt_decay_constant(rho, beta_eff, lambda_gen)
    expected_alpha = (beta_eff - rho) / lambda_gen
    assert math.isclose(alpha, expected_alpha, rel_tol=1e-9)
    assert alpha > 0.0  # Positive convention for subcritical

    # Critical alpha = beta_eff / Lambda
    alpha_crit = compute_prompt_decay_constant(0.0, beta_eff, lambda_gen)
    assert math.isclose(alpha_crit, beta_eff / lambda_gen, rel_tol=1e-9)


def test_subcritical_multiplication() -> None:
    assert math.isclose(compute_subcritical_multiplication(0.8), 5.0, rel_tol=1e-9)
    assert math.isclose(compute_subcritical_multiplication(0.9), 10.0, rel_tol=1e-9)
    assert compute_subcritical_multiplication(1.0) == float("inf")
    assert compute_subcritical_multiplication(1.05) == float("inf")

    with pytest.raises(ValueError):
        compute_subcritical_multiplication(-0.1)


def test_inhour_equation_supercritical() -> None:
    beta_eff = 0.0072
    lambda_gen = 2.5e-5

    # Critical -> infinite period
    assert math.isinf(solve_inhour_equation(0.0, beta_eff, lambda_gen))

    # Supercritical: 100 pcm step
    rho = 0.001
    period_s = solve_inhour_equation(rho, beta_eff, lambda_gen)
    assert period_s > 0.0
    omega = 1.0 / period_s

    # Back-substitute into inhour equation: rho_check should match rho
    total_rel = sum(g.fraction for g in DEFAULT_DELAYED_GROUPS_U235)
    abs_betas = [(g.fraction / total_rel) * beta_eff for g in DEFAULT_DELAYED_GROUPS_U235]
    lambdas = [g.decay_constant for g in DEFAULT_DELAYED_GROUPS_U235]

    rho_check = omega * lambda_gen + sum(
        (b * omega) / (omega + lam) for b, lam in zip(abs_betas, lambdas, strict=True)
    )
    assert math.isclose(rho, rho_check, rel_tol=1e-5)


def test_derive_kinetics_state() -> None:
    state = derive_kinetics_state(keff=0.84329, beta_eff=0.0072, lambda_gen=2.5e-5)
    assert state.keff == 0.84329
    assert state.rho < 0.0
    assert state.alpha > 0.0
    assert state.subcritical_mult > 1.0


def test_point_kinetics_steady_state() -> None:
    beta_eff = 0.0072
    lambda_gen = 2.5e-5
    solver = PointKineticsSolver(beta_eff=beta_eff, lambda_gen=lambda_gen)

    rho_0 = -0.05
    s_0 = 1000.0

    n_0, c_0 = solver.compute_steady_state(rho_0, s_0)
    assert n_0 > 0.0
    assert len(c_0) == 6

    # Verify steady state over 5 seconds
    t_eval, n_eval = solver.solve(
        t_span=(0.0, 5.0),
        rho_func=lambda t: rho_0,
        source_func=lambda t: s_0,
        n_init=n_0,
        c_init=c_0,
    )

    # Neutron population must remain within 0.1% of steady state
    assert np.allclose(n_eval, n_0, rtol=1e-3)
