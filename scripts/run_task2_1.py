import numpy as np
import copy
from he3sim.config import load_config
from he3sim.physics.events import simulate_true_events
from he3sim.analysis.noise import analyze_event_noise
from pathlib import Path

def run_task2_1():
    cfg = load_config(Path("configs/demo_correlated.yaml"))
    cfg = copy.deepcopy(cfg)
    cfg.simulation.true_rate_cps.value = 3000.0
    cfg.source_model.alpha.value = 1000.0
    cfg.source_model.k_eff.value = 0.7
    cfg.source_model.detection_efficiency.value = 0.3
    cfg.source_model.source_rate_cps.value = 3000.0 * (1.0 - 0.7) / 0.3
    
    sim = simulate_true_events(cfg, max_expected_events=120_000)
    events = sim.events
    times = events["t_s"]
    amps = events["amplitude_peak_V"]
    
    # 1) cut below threshold
    thresh = np.percentile(amps, 20)
    idx1 = amps > thresh
    eff1 = np.sum(idx1) / len(amps)
    times1 = times[idx1]
    
    # 2) random sample
    rng = np.random.default_rng(42)
    idx2 = rng.random(len(amps)) < eff1
    times2 = times[idx2]
    
    an1 = analyze_event_noise(times1, sim.duration_s)
    an2 = analyze_event_noise(times2, sim.duration_s)
    
    print(f"Total events: {len(amps)}")
    print(f"Eff1: {eff1:.4f}")
    print(f"1) Threshold cut alpha: {an1.feynman.fit.alpha_per_s:.2f}")
    print(f"2) Random sample alpha: {an2.feynman.fit.alpha_per_s:.2f}")
    print(f"1) Rossi alpha: {an1.rossi.fit.alpha_per_s:.2f}")
    print(f"2) Rossi alpha: {an2.rossi.fit.alpha_per_s:.2f}")

    # Output triggering efficiency vs amplitude curve and amplitude distribution of cut events
    import matplotlib.pyplot as plt
    out_dir = Path("../output_v4/new_results")
    out_dir.mkdir(parents=True, exist_ok=True)
    
    plt.figure()
    plt.hist(amps[~idx1], bins=50, alpha=0.5, label='Cut Events')
    plt.hist(amps[idx1], bins=50, alpha=0.5, label='Kept Events')
    plt.legend()
    plt.xlabel('Amplitude (V)')
    plt.ylabel('Counts')
    plt.title('Amplitude Distribution (Threshold Cut)')
    plt.savefig(out_dir / 'task2_1_amplitude_dist.png')
    
    # Feynman Y curves
    plt.figure()
    plt.plot(an1.feynman.x, an1.feynman.observed, label='Threshold Cut')
    plt.plot(an2.feynman.x, an2.feynman.observed, label='Random Sample')
    plt.plot(an1.feynman.x, an1.feynman.fitted, '--', label='Fit 1')
    plt.plot(an2.feynman.x, an2.feynman.fitted, '--', label='Fit 2')
    plt.legend()
    plt.xscale('log')
    plt.xlabel('Gate Width T (s)')
    plt.ylabel('Feynman Y(T)')
    plt.title('Feynman Y(T) Comparison')
    plt.savefig(out_dir / 'task2_1_feynman_y.png')

    with open(out_dir / 'task2_1_results.csv', 'w') as f:
        f.write("Method,alpha_rossi,alpha_feynman,alpha_psd\n")
        f.write(f"Threshold,{an1.rossi.fit.alpha_per_s:.2f},{an1.feynman.fit.alpha_per_s:.2f},{an1.psd.fit.alpha_per_s:.2f}\n")
        f.write(f"Random,{an2.rossi.fit.alpha_per_s:.2f},{an2.feynman.fit.alpha_per_s:.2f},{an2.psd.fit.alpha_per_s:.2f}\n")

if __name__ == "__main__":
    run_task2_1()
