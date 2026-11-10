import numpy as np
import copy
from he3sim.config import load_config
from he3sim.physics.events import simulate_true_events
from he3sim.analysis.noise import analyze_event_noise
from pathlib import Path

def run_task2_3():
    print("=== Task 2.3: Record Duration Scan ===")
    out_dir = Path("../output_v4/new_results")
    out_dir.mkdir(parents=True, exist_ok=True)
    
    cfg = load_config(Path("configs/demo_correlated.yaml"))
    cfg = copy.deepcopy(cfg)
    
    rate = 5000.0
    k = 0.7
    eff = 0.35
    alpha = 1000.0
    
    cfg.simulation.true_rate_cps.value = rate
    cfg.source_model.alpha.value = alpha
    cfg.source_model.k_eff.value = k
    cfg.source_model.detection_efficiency.value = eff
    cfg.source_model.source_rate_cps.value = rate * (1.0 - k) / eff
    cfg.source_model.max_total_reactions = 20_000_000
    
    durations = [10.0, 30.0, 100.0, 300.0]
    seeds = [1, 2, 3, 4, 5]
    
    with open(out_dir / "task2_3_results.csv", "w") as f:
        f.write("duration_s,seed,n_events,rossi_alpha,feynman_alpha,psd_alpha\n")
        
        for dur in durations:
            for seed in seeds:
                print(f"Duration {dur}s, Seed {seed}")
                # We can't really "reseed" the times easily, so we just run independent simulations.
                # Actually, the task says "控制 α=1000 ... 使用独立的几个随机种子 ... " 
                # Let's generate a fresh simulation for each seed to be proper.
                
                cfg_s = copy.deepcopy(cfg)
                cfg_s.metadata.seed.value = seed
                cfg_s.observation.mode = "fixed_duration"
                cfg_s.observation.duration_s.value = dur
                sim_s = simulate_true_events(cfg_s, max_expected_events=int(rate * dur * 1.1 + 10000))
                times_s = sim_s.events["t_s"]
                
                # Cut at exactly dur
                times_cut = times_s[times_s <= dur]
                
                an = analyze_event_noise(times_cut, dur)
                
                f.write(f"{dur},{seed},{len(times_cut)},{an.rossi.fit.alpha_per_s:.2f},{an.feynman.fit.alpha_per_s:.2f},{an.psd.fit.alpha_per_s:.2f}\n")
                
if __name__ == "__main__":
    run_task2_3()
