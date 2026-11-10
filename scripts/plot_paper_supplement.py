"""Render audited simulation evidence, with every seed visible, from saved JSON.

No data are generated, filtered, or fitted here. Synthetic data are the subject
of this software-validation study, not placeholders for experimental data.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np


def export(fig: plt.Figure, output: Path, name: str) -> None:
    """Export editable vectors and a high-resolution preview at a fixed size."""
    fig.savefig(output / f"{name}.svg")
    fig.savefig(output / f"{name}.pdf")
    fig.savefig(output / f"{name}.png", dpi=600)
    plt.close(fig)


def plot(output: Path) -> None:
    """Use raw seed points plus medians; paired effects retain seed identity."""
    result = json.loads((output / "paper_supplement_validation.json").read_text("utf-8"))
    destination = output / "figures"
    destination.mkdir(exist_ok=True)
    matplotlib.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": ["Arial", "DejaVu Sans"],
            "font.size": 8,
            "axes.titlesize": 9,
            "axes.labelsize": 8,
            "xtick.labelsize": 8,
            "ytick.labelsize": 8,
            "legend.fontsize": 7,
            "svg.fonttype": "none",
            "pdf.fonttype": 42,
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    )
    high = result["high_rate"]
    rates = np.array(high["protocol"]["rates_cps"])
    if not np.all(rates > 0):
        raise ValueError("Log rate axis requires positive rates")
    metrics = [
        ("overlap_fraction", "Overlapping events (%)", 10.0),
        ("peak_bias_p90_abs", "Peak bias P90 (%)", 10.0),
        ("clipping_nrmse", "Clipping NRMSE (%)", 1.0),
        ("saturation_fraction", "Saturated samples (%)", 0.1),
        ("trigger_efficiency", "Matched trigger efficiency (%)", 95.0),
        ("false_trigger_fraction", "Unmatched triggers (%)", 5.0),
    ]
    width_in = 183 / 25.4
    fig, axes = plt.subplots(3, 2, figsize=(width_in, 175 / 25.4), layout="constrained")
    for panel, (axis, (field, label, threshold)) in enumerate(zip(axes.flat, metrics, strict=True)):
        values = np.array(
            [[p[field] * 100 for p in high["points"] if p["true_rate_cps"] == r] for r in rates]
        )
        for i, _seed in enumerate(high["protocol"]["seeds"]):
            axis.scatter(
                rates,
                values[:, i],
                s=15,
                color="#0072B2",
                alpha=0.6,
                marker=("o", "s", "^")[i],
                label="Individual seeds" if i == 0 else None,
            )
        axis.plot(
            rates,
            np.median(values, axis=1),
            color="#0072B2",
            linewidth=1,
            label="Median (n = 3 seeds)",
        )
        axis.axhline(
            threshold, color="#555555", linestyle="--", linewidth=0.8, label="Frozen threshold"
        )
        axis.set(xscale="log", xlabel="Nominal asymptotic rate (cps)", ylabel=label)
        if field == "peak_bias_p90_abs":
            if np.any(values <= 0):
                raise ValueError("Peak-bias log axis requires positive measurements")
            axis.set_yscale("log")
        else:
            axis.set_ylim(bottom=-2 if field == "false_trigger_fraction" else -4)
        axis.set_title(f"{chr(97 + panel)}", loc="left", fontweight="bold")
        axis.grid(axis="y", alpha=0.15)
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="outside lower center", ncol=3, frameon=False)
    fig.suptitle("Synthetic source-on scan: no rate meets all six criteria", fontsize=10)
    export(fig, destination, "high_rate_seed_diagnostics")

    gate = result["feynman_gate"]
    fig = plt.figure(figsize=(width_in, 145 / 25.4), layout="constrained")
    grid = fig.add_gridspec(2, 2)
    dev_axis = fig.add_subplot(grid[0, :])
    pair_axis, effect_axis = fig.add_subplot(grid[1, 0]), fig.add_subplot(grid[1, 1])
    strategies = gate["protocol"]["candidate_alpha_t_ranges"]
    dev_labels = []
    for i, (name, low, high_gate) in enumerate(strategies):
        errors = np.array(
            [p["relative_error"] * 100 for p in gate["development_points"] if p["strategy"] == name]
        )
        color = "#D55E00" if name == gate["selected_strategy"] else "#737373"
        dev_axis.scatter(np.full(errors.size, i), errors, color=color, s=18, alpha=0.7)
        dev_axis.plot(i, np.median(errors), "D", color=color, markersize=6)
        suffix = (
            "\nBaseline" if i == 0 else ("\nSelected" if name == gate["selected_strategy"] else "")
        )
        dev_labels.append(f"{low:g}–{high_gate:g}{suffix}")
    dev_axis.set(
        xticks=np.arange(len(strategies)),
        xticklabels=dev_labels,
        xlabel="Frozen candidate range (αT)",
        ylabel="Absolute relative α error (%)",
    )
    dev_axis.set_title(
        "a  Development: four seeds; diamonds show medians", loc="left", fontweight="bold"
    )
    baseline_name = "baseline_20us_10ms"
    lookup = {(p["seed"], p["strategy"]): p["relative_error"] for p in gate["holdout_points"]}
    paired_differences = []
    for seed in gate["protocol"]["holdout_seeds"]:
        baseline_error = lookup[seed, baseline_name]
        selected_error = lookup[seed, gate["selected_strategy"]]
        pair_axis.plot(
            [0, 1],
            np.array([baseline_error, selected_error]) * 100,
            "o-",
            color="#737373",
            alpha=0.65,
            markersize=3,
            linewidth=0.8,
        )
        paired_differences.append(
            (baseline_error - selected_error) * gate["protocol"]["alpha_true_s_inv"]
        )
    pair_axis.axhline(5, color="#0072B2", linestyle="--", linewidth=0.8)
    pair_axis.set(
        xticks=[0, 1],
        xticklabels=["20 µs–10 ms\nBaseline", "0.2–8 ms\nFrozen"],
        ylabel="Absolute relative α error (%)",
    )
    pair_axis.set_title("b  Holdout: eight paired seeds", loc="left", fontweight="bold")
    ci = gate["paired_improvement_ci95_s_inv"]
    center = gate["paired_improvement_median_s_inv"]
    effect_axis.scatter(np.arange(1, 9), paired_differences, color="#737373", s=18)
    effect_axis.errorbar(
        [10],
        [center],
        yerr=[[center - ci[0]], [ci[1] - center]],
        fmt="D",
        color="#D55E00",
        capsize=4,
        markersize=5,
    )
    effect_axis.axhline(0, color="#555555", linestyle="--", linewidth=0.8)
    effect_axis.set(
        xticks=[1, 4, 8, 10],
        xticklabels=["1", "4", "8", "Median\n95% CI"],
        xlabel="Holdout seed index",
        ylabel="Error reduction (1/s)",
    )
    effect_axis.set_title("c  Positive values favour frozen gates", loc="left", fontweight="bold")
    for axis in (dev_axis, pair_axis, effect_axis):
        axis.grid(axis="y", alpha=0.15)
    fig.suptitle("Frozen gate selection does not establish holdout improvement", fontsize=10)
    export(fig, destination, "feynman_development_holdout")
    print(f"Rendered source-preserving figures: {destination}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("outputs/paper_supplement_validation"))
    plot(parser.parse_args().output)
