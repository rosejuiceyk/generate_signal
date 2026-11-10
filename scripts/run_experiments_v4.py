"""Optimized runner for manuscript v2 improved experiments:
1. Multi-seed (5 seeds) waveform-to-alpha closed loop validation (Table 2) with multiprocessing.
2. Steady-state high-count-rate diagnostic with warmup (Table 3 & Fig 4).
"""

from __future__ import annotations

import csv
import json
import math
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np

from he3sim.acquisition.trigger import ThresholdTrigger
from he3sim.analysis.waveform_alpha_validation import run_waveform_alpha_validation
from he3sim.config import He3SimConfig, load_config
from he3sim.physics.pulse_models import double_exponential_peak_time_s
from he3sim.synthesis.renderers import render_direct_sparse_block
from he3sim.synthesis.streaming import iter_waveform_blocks, prepare_waveform_simulation

OUT_DIR = Path("outputs/v2_validation")
OUT_DIR.mkdir(parents=True, exist_ok=True)


def _required_number(value: float | int | None, name: str) -> float:
    if value is None:
        raise ValueError(f"{name} requires an explicit configured value")
    return float(value)


def _safe_nrmse(observed: np.ndarray, reference: np.ndarray) -> float:
    denominator = float(np.sqrt(np.mean(np.square(reference))))
    numerator = float(np.sqrt(np.mean(np.square(observed - reference))))
    if denominator > 0.0:
        return numerator / denominator
    if numerator == 0.0:
        return 0.0
    raise ValueError("NRMSE is undefined for a zero reference with nonzero error")


def _overlap_fraction(times_s: np.ndarray, support_s: float) -> float:
    if times_s.size < 2:
        return 0.0
    gaps = np.diff(times_s)
    previous = np.concatenate(([np.inf], gaps))
    following = np.concatenate((gaps, [np.inf]))
    return float(np.mean(np.minimum(previous, following) < support_s))


def _trigger_metrics(
    candidates_s: np.ndarray,
    true_events: np.ndarray,
    config: He3SimConfig,
) -> tuple[float, float]:
    if candidates_s.size == 0:
        return 0.0, 0.0
    event_times = true_events["t_s"]
    used = np.zeros(event_times.size, dtype=np.bool_)
    matched = 0
    unmatched = 0
    before_s = _required_number(config.trigger.pre_trigger_s.value, "pre_trigger_s")
    after_s = _required_number(config.trigger.post_trigger_s.value, "post_trigger_s")
    for trigger_s in candidates_s:
        start = int(np.searchsorted(event_times, trigger_s - before_s, side="left"))
        stop = int(np.searchsorted(event_times, trigger_s + after_s, side="right"))
        local = np.flatnonzero(~used[start:stop]) + start
        if local.size == 0:
            unmatched += 1
            continue
        nearest = int(local[int(np.argmin(np.abs(event_times[local] - trigger_s)))])
        used[nearest] = True
        matched += 1
    efficiency = matched / true_events.size if true_events.size else 0.0
    return float(efficiency), float(unmatched / candidates_s.size)


def _event_peak_indices(events: np.ndarray, sample_rate_hz: float) -> np.ndarray:
    indices = np.empty(events.size, dtype=np.int64)
    for index, event in enumerate(events):
        event_time = float(event["t_s"])
        tau_r = float(event["tau_r_s"])
        tau_d = float(event["tau_d_s"])
        peak = event_time + double_exponential_peak_time_s(tau_r, tau_d)
        onset = math.ceil(event_time * sample_rate_hz)
        candidates = np.asarray(
            [
                onset,
                max(onset, math.floor(peak * sample_rate_hz)),
                math.ceil(peak * sample_rate_hz),
            ],
            dtype=np.int64,
        )
        delays = candidates / sample_rate_hz - event_time
        raw = np.exp(-delays / tau_d) - np.exp(-delays / tau_r)
        indices[index] = int(candidates[int(np.argmax(raw))])
    return indices


def _run_single_seed_waveform(seed: int) -> dict[str, Any]:
    t0 = time.time()
    print(f"[{time.strftime('%H:%M:%S')}] [Worker] Starting seed {seed}...", flush=True)
    cfg = load_config(Path("configs/demo_correlated.yaml"))
    res, _ = run_waveform_alpha_validation(
        cfg,
        duration_s=10.0,
        bootstrap_replicates=8,
        max_expected_events=100_000,
        max_waveform_samples=1_500_000_000,
        true_rate_cps=3000.0,
        alpha_s_inv=1000.0,
        sample_rate_hz=100_000_000.0,
        seed=seed,
    )
    elapsed = time.time() - t0
    print(f"[{time.strftime('%H:%M:%S')}] [Worker] Finished seed {seed} in {elapsed:.1f}s", flush=True)
    
    out = {
        "G0_event_time_reference": {
            "seed": seed,
            "n_events": res.reference.accepted_count,
            "rossi_alpha": res.reference.alpha_rossi_s_inv,
            "feynman_alpha": res.reference.alpha_feynman_s_inv,
            "psd_alpha": res.reference.alpha_psd_s_inv,
            "rossi_err": res.reference.alpha_rossi_rel_error,
            "feynman_err": res.reference.alpha_feynman_rel_error,
            "psd_err": res.reference.alpha_psd_rel_error,
        }
    }
    for cond in res.conditions:
        out[cond.name] = {
            "seed": seed,
            "n_events": cond.accepted_count,
            "rossi_alpha": cond.alpha_rossi_s_inv,
            "feynman_alpha": cond.alpha_feynman_s_inv,
            "psd_alpha": cond.alpha_psd_s_inv,
            "rossi_err": cond.alpha_rossi_rel_error,
            "feynman_err": cond.alpha_feynman_rel_error,
            "psd_err": cond.alpha_psd_rel_error,
        }
    return out


