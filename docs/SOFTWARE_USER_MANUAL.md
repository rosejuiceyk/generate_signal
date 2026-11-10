
# He-3 连续脉冲信号模拟软件用户手册

## 1. 手册用途

本文档是软件功能、操作方法、物理原型、后端模块和数据格式的独立用户手册。
阶段人工审核步骤与审核记录另见 `docs/USER_MANUAL.md`。

当前软件用于：给定死时间之前的真实计数率、采样率、观察时间和随机种子，以非相关泊松过程或
纯瞬发分支过程生成可复现的 He-3 热中子探测器前置放大器连续合成波形，并输出 HDF5、CSV、PNG、
YAML 和 JSON。

当前参数尚未由真实探测器、前放、ADC 或示波器标定。输出适合算法开发、软件验证和合成数据研究，
不能直接作为某一台真实设备的定量预测。

## 2. 环境与活动工作流
项目统一使用 Python 3.11+ 的 `signal_create` Conda 环境：

```powershell
conda activate signal_create
python -m pip install -e ".[dev,ui]"
```

活动 CLI 只提供配置校验、事件/波形/数据集生成、HDF5 检查与绘图、物理验证，以及只读采集数据
资格审查。查看完整命令：

```powershell
he3sim --help
```

常用工作流：

```powershell
he3sim validate-config -c configs/demo_minimal.yaml
he3sim simulate-events -c configs/demo_minimal.yaml -o outputs/events.h5
he3sim simulate-events --source-model correlated -c configs/demo_minimal.yaml -o outputs/correlated_events.h5
he3sim validate-correlated -c configs/demo_minimal.yaml -o outputs/phaseA_report
he3sim analyze-noise -c configs/demo_minimal.yaml -o outputs/phaseB_noise
he3sim validate-alpha-recovery -c configs/demo_minimal.yaml -o outputs/phaseB_recovery
he3sim validate-event-precision-pilot -c configs/demo_correlated.yaml -o outputs/event_precision_pilot
he3sim validate-waveform-alpha -c configs/demo_correlated.yaml -o outputs/waveform_alpha_validation
he3sim analyze-continuous-noise -c configs/demo_correlated.yaml -o outputs/phaseC_continuous
he3sim scan-usability-frontier -c configs/demo_correlated.yaml -o outputs/phaseC_frontier
he3sim simulate-waveform -c configs/demo_minimal.yaml -o outputs/waveform.h5
he3sim plot-waveform outputs/waveform.h5 -o outputs/waveform.png
he3sim generate-dataset -c configs/demo_minimal.yaml -o outputs/dataset
he3sim validate-physics -c configs/demo_minimal.yaml -o outputs/physics_validation
he3sim qualify-acquisition --input <DAQ目录> --profile configs/acquisition_profiles/dt5790_run3.yaml -o outputs/phase04q
```

波形和数据集 HDF5 保存真值事件、分块索引、裁剪前/后的模拟电压、ADC 和饱和标记。Phase 3
数据集另外保存触发、死时间、事件关联和固定窗口。所有派生产物写入 `outputs/`，原始采集目录保持只读。

`validate-waveform-alpha` 是论文方法验证用的合成闭环：同一相关中子真值依次通过 G0 事件时间参考、
G1 理想波形、G2 含噪波形和 G3 含噪波形加 `4 us` 非延长型死时间，再以 Rossi-α、Feynman-α、PSD
反演 α。G0 与 G1–G3 严格共用 seed、真值事件、观察时长、α 真值和估计器设置；JSON 记录逐种子配对差异。
波形触发可选 `level` 或 `differential`；投稿前冻结评估使用平滑延迟差分触发
(`DifferentialThreshold`：`4 mV`、延迟 `0.5 us`、平滑 `0.2 us`)。

`outputs/manuscript_v6_differential_local/` 保存的五种子冻结结果是当前投稿前口径：60 项估计的绝对相对误差
均值为 `3.219%`，中位数为 `2.567%`，`48/60` 项不超过 `5%`。原先更严格的“每一种子、每一工况、每一估计器
均不超过 5%”门槛**未达成**（仅一个种子满足），必须作为限制保留，不能转写为自动通过或真实设备性能结论。
这些结果仅支持参数化纯模拟链路的描述性软件验证。

