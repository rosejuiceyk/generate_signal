"""Reactor Core-to-Detector Signal Physics Bridge.

Links:
- YBS core loading state (fuel pins 31..199) and surrogate physics predictions
- Reactor operational state machine:
    SHUTDOWN: S=0, subcritical, background Poisson noise only (~5-10 cps).
    SOURCE_INJECTED: External source S introduced, subcritical multiplication n = S / (1-keff),
                     drives BranchingChainGenerator for non-Poisson correlated event chains.
    CRITICAL_OPERATION: Reactivity rho(t) >= 0 or small perturbation, 6-group delayed kinetics ODE solver.
    SCRAM: Emergency scram, large prompt negative reactivity step (-3500 pcm), exponential precursor decay.
- Macro-to-micro signal mapping:
    lambda_1(t) = n(t) * f_d1 * eta_1
    lambda_2(t) = n(t) * f_d2 * eta_2
- Pulse synthesis:
    Convolves arrival events with He-3 wall-effect spectrum and double-exponential preamplifier response.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
import time

import numpy as np
import numpy.typing as npt

from he3sim.core.kinetics import PointKineticsSolver, derive_kinetics_state
from he3sim.core.surrogate_model import CorePhysicsPrediction, CoreSurrogatePredictor
from he3sim.physics.arrivals import PoissonUniformArrivalGenerator
from he3sim.physics.chains import BranchingChainGenerator
from he3sim.physics.pulse_models import normalized_double_exponential
from he3sim.physics.rate_profiles import ConstantRateProfile
from he3sim.physics.source_model import PromptSourceModel
from he3sim.physics.spectra import ParametricHe3Spectrum


class ReactorOperationalState(str, Enum):
    """Operational states of the reactor core digital twin."""

    SHUTDOWN = "SHUTDOWN"
    SOURCE_INJECTED = "SOURCE_INJECTED"
    CRITICAL_OPERATION = "CRITICAL_OPERATION"
    SCRAM = "SCRAM"


@dataclass(frozen=True, slots=True)
class CoreSignalBridgeConfig:
    """Configuration for physical macro-to-micro signal translation."""

    source_strength_n_per_s: float = 1.0e6  # External neutron source S (n/s)
    efficiency_ch1: float = 1.5e-3  # Detector 1 efficiency (calibrated to ~1500 cps at ref)
    efficiency_ch2: float = 2.8e-3  # Detector 2 efficiency (calibrated to ~2800 cps at ref)
    background_rate_cps: float = 6.0  # Ambient Poisson background count rate (cps)
    sample_rate_hz: float = 10_000_000.0  # 10 MSa/s for continuous waveform synthesis
    tau_rise_s: float = 100.0e-9  # Preamplifier rise time (100 ns)
    tau_decay_s: float = 2.0e-6  # Preamplifier decay time (2.0 us)
    voltage_noise_v: float = 0.002  # Baseline RMS Gaussian white noise (2 mV)
    max_voltage_v: float = 1.8  # Full-scale pulse voltage into 50 Ohm (V)
    scram_reactivity_pcm: float = -3500.0  # Large negative reactivity for SCRAM


@dataclass(slots=True)
class DetectorSignalBlock:
    """Synthesized signal block for one observation window."""

    state: ReactorOperationalState
    t_start_s: float
    duration_s: float
    timestamps_ch1: npt.NDArray[np.float64]
    timestamps_ch2: npt.NDArray[np.float64]
    energies_ch1: npt.NDArray[np.float64]
    energies_ch2: npt.NDArray[np.float64]
    sample_rate_hz: float
    voltages_ch1: npt.NDArray[np.float64] | None = None
    voltages_ch2: npt.NDArray[np.float64] | None = None
    time_grid_s: npt.NDArray[np.float64] | None = None
    keff: float = 0.84329
    alpha_per_s: float = 7861.6
    reactivity_pcm: float = -18583.2
    flux_tilt: float = 0.0
    rate_cps_ch1: float = 0.0
    rate_cps_ch2: float = 0.0
    generation_time_ms: float = 0.0


def _build_default_he3_spectrum() -> ParametricHe3Spectrum:
    """Build standardized He-3 wall-effect energy spectrum."""
    return ParametricHe3Spectrum(
        full_energy_keV=764.0,
        full_energy_sigma_keV=18.0,
        weights=(0.70, 0.15, 0.15, 0.0),
        proton_wall=(191.0, 764.0, 1.0, 1.0),
        triton_wall=(573.0, 764.0, 1.0, 1.0),
        double_wall=None,
    )


class CoreSignalBridge:
    """Bridge connecting reactor core state to realistic He-3 detector signals."""

    def __init__(
        self,
        config: CoreSignalBridgeConfig | None = None,
        surrogate: CoreSurrogatePredictor | None = None,
        initial_num_pins: int = 105,
    ) -> None:
        self.config = config or CoreSignalBridgeConfig()
        self.surrogate = surrogate or CoreSurrogatePredictor()
        self.state = ReactorOperationalState.SHUTDOWN
        self.num_fuel_pins = initial_num_pins
        self.prediction: CorePhysicsPrediction = self.surrogate.predict(self.num_fuel_pins)
        self.spectrum = _build_default_he3_spectrum()

        # Operational time tracking
        self.current_time_s = 0.0
        self._kinetics_n = 1.0
        self._kinetics_C = np.zeros(6, dtype=np.float64)

    def set_core_loading(self, num_fuel_pins: int) -> CorePhysicsPrediction:
        """Update fuel loading configuration and refresh surrogate physics."""
        self.num_fuel_pins = num_fuel_pins
        self.prediction = self.surrogate.predict(num_fuel_pins)
        return self.prediction

    def transition_to(self, new_state: ReactorOperationalState) -> None:
        """State machine transition with physical continuity."""
        if new_state == self.state:
            return

        if new_state == ReactorOperationalState.CRITICAL_OPERATION:
            solver = PointKineticsSolver(self.prediction.beta_eff, self.prediction.lambda_gen)
            self._kinetics_n = 1.0
            self._kinetics_C = (
                solver.abs_betas / (solver.lambdas * self.prediction.lambda_gen) * self._kinetics_n
            )

        self.state = new_state

    def get_expected_rates(self) -> tuple[float, float]:
        """Compute the instantaneous expected detector rates (cps) for Channel 1 and 2."""
        f1_norm = self.prediction.flux_1501 / 1.23456e-4
        f2_norm = self.prediction.flux_1503 / 2.34567e-4

        if self.state == ReactorOperationalState.SHUTDOWN:
            return self.config.background_rate_cps, self.config.background_rate_cps

        elif self.state == ReactorOperationalState.SOURCE_INJECTED:
            # Subcritical multiplication M = 1 / (1 - keff)
            # Reference baseline at 105 pins: M_ref = 1 / (1 - 0.84329) = 6.381
            subcritical_mult = 1.0 / max(0.001, 1.0 - self.prediction.keff)
            mult_factor = subcritical_mult / 6.3812

            rate1 = self.config.source_strength_n_per_s * self.config.efficiency_ch1 * 1.5e-3 * mult_factor * f1_norm
            rate2 = self.config.source_strength_n_per_s * self.config.efficiency_ch2 * 1.5e-3 * mult_factor * f2_norm
            rate1 = max(self.config.background_rate_cps, rate1)
            rate2 = max(self.config.background_rate_cps, rate2)
            return rate1, rate2

        elif self.state == ReactorOperationalState.CRITICAL_OPERATION:
            nominal_rate = 5000.0 * self._kinetics_n
            rate1 = max(self.config.background_rate_cps, nominal_rate * f1_norm * (self.config.efficiency_ch1 / 1.5e-3))
            rate2 = max(self.config.background_rate_cps, nominal_rate * f2_norm * (self.config.efficiency_ch2 / 1.5e-3))
            return rate1, rate2

        elif self.state == ReactorOperationalState.SCRAM:
            decay_factor = max(0.01, self._kinetics_n)
            rate1 = self.config.background_rate_cps + 5000.0 * decay_factor * f1_norm * 0.05
            rate2 = self.config.background_rate_cps + 5000.0 * decay_factor * f2_norm * 0.05
            return rate1, rate2

        return self.config.background_rate_cps, self.config.background_rate_cps

    def generate_signal_block(
        self,
        duration_s: float = 1.0,
        synthesize_waveforms: bool = False,
        seed: int | None = None,
    ) -> DetectorSignalBlock:
        """Generate a complete block of detector events and optional synthesized waveforms."""
        t0 = time.perf_counter()
        rng = np.random.default_rng(seed if seed is not None else 42)
        t_start = self.current_time_s

        rate1, rate2 = self.get_expected_rates()

        # 1. Event Timestamp Generation
        if self.state == ReactorOperationalState.SHUTDOWN:
            times1 = self._sample_poisson_times(rate1, duration_s, t_start, rng)
            times2 = self._sample_poisson_times(rate2, duration_s, t_start, rng)

        elif self.state == ReactorOperationalState.SOURCE_INJECTED:
            times1, times2 = self._sample_branching_events(rate1, rate2, duration_s, t_start, rng)

        elif self.state == ReactorOperationalState.CRITICAL_OPERATION:
            solver = PointKineticsSolver(self.prediction.beta_eff, self.prediction.lambda_gen)
            rho_step = (self.prediction.keff - 1.0) / self.prediction.keff
            _, n_eval = solver.solve(
                t_span=(0.0, duration_s),
                rho_func=lambda t: rho_step,
                source_func=lambda t: 100.0,
                n_init=self._kinetics_n,
                c_init=self._kinetics_C,
            )
            self._kinetics_n = float(n_eval[-1])
            times1 = self._sample_inhomogeneous_poisson(rate1, n_eval, duration_s, t_start, rng)
            times2 = self._sample_inhomogeneous_poisson(rate2, n_eval, duration_s, t_start, rng)

        elif self.state == ReactorOperationalState.SCRAM:
            solver = PointKineticsSolver(self.prediction.beta_eff, self.prediction.lambda_gen)
            scram_rho = self.config.scram_reactivity_pcm * 1e-5
            _, n_eval = solver.solve(
                t_span=(0.0, duration_s),
                rho_func=lambda t: scram_rho,
                source_func=lambda t: 0.0,
                n_init=self._kinetics_n,
                c_init=self._kinetics_C,
            )
            self._kinetics_n = float(n_eval[-1])
            times1 = self._sample_inhomogeneous_poisson(rate1, n_eval, duration_s, t_start, rng)
            times2 = self._sample_inhomogeneous_poisson(rate2, n_eval, duration_s, t_start, rng)
        else:
            times1 = np.empty(0, dtype=np.float64)
            times2 = np.empty(0, dtype=np.float64)

        # 2. Sample Deposited Energies from He-3 Wall Effect Spectrum
        energies1 = (
            self.spectrum.sample(len(times1), rng).energies_keV
            if len(times1) > 0
            else np.empty(0, dtype=np.float64)
        )
        energies2 = (
            self.spectrum.sample(len(times2), rng).energies_keV
            if len(times2) > 0
            else np.empty(0, dtype=np.float64)
        )

        # 3. Waveform Synthesis (Optional)
        v1 = None
        v2 = None
        t_grid = None
        if synthesize_waveforms and duration_s > 0:
            num_samples = int(duration_s * self.config.sample_rate_hz)
            t_grid = np.linspace(0.0, duration_s, num_samples, endpoint=False, dtype=np.float64)
            v1 = self._synthesize_waveform(times1 - t_start, energies1, t_grid, rng)
            v2 = self._synthesize_waveform(times2 - t_start, energies2, t_grid, rng)

        self.current_time_s += duration_s
        gen_time_ms = (time.perf_counter() - t0) * 1000.0

        return DetectorSignalBlock(
            state=self.state,
            t_start_s=t_start,
            duration_s=duration_s,
            timestamps_ch1=times1,
            timestamps_ch2=times2,
            energies_ch1=energies1,
            energies_ch2=energies2,
            sample_rate_hz=self.config.sample_rate_hz,
            voltages_ch1=v1,
            voltages_ch2=v2,
            time_grid_s=t_grid,
            keff=self.prediction.keff,
            alpha_per_s=self.prediction.derived.alpha,
            reactivity_pcm=self.prediction.derived.reactivity_pcm,
            flux_tilt=self.prediction.flux_tilt,
            rate_cps_ch1=float(len(times1)) / duration_s if duration_s > 0 else 0.0,
            rate_cps_ch2=float(len(times2)) / duration_s if duration_s > 0 else 0.0,
            generation_time_ms=gen_time_ms,
        )

    def _sample_poisson_times(
        self,
        rate: float,
        duration_s: float,
        t_start_s: float,
        rng: np.random.Generator,
    ) -> npt.NDArray[np.float64]:
        """Sample homogeneous Poisson arrival timestamps."""
        if rate <= 0.0 or duration_s <= 0.0:
            return np.empty(0, dtype=np.float64)
        expected_n = rate * duration_s
        n_events = rng.poisson(expected_n)
        if n_events <= 0:
            return np.empty(0, dtype=np.float64)
        times = rng.uniform(0.0, duration_s, size=n_events)
        times.sort()
        return times + t_start_s

    def _sample_inhomogeneous_poisson(
        self,
        base_rate: float,
        amplitude_profile: npt.NDArray[np.float64],
        duration_s: float,
        t_start_s: float,
        rng: np.random.Generator,
    ) -> npt.NDArray[np.float64]:
        """Thinning algorithm for inhomogeneous Poisson arrivals."""
        max_amp = float(np.max(amplitude_profile)) if len(amplitude_profile) > 0 else 1.0
        max_rate = max(10.0, base_rate * max_amp)
        raw_times = self._sample_poisson_times(max_rate, duration_s, 0.0, rng)
        if len(raw_times) == 0:
            return np.empty(0, dtype=np.float64)

        # Thinning acceptance probability
        norm_times = raw_times / duration_s
        amp_interp = np.interp(
            norm_times, np.linspace(0.0, 1.0, len(amplitude_profile)), amplitude_profile
        )
        p_accept = np.clip(amp_interp / max_amp, 0.0, 1.0)
        accepted = rng.uniform(0.0, 1.0, size=len(raw_times)) < p_accept
        return raw_times[accepted] + t_start_s

    def _sample_branching_events(
        self,
        rate1: float,
        rate2: float,
        duration_s: float,
        t_start_s: float,
        rng: np.random.Generator,
    ) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
        """Generate correlated non-Poisson events using BranchingChainGenerator."""
        total_rate = rate1 + rate2
        alpha = self.prediction.derived.alpha
        keff = self.prediction.keff
        nu_bar = 2.45

        # Build PromptSourceModel
        lambda_t = alpha / max(0.001, 1.0 - keff)
        lambda_f = keff * lambda_t / nu_bar
        # Calibration of detection rate
        lambda_d = min(lambda_t * 0.05, total_rate / max(1.0, self.config.source_strength_n_per_s) * lambda_t)
        lambda_c = max(0.0, lambda_t - lambda_f - lambda_d)

        nu_pmf = np.array([0.026, 0.155, 0.339, 0.302, 0.133, 0.045], dtype=np.float64)
        factorial_second = float(np.sum(np.arange(6) * (np.arange(6) - 1.0) * nu_pmf))
        diven = factorial_second / (nu_bar * nu_bar)

        source_model = PromptSourceModel(
            k_eff=keff,
            reactivity=(keff - 1.0) / keff,
            alpha_per_s=alpha,
            detection_efficiency=lambda_d / lambda_t,
            nu_bar=nu_bar,
            nu_pmf=nu_pmf,
            source_rate_cps=self.config.source_strength_n_per_s,
            lambda_f_per_s=lambda_f,
            lambda_c_per_s=lambda_c,
            lambda_d_per_s=lambda_d,
            lambda_t_per_s=lambda_t,
            mean_reaction_time_s=1.0 / lambda_t,
            generation_time_s=1.0 / (nu_bar * lambda_f),
            diven_factor=diven,
            expected_detected_rate_cps=total_rate,
        )

        chain_gen = BranchingChainGenerator(
            model=source_model,
            max_events=max(10_000, int(total_rate * duration_s * 4)),
        )

        profile = ConstantRateProfile(rate_cps=min(1e7, max(10.0, total_rate)))
        batch = chain_gen.sample_with_lineage(
            profile=profile,
            t_start_s=t_start_s,
            duration_s=duration_s,
            rng=rng,
        )

        # Channel assignment: proportional to relative rate
        all_times = batch.times_s
        if len(all_times) == 0:
            times1 = np.empty(0, dtype=np.float64)
            times2 = np.empty(0, dtype=np.float64)
        else:
            p_ch1 = rate1 / total_rate
            mask1 = rng.uniform(0.0, 1.0, size=len(all_times)) < p_ch1
            times1 = all_times[mask1]
            times2 = all_times[~mask1]

        # Add independent background counts
        bg1 = self._sample_poisson_times(self.config.background_rate_cps, duration_s, t_start_s, rng)
        bg2 = self._sample_poisson_times(self.config.background_rate_cps, duration_s, t_start_s, rng)

        if len(bg1) > 0:
            times1 = np.sort(np.concatenate([times1, bg1]))
        if len(bg2) > 0:
            times2 = np.sort(np.concatenate([times2, bg2]))

        return times1, times2

    def _synthesize_waveform(
        self,
        event_times_s: npt.NDArray[np.float64],
        energies_keV: npt.NDArray[np.float64],
        t_grid_s: npt.NDArray[np.float64],
        rng: np.random.Generator,
    ) -> npt.NDArray[np.float64]:
        """Convolve arrival events with double-exponential kernel and add baseline noise."""
        num_samples = len(t_grid_s)
        signal = np.zeros(num_samples, dtype=np.float64)

        if len(event_times_s) == 0:
            noise = rng.normal(0.0, self.config.voltage_noise_v, size=num_samples)
            return signal + noise

        # Pulse length up to 6 decay time constants
        pulse_duration_s = 6.0 * self.config.tau_decay_s
        pulse_samples = int(pulse_duration_s * self.config.sample_rate_hz)
        tau_grid = np.linspace(0.0, pulse_duration_s, pulse_samples, dtype=np.float64)
        pulse_shape = normalized_double_exponential(
            tau_grid, self.config.tau_rise_s, self.config.tau_decay_s
        )

        # Superpose pulses
        for t_evt, e_evt in zip(event_times_s, energies_keV):
            if t_evt < 0.0 or t_evt >= t_grid_s[-1]:
                continue
            idx_start = int(t_evt * self.config.sample_rate_hz)
            idx_end = min(num_samples, idx_start + pulse_samples)
            span = idx_end - idx_start
            if span > 0:
                amplitude = (e_evt / 764.0) * self.config.max_voltage_v
                signal[idx_start:idx_end] += amplitude * pulse_shape[:span]

        # Add Gaussian white noise
        noise = rng.normal(0.0, self.config.voltage_noise_v, size=num_samples)
        return signal + noise

    def verify_subcritical_scaling(self, test_pins: list[int] | None = None) -> float:
        """Verify that subcritical multiplication scales with 1 / (1 - keff) within 2% deviation."""
        if test_pins is None:
            test_pins = [49, 67, 85, 105, 125]

        rates = []
        inv_rho = []
        for p in test_pins:
            self.set_core_loading(p)
            self.transition_to(ReactorOperationalState.SOURCE_INJECTED)
            r1, r2 = self.get_expected_rates()
            rates.append(r1 + r2)
            inv_rho.append(1.0 / (1.0 - self.prediction.keff))

        rates_arr = np.array(rates)
        inv_rho_arr = np.array(inv_rho)

        # Linear regression slope: Rate = C * (1 / (1 - keff))
        slope = float(np.sum(rates_arr * inv_rho_arr) / np.sum(inv_rho_arr**2))
        fitted = slope * inv_rho_arr
        rel_errors = np.abs(rates_arr - fitted) / fitted
        max_error = float(np.max(rel_errors))
        return max_error