def run_table2_multiseed_parallel(seeds: list[int] = [42, 101, 202, 303, 404]) -> dict[str, Any]:
    print(f"=== Running Table 2 Multi-seed Waveform Validation ({len(seeds)} seeds in parallel) ===", flush=True)
    t_start = time.time()
    
    with ProcessPoolExecutor() as executor:
        seed_results = list(executor.map(_run_single_seed_waveform, seeds))
        
    cond_names = ["G0_event_time_reference", "G1_ideal_waveform", "G2_noisy_waveform", "G3_noisy_waveform_deadtime"]
    results: dict[str, list[dict[str, Any]]] = {cond: [] for cond in cond_names}
    
    for s_res in seed_results:
        for cond_name in cond_names:
            results[cond_name].append(s_res[cond_name])
            
    summary: dict[str, Any] = {}
    for cond_name, points in results.items():
        n_ev = [p["n_events"] for p in points]
        r_a = [p["rossi_alpha"] for p in points]
        f_a = [p["feynman_alpha"] for p in points]
        p_a = [p["psd_alpha"] for p in points]
        r_e = [p["rossi_err"] for p in points]
        f_e = [p["feynman_err"] for p in points]
        p_e = [p["psd_err"] for p in points]
        summary[cond_name] = {
            "mean_events": float(np.mean(n_ev)),
            "std_events": float(np.std(n_ev)),
            "rossi_mean": float(np.mean(r_a)),
            "rossi_std": float(np.std(r_a)),
            "rossi_mean_err": float(np.mean(r_e)),
            "rossi_std_err": float(np.std(r_e)),
            "feynman_mean": float(np.mean(f_a)),
            "feynman_std": float(np.std(f_a)),
            "feynman_mean_err": float(np.mean(f_e)),
            "feynman_std_err": float(np.std(f_e)),
            "psd_mean": float(np.mean(p_a)),
            "psd_std": float(np.std(p_a)),
            "psd_mean_err": float(np.mean(p_e)),
            "psd_std_err": float(np.std(p_e)),
            "points": points,
        }
    
    out_file = OUT_DIR / "table2_multiseed_summary.json"
    out_file.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved Table 2 summary to {out_file} (Total time: {time.time() - t_start:.1f}s)", flush=True)
    return summary


