import numpy as np
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from he3sim.config import load_config, SourceModelConfig, ParameterValue, ParameterStatus, He3SimConfig
from he3sim.physics.source_model import PromptSourceModel
from he3sim.physics.chains import BranchingChainGenerator
from he3sim.physics.rate_profiles import ConstantRateProfile
from he3sim.analysis.noise import analyze_event_noise, NoiseAnalysis
from he3sim.analysis.waveform_alpha_validation import run_waveform_alpha_validation
import copy

OUT_DIR = Path("../output_v4/phase1")
OUT_DIR.mkdir(parents=True, exist_ok=True)

def run_table2():
    print("=== Running Table 2 (Event-level) ===", flush=True)
    conditions = [
        {"alpha": 500.0, "eff": 0.30, "rate": 3000.0, "duration": 73.33, "k": 0.7},
        {"alpha": 1000.0, "eff": 0.35, "rate": 5000.0, "duration": 44.00, "k": 0.7},
        {"alpha": 2000.0, "eff": 0.40, "rate": 8000.0, "duration": 27.50, "k": 0.7},
    ]
    seeds = [101, 203, 307, 401, 509] # Using 5 seeds to save time, or 8 seeds? Prompt says "使用相同种子数" (for Table 3). Table 2 didn't specify. The original paper Table 2 has errors from extended scan. I will use 5 seeds here to get valid statistics.
    
    with open(OUT_DIR / "table2_results.csv", "w") as f:
        f.write("alpha_true,eff,rate,duration,n_events,rossi_alpha,rossi_std,rossi_mare,feynman_alpha,feynman_std,feynman_mare,psd_alpha,psd_std,psd_mare\n")
        
        for cond in conditions:
            alpha = cond["alpha"]
            eff = cond["eff"]
            rate = cond["rate"]
            dur = cond["duration"]
            k = cond["k"]
            print(f"Condition: alpha={alpha}, eff={eff}, rate={rate}, dur={dur}, k={k}")
            
            nu_pmf_array = np.array([0.031722, 0.171707, 0.336199, 0.303969, 0.126946, 0.026648, 0.002602, 0.000207])
            nu_bar_exact = float(np.sum(np.arange(8) * nu_pmf_array))
            cfg = SourceModelConfig(
                k_eff=ParameterValue(value=k, status=ParameterStatus.SYNTHETIC_DEMO),
                alpha=ParameterValue(value=alpha, status=ParameterStatus.SYNTHETIC_DEMO),
                detection_efficiency=ParameterValue(value=eff, status=ParameterStatus.SYNTHETIC_DEMO),
                nu_bar=ParameterValue(value=nu_bar_exact, status=ParameterStatus.SYNTHETIC_DEMO),
                source_rate_cps=ParameterValue(value=rate*(1-k)/eff, status=ParameterStatus.SYNTHETIC_DEMO),
                nu_pmf=ParameterValue(value=nu_pmf_array.tolist(), status=ParameterStatus.SYNTHETIC_DEMO)
            )
            model = PromptSourceModel.from_config(cfg)
            
            results = []
            n_ev_list = []
            for seed in seeds:
                rng = np.random.default_rng(seed)
                gen = BranchingChainGenerator(model=model, max_events=20000000, max_total_reactions=200000000)
                times = gen.sample(ConstantRateProfile(model.source_rate_cps), 0.0, dur, rng)
                n_ev_list.append(len(times))
                an = analyze_event_noise(times, dur)
                results.append(an)
                
            r_a = [r.rossi.fit.alpha_per_s for r in results]
            f_a = [r.feynman.fit.alpha_per_s for r in results]
            p_a = [r.psd.fit.alpha_per_s for r in results]
            
            avg_ev = np.mean(n_ev_list)
            r_m, r_s, r_mare = np.mean(r_a), np.std(r_a), np.mean(np.abs(np.array(r_a)-alpha)/alpha)*100
            f_m, f_s, f_mare = np.mean(f_a), np.std(f_a), np.mean(np.abs(np.array(f_a)-alpha)/alpha)*100
            p_m, p_s, p_mare = np.mean(p_a), np.std(p_a), np.mean(np.abs(np.array(p_a)-alpha)/alpha)*100
            
            print(f"  Rossi: {r_m:.2f} +/- {r_s:.2f} ({r_mare:.2f}%)")
            print(f"  Feynman: {f_m:.2f} +/- {f_s:.2f} ({f_mare:.2f}%)")
            print(f"  PSD: {p_m:.2f} +/- {p_s:.2f} ({p_mare:.2f}%)")
            f.write(f"{alpha},{eff},{rate},{dur},{avg_ev:.0f},{r_m:.2f},{r_s:.2f},{r_mare:.2f}%,{f_m:.2f},{f_s:.2f},{f_mare:.2f}%,{p_m:.2f},{p_s:.2f},{p_mare:.2f}%\n")