命令可用 `--true-rate-cps`、`--duration-s`、`--alpha-s-inv` 和 `--seed` 统一覆盖全部 G0–G3 工况；
冻结评估使用 `3000 cps`、`30 s`、`α=1000 s^-1`、`100 MHz` 和五个预定种子；网页展示用的 `2 MHz`
电压片段不是正式触发链路。正式波形仿真仍保留配置要求的 `100 MHz`。

### 2.1 本地交互界面

在项目根目录启动只监听本机的 Streamlit 界面：

```powershell
streamlit run src/he3sim/ui/app.py --server.address 127.0.0.1
```

界面包含事件生成、连续波形和脉冲模式噪声三个页面。连续信号噪声分析不再提供本地交互页面；
该研究功能的既有 CLI 与分析模块仍保留，供后续科研开发使用。参数采用单一数值输入框，
既可键入，也可用右侧加减按钮微调；同一参数不再同时出现滑块和输入框。每个计算页把最近一次成功结果
分别保存在当前浏览器会话中，切换页面不会清除已有指标和图表。刷新浏览器、关闭标签页或重启服务会
开始新会话，不应把会话状态当作长期存档。

界面不提供历史结果浏览页。长期结果继续保存在 `outputs/`，可通过文件管理器或对应的静态 HTML、PNG、
JSON 文件查看。参数真实性和会话保留说明不再作为计算结果区的重复页脚展示，但相关状态仍写入配置与
输出元数据。

### 2.2 Windows 11 免安装便携版

正式便携产物位于 `dist/He3Signal-Win11-x64.zip`。目标电脑不需要安装 Python、Conda 或项目依赖：

1. 把 ZIP 完整复制到 Windows 11 64 位电脑并解压；
2. 双击解压目录中的 `He3Signal.exe`；
3. 启动控制器在后台启动仅监听 `127.0.0.1` 的本地服务，并自动打开默认浏览器；
4. 控制器随后最小化到任务栏；恢复并关闭控制器或点击“退出软件”会同时停止后台服务；
5. 再次双击时若软件已经运行，只会重新打开现有页面，不会创建第二个服务。

`outputs/` 和 `logs/` 在 EXE 所在目录按需创建。复制或备份时应保留整个 `He3Signal` 文件夹，不能只复制
EXE 或删除 `_internal/`。当前构建未使用商业代码签名证书，因此首次运行可能触发 Windows SmartScreen
的“未知发布者”提示。发行包内的 `PORTABLE_README.txt` 提供同样的离线说明。

