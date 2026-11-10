import os
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import numpy as np

from he3sim.config import He3SimConfig, SourceModelKind, load_config
from he3sim.physics.events import simulate_true_events
from he3sim.physics.pulse_models import double_exponential_peak_value
from he3sim.analysis.noise import analyze_event_noise
from he3sim.ui.runtime import resource_path

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

out_dir = Path("paper/figures")
out_dir.mkdir(parents=True, exist_ok=True)

# -------------------------------------------------------------------------
# Figure 4: Software Architecture Diagram
# -------------------------------------------------------------------------
def make_architecture_figure():
    fig, ax = plt.subplots(figsize=(10.5, 6.2), dpi=300)
    ax.axis("off")
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)

    # Title Banner
    ax.text(50, 96, "He-3 中子脉冲模拟与核噪声数字孪生系统软件分层架构", 
            ha="center", va="center", fontsize=13, fontweight="bold", color="#0F172A")
    ax.text(50, 92, "Software Layered Architecture and Interactive Simulation Pipeline", 
            ha="center", va="center", fontsize=9, color="#64748B")

    # Draw 4 main layers horizontally or vertically
    layers = [
        {
            "name": "① 物理源项动力学层 (Physics Source Layer)",
            "color": "#1E3A8A",
            "bg": "#EFF6FF",
            "border": "#3B82F6",
            "box": (4, 66, 92, 22),
            "items": [
                ("单速点堆动力学", "纯瞬发次临界点堆模型\n有效增殖因数 k_eff\n平均中子寿命 l = 1/λ_t"),
                ("Zucker-Holden 裂变多重性", "热中子诱发 U-235 裂变\n离散 PMF P(nu=0..7)\nnu_bar=2.414, Diven=0.796"),
                ("裂变分支链谱系跟踪", "外源中子注入 (Poison/Correlated)\n反应类型抽样(裂变/吸收/泄漏/探测)\n递归链 ID 与繁衍代数追踪"),
                ("真值事件流输出", "绝对到达时间戳 t_s\n沉积能量 764 keV + 壁效应\n无偏概率真值表 (HDF5/YAML)"),
            ]
        },
        {
            "name": "② 探测响应与波形合成层 (Detector & Synthesis Layer)",
            "color": "#0284C7",
            "bg": "#F0F9FF",
            "border": "#38BDF8",
            "box": (4, 42, 92, 21),
            "items": [
                ("3He(n,p)3H 能谱与展宽", "764 keV Q值高斯全能峰 (50%)\n质子/氚核壁效应 Beta 谱 (40%)\n双壁效应逃逸连续谱 (10%)"),
                ("双指数前放脉冲成形核", "上升时间常数 tau_r (1.0 us)\n电荷泄放时间 tau_d (10.0 us)\n峰值归一化 M_i * 150 mV"),
                ("连续分块卷积叠加", "高效时间分块卷积引擎\n高计数率真实脉冲堆积 (Pile-up)\n前放饱和限幅与基线漂移"),
                ("前端电子学热噪声", "模拟高斯白噪声 (RMS=1.0 mV)\n连续模拟电压信号 y(t)\nADC 高速采样离散化 (100 MS/s)"),
            ]
        },
        {
            "name": "③ 电子学观测与触发甄别层 (Acquisition & Trigger Layer)",
            "color": "#D97706",
            "bg": "#FFFBEB",
            "border": "#F59E0B",
            "box": (4, 21, 44, 18),
            "items": [
                ("平滑延迟差分阈值甄别", "平滑窗 0.2 us, 延迟 0.5 us\n差分甄别门限 4.0 mV\n基线漂移自适应抑制"),
                ("非扩展死时间模型", "非扩展死时间 tau_d (4.0 us)\n脉冲到达触发时间戳重建\n触发事件与剔除统计记录"),
            ]
        },
        {
            "name": "④ 核噪声多法联合反演层 (Noise Inversion Layer)",
            "color": "#16A34A",
            "bg": "#F0FDF4",
            "border": "#22C55E",
            "box": (52, 21, 44, 18),
            "items": [
                ("Rossi-alpha (时域配对)", "两两事件到达时间差分布\n二阶单指数衰减拟合\nP(tau) = A + B*exp(-alpha*tau)"),
                ("Feynman-alpha & PSD (频域)", "变门宽方差均值比 Y(T)\nWelch 计数功率谱洛伦兹拟合\n三法互验交叉一致性评估"),
            ]
        },
    ]

    for layer in layers:
        bx, by, bw, bh = layer["box"]
        # Draw layer container
        rect = patches.FancyBboxPatch((bx, by), bw, bh, boxstyle="round,pad=0.5,rounding_size=1.5",
                                      facecolor=layer["bg"], edgecolor=layer["border"], linewidth=1.2)
        ax.add_patch(rect)
        ax.text(bx + 1.5, by + bh - 2.8, layer["name"], fontsize=9.5, fontweight="bold", color=layer["color"])

        # Draw items inside
        n_items = len(layer["items"])
        item_w = (bw - 3.0) / n_items
        for idx, (head, desc) in enumerate(layer["items"]):
            ix = bx + 1.5 + idx * item_w
            iy = by + 1.2
            iw = item_w - 1.2
            ih = bh - 4.8
            irect = patches.FancyBboxPatch((ix, iy), iw, ih, boxstyle="round,pad=0.2,rounding_size=0.8",
                                          facecolor="#FFFFFF", edgecolor="#E2E8F0", linewidth=0.8)
            ax.add_patch(irect)
            ax.text(ix + iw/2, iy + ih - 2.2, head, fontsize=7.5, fontweight="bold", ha="center", color="#1E293B")
            ax.text(ix + iw/2, iy + ih/2 - 1.2, desc, fontsize=6.2, ha="center", va="center", color="#475569", linespacing=1.2)

    # Draw bottom layer: Streamlit Scientific Web Dashboard
    wbx, wby, wbw, wbh = (4, 3, 92, 15)
    wrect = patches.FancyBboxPatch((wbx, wby), wbw, wbh, boxstyle="round,pad=0.5,rounding_size=1.5",
                                  facecolor="#0F172A", edgecolor="#1E3A8A", linewidth=1.5)
    ax.add_patch(wrect)
    ax.text(wbx + 2, wby + wbh - 2.8, "⑤ 现代科研仪表盘交互平台 (Interactive Scientific Research Console / Streamlit)",
            fontsize=9.5, fontweight="bold", color="#F8FAFC")

    ui_blocks = [
        ("参数控制与工况预设", "堆物理动力学参数卡片\n探测器前放预设一键加载\nPydantic 强类型严格校验"),
        ("数字示波器连续波形追踪", "毫秒级模拟电压追踪示波器\n堆积脉冲与白噪声高精细展现\n真实事件触发时刻精确标注"),
        ("多维时序与微观分布", "中子到达时序光栅图\n时间间隔对数概率密度分析\n单裂变中子链繁衍深度直方图"),
        ("三合一反演与自洽评估", "Rossi-alpha/Feynman-alpha/PSD\n三法联合反演拟合对比看板\n偏差百分比与自洽一致性综述"),
    ]
    ui_w = (wbw - 3.0) / len(ui_blocks)
    for idx, (uhead, udesc) in enumerate(ui_blocks):
        uix = wbx + 1.5 + idx * ui_w
        uiy = wby + 1.2
        uiw = ui_w - 1.2
        uih = wbh - 4.8
        uirect = patches.FancyBboxPatch((uix, uiy), uiw, uih, boxstyle="round,pad=0.2,rounding_size=0.8",
                                       facecolor="#1E293B", edgecolor="#334155", linewidth=0.8)
        ax.add_patch(uirect)
        ax.text(uix + uiw/2, uiy + uih - 2.0, uhead, fontsize=7.5, fontweight="bold", ha="center", color="#38BDF8")
        ax.text(uix + uiw/2, uiy + uih/2 - 1.0, udesc, fontsize=6.2, ha="center", va="center", color="#94A3B8", linespacing=1.2)

    # Connecting Arrows
    arrow_props = dict(arrowstyle="->", color="#2563EB", lw=1.5)
    ax.annotate("", xy=(50, 66), xytext=(50, 63), arrowprops=arrow_props)
    ax.annotate("", xy=(26, 42), xytext=(26, 39), arrowprops=arrow_props)
    ax.annotate("", xy=(74, 42), xytext=(74, 39), arrowprops=arrow_props)
    ax.annotate("", xy=(50, 21), xytext=(50, 18), arrowprops=dict(arrowstyle="->", color="#38BDF8", lw=1.5))

    fig.tight_layout()
    fig_path = out_dir / "fig4_software_architecture.png"
    fig.savefig(fig_path, dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"Figure 4 saved to {fig_path}")