def _run_single_waveform(args):
    alpha, seed = args
    cfg = load_config(Path("configs/demo_correlated.yaml"))
    cfg = copy.deepcopy(cfg)
    cfg.source_model.alpha.value = alpha
    
    res, _ = run_waveform_alpha_validation(
        cfg,
        duration_s=10.0,
        max_waveform_samples=1_500_000_000,
        true_rate_cps=3000.0, # wait, does table 3 use true_rate_cps=3000.0 for all? In original, table 3 had average events = 29957 (so rate = 3000). Yes.
        alpha_s_inv=alpha,
        sample_rate_hz=100_000_000.0,
        seed=seed,
    )
    
    out = {}
    for cond in [res.reference] + list(res.conditions):
        out[cond.name] = {
            "n_events": cond.accepted_count,
            "rossi_alpha": cond.alpha_rossi_s_inv,
            "feynman_alpha": cond.alpha_feynman_s_inv,
            "psd_alpha": cond.alpha_psd_s_inv,
        }
    return alpha, seed, out

def run_table3():
    print("=== Running Table 3 (Waveform-level) ===", flush=True)
    alphas = [500.0, 1000.0, 2000.0]
    seeds = [42, 101, 202, 303, 404]
    
    args_list = [(a, s) for a in alphas for s in seeds]
    
    with ProcessPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(_run_single_waveform, args_list))
        
    with open(OUT_DIR / "table3_results.csv", "w") as f:
        f.write("alpha_true,condition,n_events,rossi_alpha,rossi_std,rossi_mare,feynman_alpha,feynman_std,feynman_mare,psd_alpha,psd_std,psd_mare\n")
        
        for alpha in alphas:
            print(f"\nAlpha = {alpha}")
            cond_names = ["G0_event_time_reference", "G1_ideal_waveform", "G2_noisy_waveform", "G3_noisy_waveform_deadtime"]
            for cname in cond_names:
                pts = [r[2][cname] for r in results if r[0] == alpha]
                evs = [p['n_events'] for p in pts]
                r_a = [p['rossi_alpha'] for p in pts]
                f_a = [p['feynman_alpha'] for p in pts]
                p_a = [p['psd_alpha'] for p in pts]
                
                avg_ev = np.mean(evs)
                r_m, r_s, r_mare = np.mean(r_a), np.std(r_a), np.mean(np.abs(np.array(r_a)-alpha)/alpha)*100
                f_m, f_s, f_mare = np.mean(f_a), np.std(f_a), np.mean(np.abs(np.array(f_a)-alpha)/alpha)*100
                p_m, p_s, p_mare = np.mean(p_a), np.std(p_a), np.mean(np.abs(np.array(p_a)-alpha)/alpha)*100
                
                print(f"  {cname}:")
                print(f"    Rossi: {r_m:.2f} +/- {r_s:.2f} ({r_mare:.2f}%)")
                print(f"    Feynman: {f_m:.2f} +/- {f_s:.2f} ({f_mare:.2f}%)")
                print(f"    PSD: {p_m:.2f} +/- {p_s:.2f} ({p_mare:.2f}%)")
                f.write(f"{alpha},{cname},{avg_ev:.0f},{r_m:.2f},{r_s:.2f},{r_mare:.2f}%,{f_m:.2f},{f_s:.2f},{f_mare:.2f}%,{p_m:.2f},{p_s:.2f},{p_mare:.2f}%\n")

if __name__ == "__main__":
    t0 = time.time()
    run_table2()
    run_table3()
    print(f"Done in {time.time()-t0:.1f}s")
