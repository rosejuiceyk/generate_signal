"""Point reactor kinetics and derived physical parameters for YBS core."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
from scipy.integrate import solve_ivp
from scipy.optimize import root_scalar


@dataclass(frozen=True, slots=True)
class DelayedNeutronGroup:
    """Delayed neutron precursor group properties."""

    fraction: float  # Absolute or relative group delayed fraction beta_i
    decay_constant: float  # Decay constant lambda_i (1/s)


# Standard 6-group delayed neutron parameters for U-235 (Keepin fast/thermal benchmark)
# Total sum of relative fractions is 1.0.
DEFAULT_DELAYED_GROUPS_U235: tuple[DelayedNeutronGroup, ...] = (
    DelayedNeutronGroup(fraction=0.033, decay_constant=0.0124),  # Group 1: ~55s half-life
    DelayedNeutronGroup(fraction=0.219, decay_constant=0.0305),  # Group 2: ~22s
    DelayedNeutronGroup(fraction=0.196, decay_constant=0.111),  # Group 3: ~6s
    DelayedNeutronGroup(fraction=0.395, decay_constant=0.301),  # Group 4: ~2s
    DelayedNeutronGroup(fraction=0.115, decay_constant=1.14),  # Group 5: ~0.6s
    DelayedNeutronGroup(fraction=0.042, decay_constant=3.01),  # Group 6: ~0.2s
)


@dataclass(frozen=True, slots=True)
class KineticsDerivedState:
    """Derived physical quantities computed from fundamental reactor state."""

    keff: float
    beta_eff: float
    lambda_gen: float  # Generation time Lambda (s)
    rho: float  # Reactivity (dk/k)
    rho_pcm: float  # Reactivity in pcm (1 pcm = 1e-5)
    rho_dollars: float  # Reactivity in dollars ($)
    alpha: float  # Prompt neutron decay constant (1/s), positive convention
    subcritical_mult: float  # Subcritical multiplication factor M = 1 / (1 - keff)
    stable_period_s: float  # Asymptotic reactor period T = 1 / omega (s)


def compute_reactivity(keff: float) -> float:
    """Compute reactivity rho = (keff - 1) / keff.

    Parameters
    ----------
    keff : float
        Effective neutron multiplication factor (must be positive).

    Returns
    -------
    float
        Dimensionless reactivity rho.
    """
    if keff <= 0.0:
        raise ValueError(f"keff must be strictly positive, got {keff}")
    return (keff - 1.0) / keff


def reactivity_to_pcm(rho: float) -> float:
    """Convert reactivity to pcm (1 pcm = 1e-5)."""
    return rho * 1.0e5


def reactivity_to_dollars(rho: float, beta_eff: float) -> float:
    """Convert reactivity to dollars ($ = rho / beta_eff)."""
    if beta_eff <= 0.0:
        raise ValueError(f"beta_eff must be positive, got {beta_eff}")
    return rho / beta_eff


def compute_prompt_decay_constant(rho: float, beta_eff: float, lambda_gen: float) -> float:
    """Compute prompt neutron decay constant alpha = (beta_eff - rho) / Lambda.

    Uses positive sign convention: for subcritical (rho < 0) and critical (rho = 0),
    alpha is strictly positive.

    Parameters
    ----------
    rho : float
        Reactivity (dk/k).
    beta_eff : float
        Effective delayed neutron fraction.
    lambda_gen : float
        Prompt neutron generation time Lambda in seconds.

    Returns
    -------
    float
        Prompt neutron decay constant alpha in 1/s.
    """
    if lambda_gen <= 0.0:
        raise ValueError(f"lambda_gen must be positive, got {lambda_gen}")
    return (beta_eff - rho) / lambda_gen


def compute_subcritical_multiplication(keff: float) -> float:
    """Compute subcritical multiplication factor M = 1 / (1 - keff).

    For keff >= 1.0, returns infinity or raises ValueError.
    """
    if keff >= 1.0:
        return float("inf")
    if keff < 0.0:
        raise ValueError(f"keff cannot be negative, got {keff}")
    return 1.0 / (1.0 - keff)


def solve_inhour_equation(
    rho: float,
    beta_eff: float,
    lambda_gen: float,
    delayed_groups: tuple[DelayedNeutronGroup, ...] | None = None,
) -> float:
    """Solve the inhour equation for the dominant asymptotic reactor period T = 1 / omega.

    The inhour equation:
        rho = omega * Lambda + sum_{i=1}^6 [ (beta_i * omega) / (omega + lambda_i) ]

    Parameters
    ----------
    rho : float
        Reactivity (dk/k).
    beta_eff : float
        Effective delayed neutron fraction.
    lambda_gen : float
        Neutron generation time Lambda (s).
    delayed_groups : tuple of DelayedNeutronGroup, optional
        Precursor groups with relative fractions (summing to 1.0) and decay constants.

    Returns
    -------
    float
        Asymptotic reactor period T in seconds (positive for supercritical,
        negative for subcritical).
        Returns infinity (math.inf) when rho == 0.
    """
    if math.isclose(rho, 0.0, abs_tol=1e-12):
        return math.inf

    groups = delayed_groups or DEFAULT_DELAYED_GROUPS_U235
    total_rel = sum(g.fraction for g in groups)
    abs_betas = [(g.fraction / total_rel) * beta_eff for g in groups]
    lambdas = [g.decay_constant for g in groups]

    def inhour_residual(w: float) -> float:
        val = w * lambda_gen
        for b_i, l_i in zip(abs_betas, lambdas, strict=True):
            val += (b_i * w) / (w + l_i)
        return val - rho

    if rho > 0.0:
        # Supercritical: single positive root w > 0.
        # Find bracket [0, w_max]
        w_low = 0.0
        w_high = max(1.0, rho / lambda_gen)
        while inhour_residual(w_high) < 0.0:
            w_high *= 2.0
            if w_high > 1e6:
                break
        res = root_scalar(inhour_residual, bracket=[w_low, w_high], method="brentq")
        if not res.converged:
            raise RuntimeError(f"Failed to solve inhour equation for rho={rho}")
        omega = res.root
        return 1.0 / omega
    else:
        # Subcritical: without external source, dominant root is between -min(lambda_i) and 0.
        min_lambda = min(lambdas)
        eps = 1e-7
        w_low = -min_lambda + eps
        w_high = -eps
        # If residual has same sign, expand search
        f_low = inhour_residual(w_low)
        f_high = inhour_residual(w_high)
        if f_low * f_high <= 0.0:
            res = root_scalar(inhour_residual, bracket=[w_low, w_high], method="brentq")
            omega = res.root
            return 1.0 / omega
        # Fallback to prompt approximation when deeply subcritical
        return -lambda_gen / (beta_eff - rho)


def derive_kinetics_state(
    keff: float,
    beta_eff: float,
    lambda_gen: float,
    delayed_groups: tuple[DelayedNeutronGroup, ...] | None = None,
) -> KineticsDerivedState:
    """Compute full set of derived reactor kinetics parameters."""
    rho = compute_reactivity(keff)
    rho_pcm = reactivity_to_pcm(rho)
    rho_dollars = reactivity_to_dollars(rho, beta_eff)
    alpha = compute_prompt_decay_constant(rho, beta_eff, lambda_gen)
    subcritical_mult = compute_subcritical_multiplication(keff)
    period = solve_inhour_equation(rho, beta_eff, lambda_gen, delayed_groups)

    return KineticsDerivedState(
        keff=keff,
        beta_eff=beta_eff,
        lambda_gen=lambda_gen,
        rho=rho,
        rho_pcm=rho_pcm,
        rho_dollars=rho_dollars,
        alpha=alpha,
        subcritical_mult=subcritical_mult,
        stable_period_s=period,
    )


class PointKineticsSolver:
    """Solves the 6-delayed-group point kinetics differential equations.

    Equations:
        dn/dt = [(rho(t) - beta_eff) / Lambda] * n(t) + sum_i [lambda_i * C_i(t)] + S(t)
        dC_i/dt = (beta_i / Lambda) * n(t) - lambda_i * C_i(t)
    """

    def __init__(
        self,
        beta_eff: float,
        lambda_gen: float,
        delayed_groups: tuple[DelayedNeutronGroup, ...] | None = None,
    ) -> None:
        if beta_eff <= 0.0 or lambda_gen <= 0.0:
            raise ValueError("beta_eff and lambda_gen must be strictly positive")
        self.beta_eff = beta_eff
        self.lambda_gen = lambda_gen
        groups = delayed_groups or DEFAULT_DELAYED_GROUPS_U235
        total_rel = sum(g.fraction for g in groups)
        self.abs_betas = np.array(
            [(g.fraction / total_rel) * beta_eff for g in groups], dtype=np.float64
        )
        self.lambdas = np.array([g.decay_constant for g in groups], dtype=np.float64)

    def compute_steady_state(
        self, rho_0: float, s_0: float
    ) -> tuple[float, npt.NDArray[np.float64]]:
        """Compute equilibrium initial condition (n_0, C_i,0) for subcritical state with source s_0.

        Parameters
        ----------
        rho_0 : float
            Initial reactivity (must be < 0 for source-driven steady state).
        s_0 : float
            Initial neutron source rate S_0 > 0.

        Returns
        -------
        tuple of (n_0, C_array)
        """
        if rho_0 >= 0.0:
            raise ValueError(
                f"Steady state with source requires subcritical rho < 0, got rho={rho_0}"
            )
        if s_0 <= 0.0:
            raise ValueError(f"Source s_0 must be positive, got {s_0}")

        n_0 = (s_0 * self.lambda_gen) / (-rho_0)
        c_0 = (self.abs_betas / (self.lambdas * self.lambda_gen)) * n_0
        return n_0, c_0

    def solve(
        self,
        t_span: tuple[float, float],
        rho_func: Callable[[float], float],
        source_func: Callable[[float], float],
        n_init: float,
        c_init: npt.NDArray[np.float64] | None = None,
        max_step: float = 0.05,
    ) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
        """Simulate point kinetics transient.

        Parameters
        ----------
        t_span : tuple of (t_start, t_end)
        rho_func : callable(t) -> rho(t)
        source_func : callable(t) -> S(t)
        n_init : initial neutron level
        c_init : initial precursor concentrations (6 groups). If None, calculated for steady state.

        Returns
        -------
        tuple of (t_eval, n_eval)
        """
        if c_init is None:
            rho_0 = rho_func(t_span[0])
            s_0 = source_func(t_span[0])
            if rho_0 < 0 and s_0 > 0:
                _, c_init = self.compute_steady_state(rho_0, s_0)
            else:
                c_init = (self.abs_betas / (self.lambdas * self.lambda_gen)) * n_init

        y0 = np.concatenate(([n_init], c_init))

        def ode_sys(t: float, y: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
            n = max(0.0, y[0])
            c = y[1:]
            rho = rho_func(t)
            s = source_func(t)

            dn_dt = ((rho - self.beta_eff) / self.lambda_gen) * n + np.sum(self.lambdas * c) + s
            dc_dt = (self.abs_betas / self.lambda_gen) * n - self.lambdas * c
            return np.concatenate(([dn_dt], dc_dt))

        # Radau solver is stiff-capable and accurate across disparate prompt/delayed timescales
        sol = solve_ivp(
            ode_sys,
            t_span,
            y0,
            method="Radau",
            max_step=max_step,
            vectorized=False,
        )

        return sol.t, np.maximum(0.0, sol.y[0])