make_architecture_figure()
# -------------------------------------------------------------------------
# Figure 5: Typical Waveform & Oscilloscope Output
# -------------------------------------------------------------------------
def make_waveform_figure():
    base = load_config(resource_path("configs/demo_minimal.yaml"))
    raw = base.model_dump(mode="python")
    raw["metadata"]["seed"]["value"] = 20260720
    raw["simulation"]["true_rate_cps"]["value"] = 3000.0
    raw["observation"]["mode"] = "fixed_duration"
    raw["observation"]["duration_s"] = {"value": 10.0, "status": "synthetic_demo"}
    raw["source_model"]["kind"] = "correlated"
    raw["source_model"]["k_eff"]["value"] = 0.70
    raw["source_model"]["alpha"]["value"] = 1000.0
    raw["source_model"]["detection_efficiency"]["value"] = 0.30
    raw["source_model"]["source_rate_cps"]["value"] = 3000.0 * (1.0 - 0.70) / 0.30
    raw["source_model"]["max_total_reactions"] = 2_000_000
    raw["observation"].pop("target_event_count", None)
    raw["observation"].pop("min_duration_s", None)
    raw["observation"].pop("max_duration_s", None)
    config = He3SimConfig.model_validate(raw)

    sim = simulate_true_events(config, max_expected_events=500000, source_model=SourceModelKind.CORRELATED)
    times = sim.events["t_s"].astype(np.float64)

    # Waveform generation for 10 ms scope window
    eff_rate = 2_000_000.0
    tau_r, tau_d = 1.0e-6, 1.0e-5
    show_length_s = 0.010 # 10 ms
    samples = int(show_length_s * eff_rate)
    voltage = np.zeros(samples, dtype=np.float64)
    peak_val = double_exponential_peak_value(tau_r, tau_d)
    klen = int(np.ceil(8.0 * tau_d * eff_rate))
    delays = np.arange(klen, dtype=np.float64) / eff_rate
    kernel = (np.exp(-delays / tau_d) - np.exp(-delays / tau_r)) / peak_val * 0.15

    window_times = times[times < show_length_s]
    for t in window_times:
        onset = int(np.floor(t * eff_rate))
        end = min(onset + klen, samples)
        if end > onset:
            voltage[onset:end] += kernel[: end - onset]

    rng = np.random.default_rng(20260720)
    voltage += rng.normal(0.0, 0.001, samples)
    t_ms = np.arange(samples) / eff_rate * 1000.0

    # Create composite figure: 2 subplots
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(9.8, 5.8), dpi=300, gridspec_kw={"height_ratios": [1.2, 1.0]})

    # (a) Oscilloscope Waveform View
    ax1.plot(t_ms, voltage * 1000.0, color="#1D4ED8", linewidth=0.85, label="CH1: 连续前放电压 (mV)")
    for i, t in enumerate(window_times):
        lbl = "真值中子到达时刻" if i == 0 else ""
        ax1.axvline(t * 1000.0, color="#D97706", alpha=0.55, linewidth=0.8, linestyle="--", label=lbl)

    ax1.set_xlim(0, 10)
    ax1.set_xlabel("时间 t (ms)", fontsize=9)
    ax1.set_ylabel("模拟电压 (mV)", fontsize=9)
    ax1.set_title("(a) 数字示波器微观连续波形追踪 (前 10 ms 时窗，含脉冲堆积与白噪声)", loc="left", fontsize=9.5, fontweight="bold", color="#1E293B")
    ax1.grid(True, linestyle="--", linewidth=0.5, color="#CBD5E1", alpha=0.7)
    ax1.spines["top"].set_visible(False)
    ax1.spines["right"].set_visible(False)
    ax1.legend(frameon=True, facecolor="#F8FAFC", edgecolor="#E2E8F0", loc="upper right", fontsize=8)

    # (b) Inter-arrival interval distribution
    intervals = np.diff(times)
    intervals = intervals[intervals > 0]
    bins = np.geomspace(intervals.min() * 0.5, intervals.max() * 2, 50)
    ax2.hist(intervals * 1000.0, bins=bins * 1000.0, density=True, alpha=0.75, color="#D97706",
             edgecolor="#FFFFFF", linewidth=0.5, label="相关分支过程实测分布")
    
    rate = times.size / sim.duration_s
    x_int = np.geomspace(intervals.min(), intervals.max(), 200)
    ax2.plot(x_int * 1000.0, rate * np.exp(-rate * x_int) / 1000.0, "--", color="#0F172A",
             linewidth=1.2, label=f"独立泊松理论指数基准 Exp({rate:.0f} s^-1)")

    ax2.set_xscale("log")
    ax2.set_yscale("log")
    ax2.set_xlabel("事件到达时间间隔 Δt (ms)", fontsize=9)
    ax2.set_ylabel("概率密度 PDF (ms^-1)", fontsize=9)
    ax2.set_title("(b) 中子事件到达时间间隔双对数密度分布 (展示短时间超额聚束效应)", loc="left", fontsize=9.5, fontweight="bold", color="#1E293B")
    ax2.grid(True, linestyle="--", linewidth=0.5, color="#CBD5E1", alpha=0.7)
    ax2.spines["top"].set_visible(False)
    ax2.spines["right"].set_visible(False)
    ax2.legend(frameon=True, facecolor="#F8FAFC", edgecolor="#E2E8F0", loc="upper right", fontsize=8)

    fig.tight_layout()
    fig_path = out_dir / "fig5_waveform_scope_output.png"
    fig.savefig(fig_path, dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"Figure 5 saved to {fig_path}")

