import numpy as np
import copy
from he3sim.config import load_config
from he3sim.synthesis.streaming import prepare_waveform_simulation
from he3sim.analysis.paper_supplement_validation import HighRateProtocol
from pathlib import Path

def run_task2_2():
    print("=== Task 2.2: High-Rate Diagnostic Extension ===")
    
    # Actually, HighRateProtocol in he3sim.analysis.paper_supplement_validation already does high rate!
    # Let's import it and see if we can use it.
    
    out_dir = Path("../output_v4/new_results")
    out_dir.mkdir(parents=True, exist_ok=True)
    
    # Custom high rate loop
    rates = [30.0, 100.0, 300.0, 1000.0, 3000.0, 5000.0, 10000.0, 50000.0, 100000.0, 1000000.0]
    duration = 0.1 # Unified max duration
    seeds = [42, 101, 202]
    
    with open(out_dir / "task2_2_results.csv", "w") as f:
        f.write("rate_cps,seed,duration,n_events,overlap_pct,p90_pct,nrmse_pct,trig_eff_pct\n")
        
        for rate in rates:
            for seed in seeds:
                # We can call the module functions directly
                from he3sim.analysis.paper_supplement_validation import _high_rate_point
                from he3sim.analysis.paper_supplement_validation import _high_rate_point, HighRateProtocol
                from he3sim.config import load_config
                cfg_obj = load_config(Path("configs/demo_correlated.yaml"))
                pt = _high_rate_point(
                    base_config=cfg_obj,
                    protocol=HighRateProtocol(),
                    rate_cps=rate,
                    seed=seed,
                    duration_s=duration,
                    max_expected_events=12000000,
                    max_waveform_samples=150000000
                )
                
                print(f"Rate {rate}, seed {seed}: NRMSE={pt.clipping_nrmse*100:.2f}%, Overlap={pt.overlap_fraction*100:.2f}%, TrigEff={pt.trigger_efficiency*100:.2f}%, P90={pt.peak_bias_p90_abs*100:.2f}%")
                f.write(f"{rate},{seed},{duration},{pt.true_event_count},{pt.overlap_fraction*100:.2f},{pt.peak_bias_p90_abs*100:.2f},{pt.clipping_nrmse*100:.2f},{pt.trigger_efficiency*100:.2f}\n")

if __name__ == "__main__":
    run_task2_2()