def run_high_rate_steady_state() -> dict[str, Any]:
    print("=== Running Steady-State High-Rate Diagnostic ===", flush=True)
    base_config = load_config(Path("configs/demo_correlated.yaml"))
    rates = [1.0e3, 5.0e3, 1.0e4, 5.0e4, 1.0e5, 1.0e6, 1.0e7]
    durations = [0.1, 0.1, 0.1, 0.05, 0.05, 0.01, 0.002]
    seeds = [2026082501, 2026082502, 2026082503]
    
    rows = []
    points = []
    
    for rate_cps, dur_s in zip(rates, durations):
        print(f"  Testing rate {rate_cps:.0e} cps (duration {dur_s} s)...", flush=True)
        rate_points = []
        for seed in seeds:
            raw = base_config.model_dump(mode="python")
            raw["metadata"]["seed"]["value"] = seed
            raw["simulation"]["true_rate_cps"]["value"] = rate_cps
            raw["source_model"]["alpha"]["value"] = 1000.0
            k_eff = float(raw["source_model"]["k_eff"]["value"])
            eff = float(raw["source_model"]["detection_efficiency"]["value"])
            source_rate_cps = rate_cps * (1.0 - k_eff) / eff
            for boundary_cps in (10.0, 1.0e7):
                if math.isclose(source_rate_cps, boundary_cps, rel_tol=1e-15, abs_tol=0.0):
                    source_rate_cps = boundary_cps
            raw["source_model"]["source_rate_cps"]["value"] = source_rate_cps
            
            raw["observation"]["mode"] = "fixed_duration"
            raw["observation"]["duration_s"]["value"] = dur_s
            raw["noise"]["enabled"] = False
            raw["dead_time"]["mode"] = "none"
            raw["dead_time"]["duration_s"]["value"] = 0.0
            
            config = He3SimConfig.model_validate(raw)
            sim = prepare_waveform_simulation(config, max_expected_events=100_000, max_waveform_samples=20_000_000)
            
            trigger = ThresholdTrigger(
                sample_rate_hz=sim.sample_rate_hz,
                polarity=int(_required_number(config.trigger.polarity.value, "polarity")),
                threshold_V=_required_number(config.trigger.threshold_V.value, "threshold"),
                hysteresis_V=_required_number(config.trigger.hysteresis_V.value, "hysteresis"),
                min_hold_s=_required_number(config.trigger.min_hold_s.value, "hold"),
            )
            trigger_state = None
            preclip_chunks = []
            clipped_chunks = []
            candidate_chunks = []
            saturation_count = 0
            sample_count = 0
            
            for block in iter_waveform_blocks(sim, config):
                preclip_chunks.append(block.preclip_analog_samples_V)
                clipped_chunks.append(block.analog_samples_V)
                if block.saturation_mask is not None:
                    saturation_count += int(np.count_nonzero(block.saturation_mask))
                sample_count += int(block.analog_samples_V.size)
                indices, trigger_state = trigger.process_block(
                    block.analog_samples_V,
                    block.sample_index_start,
                    trigger_state,
                )
                if indices.size:
                    candidate_chunks.append(indices)
                    
            preclip = np.concatenate(preclip_chunks).astype(np.float64, copy=False)
            clipped = np.concatenate(clipped_chunks).astype(np.float64, copy=False)
            candidates = (
                np.concatenate(candidate_chunks).astype(np.float64) / sim.sample_rate_hz
                if candidate_chunks
                else np.empty(0, dtype=np.float64)
            )
            events = sim.true_events.events
            baseline = (
                _required_number(config.baseline.offset_V.value, "baseline offset")
                if config.baseline.enabled
                else 0.0
            )
            signal_reference = preclip - baseline
            clipping_nrmse = _safe_nrmse(clipped - baseline, signal_reference)
            
            direct = render_direct_sparse_block(events, 0, min(5000, preclip.size), sim.sample_rate_hz)
            linear_nrmse = _safe_nrmse(signal_reference[:min(5000, preclip.size)], direct)
            
            peak_indices = _event_peak_indices(events, sim.sample_rate_hz)
            valid = peak_indices < preclip.size
            peak_indices = peak_indices[valid]
            valid_events = events[valid]
            ideal_peaks = valid_events["amplitude_peak_V"].astype(np.float64) * valid_events["polarity"].astype(np.float64)
            measured_peaks = preclip[peak_indices] - baseline
            peak_bias = np.abs((measured_peaks - ideal_peaks) / np.abs(ideal_peaks))
            p90_bias = float(np.quantile(peak_bias, 0.90)) if peak_bias.size else 0.0
            
            tau_d_s = _required_number(config.pulse_shape.tau_d_s.value, "tau_d")
            support_s = 5.0 * tau_d_s
            trig_eff, false_frac = _trigger_metrics(candidates, events, config)
            overlap_frac = _overlap_fraction(events["t_s"], support_s)
            sat_frac = saturation_count / sample_count if sample_count else 0.0
            
            pt = {
                "rate_cps": rate_cps,
                "duration_s": dur_s,
                "seed": seed,
                "true_events": len(events),
                "overlap_fraction": overlap_frac,
                "peak_bias_p90": p90_bias,
                "clipping_nrmse": clipping_nrmse,
                "linear_nrmse": linear_nrmse,
                "saturation_fraction": sat_frac,
                "trigger_candidates": len(candidates),
                "trigger_efficiency": trig_eff,
                "false_trigger_fraction": false_frac,
            }
            rate_points.append(pt)
            points.append(pt)
            
        med_overlap = float(np.median([p["overlap_fraction"] for p in rate_points]))
        med_p90 = float(np.median([p["peak_bias_p90"] for p in rate_points]))
        med_clip = float(np.median([p["clipping_nrmse"] for p in rate_points]))
        med_linear = float(np.median([p["linear_nrmse"] for p in rate_points]))
        med_sat = float(np.median([p["saturation_fraction"] for p in rate_points]))
        med_eff = float(np.median([p["trigger_efficiency"] for p in rate_points]))
        med_events = float(np.median([p["true_events"] for p in rate_points]))
        
        rows.append({
            "rate_cps": rate_cps,
            "duration_s": dur_s,
            "median_events": med_events,
            "median_overlap": med_overlap,
            "median_p90_bias": med_p90,
            "median_clipping_nrmse": med_clip,
            "median_linear_nrmse": med_linear,
            "median_saturation_fraction": med_sat,
            "median_trigger_efficiency": med_eff,
        })
        
    csv_file = OUT_DIR / "high_rate_steady_diagnostic.csv"
    with csv_file.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(points[0].keys()))
        writer.writeheader()
        writer.writerows(points)
        
    json_file = OUT_DIR / "high_rate_steady_summary.json"
    summary_data = {
        "rates": rates,
        "durations": durations,
        "seeds": seeds,
        "rows": rows,
        "points": points,
    }
    json_file.write_text(json.dumps(summary_data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved steady-state high-rate summary to {json_file}", flush=True)
    return summary_data


def main() -> None:
    run_table2_multiseed_parallel()
    run_high_rate_steady_state()
    print("All v2 experiment simulations completed successfully!", flush=True)


if __name__ == "__main__":
    main()