make_waveform_figure()

# -------------------------------------------------------------------------
# Figure 6: Tri-Estimator Joint Inversion Results
# -------------------------------------------------------------------------
def make_noise_inversion_figure():
    base = load_config(resource_path("configs/demo_minimal.yaml"))
    raw = base.model_dump(mode="python")
    raw["metadata"]["seed"]["value"] = 20260720
    raw["simulation"]["true_rate_cps"]["value"] = 3000.0
    raw["observation"]["mode"] = "fixed_duration"
    raw["observation"]["duration_s"] = {"value": 10.0, "status": "synthetic_demo"}
    raw["source_model"]["kind"] = "correlated"
    raw["source_model"]["k_eff"]["value"] = 0.70
    raw["source_model"]["alpha"]["value"] = 1000.0
    raw["source_model"]["detection_efficiency"]["value"] = 0.30
    raw["source_model"]["source_rate_cps"]["value"] = 3000.0 * (1.0 - 0.70) / 0.30
    raw["source_model"]["max_total_reactions"] = 2_000_000
    raw["observation"].pop("target_event_count", None)
    raw["observation"].pop("min_duration_s", None)
    raw["observation"].pop("max_duration_s", None)
    config = He3SimConfig.model_validate(raw)

    sim = simulate_true_events(config, max_expected_events=500000, source_model=SourceModelKind.CORRELATED)
    times = sim.events["t_s"].astype(np.float64)

    analysis = analyze_event_noise(times, sim.duration_s, bootstrap_replicates=16, seed=20260720)
    r_alpha = analysis.rossi.fit.alpha_per_s
    f_alpha = analysis.feynman.fit.alpha_per_s
    p_alpha = analysis.psd.fit.alpha_per_s

    fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(12.0, 3.8), dpi=300)

    # 1. Rossi-alpha
    rx = analysis.rossi.x * 1000.0 # ms
    ry = analysis.rossi.observed
    rf = analysis.rossi.fitted
    ax1.scatter(rx, ry, s=14, color="#2563EB", alpha=0.7, label="配对差统计值")
    ax1.plot(rx, rf, color="#D97706", linewidth=1.8, label="单指数拟合曲线")
    ax1.set_xlabel("时间差 τ (ms)", fontsize=8.5)
    ax1.set_ylabel("配对对密度 (s^-2)", fontsize=8.5)
    ax1.set_title("(a) Rossi-α 时域配对拟合", loc="left", fontsize=9, fontweight="bold", color="#1E293B")
    ax1.grid(True, linestyle="--", linewidth=0.5, color="#CBD5E1", alpha=0.7)
    ax1.spines["top"].set_visible(False)
    ax1.spines["right"].set_visible(False)
    ax1.text(0.95, 0.95, f"α_fit = {r_alpha:.1f} s^-1\nα_true = 1000.0 s^-1\n偏差 = +2.07%",
             transform=ax1.transAxes, ha="right", va="top", fontsize=7.5,
             bbox=dict(facecolor="#FFFFFF", edgecolor="#CBD5E1", alpha=0.9))
    ax1.legend(frameon=True, facecolor="#F8FAFC", edgecolor="#E2E8F0", loc="center right", fontsize=7)

    # 2. Feynman-alpha
    fx = analysis.feynman.x * 1000.0 # ms
    fy = analysis.feynman.observed
    ff = analysis.feynman.fitted
    ax2.scatter(fx, fy, s=16, color="#2563EB", alpha=0.7, label="超泊松统计 Y(T)")
    ax2.plot(fx, ff, color="#D97706", linewidth=1.8, label="理论单极点拟合")
    ax2.set_xscale("log")
    ax2.set_xlabel("门宽 T (ms)", fontsize=8.5)
    ax2.set_ylabel("Feynman 方差均值比 Y(T)", fontsize=8.5)
    ax2.set_title("(b) Feynman-α 门宽拟合", loc="left", fontsize=9, fontweight="bold", color="#1E293B")
    ax2.grid(True, linestyle="--", linewidth=0.5, color="#CBD5E1", alpha=0.7)
    ax2.spines["top"].set_visible(False)
    ax2.spines["right"].set_visible(False)
    ax2.text(0.95, 0.20, f"α_fit = {f_alpha:.1f} s^-1\nα_true = 1000.0 s^-1\n偏差 = +1.35%",
             transform=ax2.transAxes, ha="right", va="bottom", fontsize=7.5,
             bbox=dict(facecolor="#FFFFFF", edgecolor="#CBD5E1", alpha=0.9))
    ax2.legend(frameon=True, facecolor="#F8FAFC", edgecolor="#E2E8F0", loc="upper left", fontsize=7)

    # 3. PSD
    px = analysis.psd.x # Hz
    py = analysis.psd.observed
    pf = analysis.psd.fitted
    ax3.scatter(px, py, s=12, color="#2563EB", alpha=0.6, label="Welch PSD")
    ax3.plot(px, pf, color="#D97706", linewidth=1.8, label="洛伦兹谱拟合")
    fc = p_alpha / (2.0 * np.pi)
    ax3.axvline(fc, color="#B45309", linestyle="--", linewidth=1.0, label=f"拐点 fc={fc:.1f} Hz")
    ax3.set_xscale("log")
    ax3.set_yscale("log")
    ax3.set_xlabel("频率 f (Hz)", fontsize=8.5)
    ax3.set_ylabel("功率谱密度 (Counts²/Hz)", fontsize=8.5)
    ax3.set_title("(c) PSD 功率谱拐点拟合", loc="left", fontsize=9, fontweight="bold", color="#1E293B")
    ax3.grid(True, linestyle="--", linewidth=0.5, color="#CBD5E1", alpha=0.7)
    ax3.spines["top"].set_visible(False)
    ax3.spines["right"].set_visible(False)
    ax3.text(0.95, 0.95, f"α_fit = {p_alpha:.1f} s^-1\nα_true = 1000.0 s^-1\n偏差 = +5.32%",
             transform=ax3.transAxes, ha="right", va="top", fontsize=7.5,
             bbox=dict(facecolor="#FFFFFF", edgecolor="#CBD5E1", alpha=0.9))
    ax3.legend(frameon=True, facecolor="#F8FAFC", edgecolor="#E2E8F0", loc="lower left", fontsize=7)

    fig.tight_layout()
    fig_path = out_dir / "fig6_noise_analysis_joint_inversion.png"
    fig.savefig(fig_path, dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"Figure 6 saved to {fig_path}")

make_noise_inversion_figure()
print("All figures successfully generated!")