维护者可在项目根目录重新构建：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build_portable.ps1
```

构建脚本使用 `signal_create` 环境中的 PyInstaller，生成 onedir 文件夹并压缩为 Win11 x64 ZIP。打包清单
明确排除 PyTorch、TensorFlow、JAX 等当前界面不使用的可选框架。

## 3. 物理原型

### 3.1 齐次泊松事件到达

当前非相关热中子使用恒定真实到达率 `lambda_true` 的齐次泊松过程：

$$
N(T)\sim\operatorname{Poisson}(\lambda_{\mathrm{true}}T)
$$

相邻事件间隔：

$$
\Delta t_i\sim\operatorname{Exponential}(\lambda_{\mathrm{true}})
$$

软件保留两种精确算法：固定窗口主路径使用“泊松计数加排序均匀时刻”，交叉验证和流式扩展使用
“累积指数间隔”。随机数统一使用 `numpy.random.Generator` 和 `SeedSequence` 子流。

### 3.2 纯瞬发相关中子分支过程

相关模式使用一速点模型。外源到达仍由精确泊松采样器生成；每个中子经过参数为 `lambda_t` 的指数
寿命后发生裂变、俘获或探测：

$$
\lambda_t=\frac{\alpha}{1-k},\quad
\lambda_f=\frac{k\lambda_t}{\bar\nu},\quad
\lambda_d=\epsilon\lambda_t,\quad
\lambda_c=\lambda_t-\lambda_f-\lambda_d
$$

裂变时按 `nu_pmf` 抽取瞬发子代数并继续同一条链。长时间一阶探测率为：

$$
R_d=\frac{S\epsilon}{1-k}
$$

配置要求 `0<k<1`、`alpha>0`、`0<epsilon<1`、`nu_pmf` 非负且和为 1、PMF 均值与
`nu_bar` 一致，并要求 `lambda_c>=0`。`k_eff` 与反应性 `rho=(k-1)/k` 二选一。

`configs/demo_minimal.yaml` 默认仍为 `source_model.kind: poisson`，但包含完整、全部标记为
`synthetic_demo` 的相关参数预设，因此可用 `--source-model correlated` 审核事件 CLI。若要让波形和
数据集命令按相关模式运行，应在派生配置中把 `source_model.kind` 改为 `correlated`，并保持
`simulation.true_rate_cps = S*epsilon/(1-k)`。

本阶段采用“源开启窗口”：只从观察窗起点开始注入外源，不模拟窗前历史，因此开头存在约
`1/alpha` 的启动暂态。当前不包含延迟中子、空间/能量输运或近临界 Gillespie 算法。

Phase A 静态验证命令为：

```powershell
he3sim validate-correlated -c configs/demo_minimal.yaml -o outputs/phaseA_report
```

命令以固定 seed 计算所有统计量，然后调用 `analysis/figures.py` 的纯绘图函数。输出包括
`event_raster.png`、`interval_distribution.png`、`fano_vs_gate.png`、`mean_rate_vs_k.png`、
`chain_tree.png`、`degeneracy_limit.png`、离线 `phase_a_validation.html` 和
`phase_a_validation.json`。HTML 只引用同目录静态 PNG，不含 JavaScript 或交互仪表盘。

报告门禁为：配置点观察率相对差异不超过 3%，`k_eff` 扫描最大相对差异不超过 5%，最大相关
Fano 大于 1.05，近零倍增间隔 KS 距离不超过样本量相关容限。图上标注 `α`、`k_eff`、短间隔
差异、最大 Fano、最大率差异和 KS 距离；这些量均在验证层计算，绘图层不重复推导。

### 3.3 参数化 He-3 沉积能谱

物理原型来自：

$$
{}^3\mathrm{He}+n\rightarrow p+{}^3\mathrm{H}+764\ \mathrm{keV}
$$

能谱由 764 keV 全能峰、质子壁效应、氚壁效应和可选双壁效应组成。全能峰使用正值截断高斯，
壁效应使用有界 Beta 分布。混合权重非负且和为 1。这些是参数化演示分布，不是真实管体标定结果。

### 3.4 能量到峰值幅值

$$
A_{\mathrm{peak}}=G_EE_{\mathrm{dep}}+\epsilon_A
$$

`A_peak` 保存正的目标峰值幅度，脉冲正负由独立的 `polarity` 保存。当前增益、偏置和展宽参数均为
演示值。

### 3.5 峰值归一化双指数脉冲

令 `s=t-t_i`，当 `s>=0`：

$$
g(s)=e^{-s/\tau_d}-e^{-s/\tau_r},\qquad \tau_d>\tau_r>0
$$

$$
t_{\mathrm{peak}}=
\frac{\tau_r\tau_d}{\tau_d-\tau_r}
\ln\left(\frac{\tau_d}{\tau_r}\right)
$$

$$
v_i(t)=\mathrm{polarity}_i\,A_{\mathrm{peak},i}
\frac{g(t-t_i)}{g(t_{\mathrm{peak}})}
$$

离散实现按事件相对采样网格的分数相位校正峰值，使孤立脉冲在离散波形上的峰值保持为
配置的 `A_peak`。

### 3.6 连续波形和堆积

$$
v(t)=b(t)+n(t)+\sum_i v_i(t)
$$

所有真实事件都参与求和，因此高计数率自然产生堆积。`direct_sparse` 是逐事件参考实现；
`recursive_fixed_tau` 使用两个指数递推状态实现高效固定时间常数波形，并保持跨块尾部连续；
`auto` 自动选择后端。

### 3.7 基线、噪声、裁剪和 ADC

当前支持常量基线、高斯白噪声、可选 AR(1) 低频漂移、模拟电压裁剪、ADC 输入范围与位数量化，
以及每点饱和标记。处理顺序为：

```text
脉冲叠加 → 基线/噪声 → 保存裁剪前电压 → 模拟裁剪 → 保存裁剪后电压 → ADC
```

简单裁剪不是空间电荷、气体增益变化或真实前放饱和恢复模型。真实恢复行为必须等待示波器数据标定。

### 3.8 触发与死时间

Phase 3 数据集支持 `none`、`nonparalyzable` 和 `paralyzable`：

$$
m_{\mathrm{nonparalyzable}}=\frac{\lambda}{1+\lambda\tau_d}
$$

$$
m_{\mathrm{paralyzable}}=\lambda e^{-\lambda\tau_d}
$$

死时间只改变观测候选的接受状态，不能删除真值事件或它们的连续波形贡献。

## 4. 后端模块对应表

| 模块 | 职责 |
|---|---|
| `he3sim/config.py`、`random.py` | 配置、单位、参数状态、seed 和独立随机子流 |
| `physics/` | 泊松到达、纯瞬发分支链、源模型映射、He-3 能谱、幅值、脉冲参数和真值事件 |
| `synthesis/` | 连续波形、噪声、基线、裁剪、ADC 和多尺度数据集 |
| `acquisition/` | 触发、死时间和真值事件关联 |
| `analysis/` | 统计验证、脉冲特征、报告、噪声估计（连续与脉冲模式）和波形绘图 |
| `io/` | HDF5、MCNP、示波器、DT5800 stub 和数据集持久化 |
| `calibration/` | 只读采集探针、四态 QC、来源追溯和 Phase 4Q 门禁 |
| `he3sim/cli.py` | 活动命令入口，不导入归档 Web/ML 模块 |

## 5. 命令行功能

```powershell
he3sim validate-config -c configs/demo_minimal.yaml
he3sim simulate-events -c configs/demo_minimal.yaml -o outputs/events.h5
he3sim simulate-events --source-model correlated -c configs/demo_minimal.yaml -o outputs/correlated_events.h5
he3sim validate-correlated -c configs/demo_minimal.yaml -o outputs/phaseA_report
he3sim validate-arrivals -c configs/demo_minimal.yaml -o outputs/arrival_validation
he3sim simulate-waveform -c configs/demo_minimal.yaml -o outputs/waveform.h5
he3sim plot-waveform outputs/waveform.h5 -o outputs/waveform.png
he3sim generate-dataset -c configs/demo_minimal.yaml -o outputs/dataset
he3sim validate-physics -c configs/demo_minimal.yaml -o outputs/physics_validation
he3sim inspect outputs/waveform.h5
he3sim qualify-acquisition --input <DAQ目录> --profile configs/acquisition_profiles/dt5790_run3.yaml -o outputs/phase04q
```

## 6. 已归档路线

原 Phase 3.5 本地 Web、Phase 5 网络 A、Phase 6 网络 C 和 Phase 6S 合成预演已移入
`archive/`。相关依赖、配置、CLI 和活动测试均已移除；归档内容只用于审计，不能作为当前软件功能调用。
项目主线见 `docs/ROADMAP_v2.md`。

## 7. Phase 4Q 数据资格功能

Phase 4Q 命令只读扫描采集目录，并把派生清单写入 `outputs/phase04q/`。它逐文件计算 SHA-256，明确
保存 RAW/FILTERED/UNFILTERED 版本，对 RAW 事件逐行执行 QC，因此内存只随单条事件记录增长。

QC 状态为 `pass`、`fail`、`not_evaluable` 或 `unknown`。当前 profile 的阈值为 `provisional`；ADC
轨道未独立确认，因此 saturation 保持 `not_evaluable`。严格相邻重复样本只计算比例和候选去重长度，
不会改写样本。独立已知频率实验完成前：

- `sample_interval_s` 必须为 `null`；
- 波形只使用导出索引和 `ADC_counts`；
- `ENERGY` 只作为原始 channel；
- 软件粒子标签保持 `unknown/candidate`；
- 不允许拟合物理时间常数或生成标定 YAML。

默认每个 run 最多处理256条事件以便有界人工审查。`--max-events-per-run 0` 可执行完整流式普查，
但不会解除采样轴和独立 run 数量造成的科学阻塞。



## 8. 当前限制

- 到达层支持恒定率非相关泊松和源驱动纯瞬发一速点模型；不含延迟中子、全输运或近临界算法；
- 能谱、增益、时间常数、噪声、量程和 ADC 尚未真实标定；
- 没有空间电荷、气体增益随计数率变化、前放非线性恢复或真实饱和恢复；
- 不包含示波器导入、真实标定、MCNP 自动运行或硬件控制；
- 原 Phase 3.5 Web 后端与生成式 ML 路线已归档；当前只恢复本机 Streamlit 研究界面，不恢复远程服务，
  也不安装或调用归档 ML。
- Phase B CLI 报告仍为静态文件；本机界面仅用于调用现有分析并浏览会话结果，不含远程多用户仪表盘。
- Phase C 连续信号方法使用合成数字孪生；CCF/CTM 未经过 DT5800 或真实电子学验证。

## 9. 相关事件 HDF5 数据格式

`TRUE_EVENT_DTYPE` 保持不变。相关模式在 `events/true` 之外增加 `events/lineage`：

| 字段 | 类型 | 含义 |
|---|---|---|
| `event_id` | int64 | 与 `events/true/event_id` 一一对应 |
| `chain_id` | int64 | 产生该探测的外源裂变链编号 |
| `generation` | int32 | 源中子为第 0 代，裂变子代逐代递增 |

`pileup_group_id` 不存链编号，继续表示波形脉冲重叠分组。HDF5 元数据 `source_model` 记录选择，
`source_model_derived_json` 保存反应率、时间尺度、Diven 因子和一阶探测率等计算值。派生量没有独立
证据状态，其可信度继承输入参数。

完整数学合同见 `docs/model_spec.md`，项目范围与阶段门禁见 `docs/PROJECT_SPEC.md`。

## 10. 论文补充实验入口

独立脚本 `scripts/run_paper_supplement_validation.py` 编排
`analysis/paper_supplement_validation.py`，不修改现有 CLI 或界面。

```powershell
conda run -n signal_create python scripts/run_paper_supplement_validation.py --config configs/demo_correlated.yaml --output outputs/paper_supplement_validation
```

高率诊断保存裁剪前后及 ADC 对照指标；触发效率采用每个真值最多匹配一次的贪心关联，避免用原多对多
窗口关联数冒充逐事件分辨率。它仍是窗口匹配诊断，不是脉冲因果归属的独立证据。
门宽候选、开发/保留种子和通过门槛由实验协议固定，规范协议哈希与基础配置哈希写入结果。

输出目录现包含完整协议、JSON、CSV、快速预览、`figures/` 内逐种子 PNG/SVG/PDF，以及 `reproduction/`
内完整复现产物。两次完整执行的协议和数值文件逐字节一致；初次源强舍入中止历史保留于执行记录。

独立审核入口 `scripts/audit_paper_supplement.py` 从落盘逐种子结果重新计算选择规则、判据和配对区间，
核对全部 CSV 字段，并增加非空线性实现对照；它不重新挑门宽或改科学门槛。调用示例：

```powershell
conda run -n signal_create python scripts/audit_paper_supplement.py --reproduction outputs/paper_supplement_validation/reproduction
conda run -n signal_create python scripts/plot_paper_supplement.py
```

审核输出 `independent_audit.json`、`base_config_snapshot.json`、`provenance_manifest.json` 分别记录独立核查、
基础参数状态快照及活动源码/产物哈希。波形长数组不单独存档，可通过冻结配置与种子重建。
绘图脚本只读数值结果，不重新生成或筛选实验数据；推荐其全部种子图用于论文审核。

2026-08-26：全量测试 227 passed，独立核查 84 项通过。科学结论仍为：无全部判据达标率点、门宽改善未获支持。
源模型无稳态预热；触发读取模拟样本，ADC 仅做量化诊断；软件裁剪不是已标定的硬件非线性。
详见 `docs/PAPER_SUPPLEMENT_RESULTS.md`。当前为 `awaiting_human_review`，不代表作者验收通过。
