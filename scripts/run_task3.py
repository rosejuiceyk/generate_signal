import numpy as np
import copy
from pathlib import Path
from he3sim.config import load_config
from he3sim.physics.events import simulate_true_events
from he3sim.physics.pulse_models import normalized_double_exponential
from he3sim.analysis.continuous_noise import compute_vtm_waveform, _f1
from scipy.optimize import least_squares
from scipy.fft import fft, ifft
from scipy.signal import welch
import matplotlib.pyplot as plt

def run_task3():
    print("=== Task 3: Continuous Signal Inversion ===")
    out_dir = Path("../output_v4/new_results")
    out_dir.mkdir(parents=True, exist_ok=True)
    
    cfg = load_config(Path("configs/demo_correlated.yaml"))
    
    alpha_true = 1000.0
    k = 0.7
    eff = 0.35
    rate = 5000.0
    dur = 300.0
    sample_rate = 1_000_000.0 # 1 MHz
    
    cfg.simulation.true_rate_cps.value = rate
    cfg.source_model.alpha.value = alpha_true
    cfg.source_model.k_eff.value = k
    cfg.source_model.detection_efficiency.value = eff
    cfg.source_model.source_rate_cps.value = rate * (1.0 - k) / eff
    cfg.observation.mode = "fixed_duration"
    cfg.observation.duration_s.value = dur
    cfg.metadata.seed.value = 42
    cfg.source_model.max_total_reactions = 20_000_000
    
    print("Generating events...")
    sim = simulate_true_events(cfg, max_expected_events=2000000)
    times = sim.events["t_s"]
    times = times[times <= dur]
    
    print("Rendering 300s waveform...")
    n_samples = int(dur * sample_rate)
    voltage = np.zeros(n_samples, dtype=np.float32)
    
    tau_r = 1e-8
    tau_d = 40e-6
    
    # Simple pileup
    # To be fast, we'll discretize event times to indices and add a pulse template
    t_pulse = np.arange(0, 10*tau_d, 1.0/sample_rate)
    pulse = (np.exp(-t_pulse/tau_d) - np.exp(-t_pulse/tau_r)).astype(np.float32)
    pulse /= np.max(pulse)
    
    indices = (times * sample_rate).astype(np.int64)
    # Filter out out of bounds
    indices = indices[indices < n_samples]
    
    # Just add pulses
    from numba import njit
    @njit
    def add_pulses(volt, idxs, p):
        for i in idxs:
            end = min(len(volt), i + len(p))
            volt[i:end] += p[:end-i]
    add_pulses(voltage, indices, pulse)
    
    # 1. VTM
    print("Computing VTM...")
    gates = np.geomspace(1e-4, 0.1, 50)
    gates, vtm_vals = compute_vtm_waveform(voltage, sample_rate, gates)
    # Fit VTM
    def vtm_resid(p):
        a, d, c = np.exp(p)
        return (c + d * _f1(a * gates) - vtm_vals) / np.std(vtm_vals)
    
    y0_guess = np.clip(np.max(vtm_vals) - np.min(vtm_vals), 1e-15, None)
    c0_guess = max(np.min(vtm_vals), 1e-15)
    r_vtm = least_squares(vtm_resid, np.log([1000.0, y0_guess, c0_guess]), max_nfev=1000)
    a_vtm, d_vtm, c_vtm = np.exp(r_vtm.x)
    print(f"VTM Alpha: {a_vtm:.2f} (True: 1000)")
    
    # 2. PSD
    print("Computing PSD...")
    f, Pxx = welch(voltage, fs=sample_rate, nperseg=int(sample_rate/10)) # 10Hz res
    w = 2 * np.pi * f
    # Only fit low frequencies to avoid pulse shape roll-off at 1/tau_d = 25000 rad/s
    mask = (w > 0) & (w < 2000 * 2 * np.pi)
    w_fit = w[mask]
    Pxx_fit = Pxx[mask]
    
    def psd_resid(p):
        a, amp, c = np.exp(p)
        model = c + amp / (a**2 + w_fit**2)
        return (np.log(model) - np.log(Pxx_fit))
        
    y_guess = Pxx_fit[0]*1000**2
    c_guess = max(np.min(Pxx_fit), 1e-15)
    r_psd = least_squares(psd_resid, np.log([1000.0, max(y_guess, 1e-15), c_guess]), max_nfev=1000)
    a_psd, amp_psd, c_psd = np.exp(r_psd.x)
    print(f"PSD Alpha: {a_psd:.2f} (True: 1000)")
    
    # 3. ACF (Log-delay binning)
    print("Computing ACF...")
    v_c = voltage - np.mean(voltage)
    v_f = fft(v_c)
    acf = np.real(ifft(v_f * np.conj(v_f)))[:n_samples//2] / len(v_c)
    lags = np.arange(len(acf)) / sample_rate
    
    log_bins = np.geomspace(1e-4, 0.1, 50)
    acf_log = np.zeros_like(log_bins)
    for i, t in enumerate(log_bins):
        idx = int(t * sample_rate)
        acf_log[i] = acf[idx]
        
    def acf_resid(p):
        # We need a sign logic for c because c can be negative!
        # Instead of np.exp(p), use p directly or just shift.
        a = np.exp(p[0])
        phi = np.exp(p[1])
        c = p[2]
        model = c + phi * np.exp(-a * log_bins)
        return (model - acf_log) / np.std(acf_log)
        
    c0 = np.min(acf_log)
    y0 = np.max(acf_log) - c0
    r_acf = least_squares(acf_resid, [np.log(1000.0), np.log(max(y0, 1e-15)), c0], max_nfev=1000)
    a_acf = np.exp(r_acf.x[0])
    phi_acf = np.exp(r_acf.x[1])
    c_acf = r_acf.x[2]
    print(f"ACF Alpha: {a_acf:.2f} (True: 1000)")
    
    plt.figure()
    plt.plot(gates, vtm_vals, 'o', label='VTM')
    plt.plot(gates, c_vtm + d_vtm * _f1(a_vtm * gates), '-', label=f'Fit $\\alpha$={a_vtm:.0f}')
    plt.xscale('log')
    plt.legend()
    plt.title('VTM')
    plt.savefig(out_dir / "task3_vtm.png")
    
    plt.figure()
    plt.plot(w, Pxx, 'o', alpha=0.1, label='PSD')
    plt.plot(w, c_psd + amp_psd / (a_psd**2 + w**2), '-', label=f'Fit $\\alpha$={a_psd:.0f}')
    plt.xscale('log')
    plt.yscale('log')
    plt.legend()
    plt.title('PSD')
    plt.savefig(out_dir / "task3_psd.png")
    
    plt.figure()
    plt.plot(log_bins, acf_log, 'o', label='ACF')
    plt.plot(log_bins, c_acf + phi_acf * np.exp(-a_acf * log_bins), '-', label=f'Fit $\\alpha$={a_acf:.0f}')
    plt.xscale('log')
    plt.legend()
    plt.title('ACF')
    plt.savefig(out_dir / "task3_acf.png")
    
    with open(out_dir / "task3_results.md", "w", encoding='utf-8') as f:
        f.write(f"## Stage 3 Continuous Signal Inversion\n")
        f.write(f"- True Alpha: {alpha_true}\n")
        f.write(f"- VTM Alpha: {a_vtm:.2f} ({(a_vtm-alpha_true)/alpha_true*100:.2f}%)\n")
        f.write(f"- PSD Alpha: {a_psd:.2f} ({(a_psd-alpha_true)/alpha_true*100:.2f}%)\n")
        f.write(f"- ACF Alpha: {a_acf:.2f} ({(a_acf-alpha_true)/alpha_true*100:.2f}%)\n")

if __name__ == "__main__":
    run_task3()
