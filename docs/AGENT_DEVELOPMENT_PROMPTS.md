# Agent 协同开发工程提示词与任务指令集 (Prompt Specification)

> **文档用途**：本文件专为与 AI 编码智能体（如 Antigravity / Codex 等）协同开发设计。每个任务均具备明确的代码上下文、技术规范、输入输出定义与自动化验收命令，开发者可按阶段将对应提示词直接下发给智能体执行。

---

## 目录
- [通用开发规范与工程约束](#通用开发规范与工程约束)
- [Task 1.1：MCNP 输入卡参数化与样本批处理采集器](#task-11mcnp-输入卡参数化与样本批处理采集器)
- [Task 1.2：堆芯物理参数极速 ML 代理模型构建与导出](#task-12堆芯物理参数极速-ml-代理模型构建与导出)
- [Task 1.3：堆芯数字孪生可视化交互界面 (Streamlit)](#task-13堆芯数字孪生可视化交互界面-streamlit)
- [Task 2.1：堆芯测点通量至探测器信号内核转换桥](#task-21堆芯测点通量至探测器信号内核转换桥)
- [Task 2.2：DT5800 AWG 14-bit 格式化波形导出器](#task-22dt5800-awg-14-bit-格式化波形导出器)
- [Task 3.1：CAEN DT5800 底层通信驱动与设备诊断工具](#task-31caen-dt5800-底层通信驱动与设备诊断工具)
- [Task 3.2：DT5800 AWG 波形内存推送与播放控制器](#task-32dt5800-awg-波形内存推送与播放控制器)
- [Task 4.1：硬件在环闭环数据回采与反演验证流水线](#task-41硬件在环闭环数据回采与反演验证流水线)

---

## 通用开发规范与工程约束
1. **代码风格与环境**：Python 3.10+，严格遵守 PEP 8，使用类型注解（Type Hints），所有模块必须通过 `ruff check` 与 `mypy`；
2. **真值隔离原则**：物理模型计算得出的真实物理量（Ground Truth）必须完整保留在数据结构元数据中，不得因仪器量化、触发或死时间修改真实值；
3. **接口解耦**：所有与外部硬件（如 DT5800、示波器）的交互必须包含**模拟桩（Mock / Stub / Fixture）**，确保在未连接实体硬件的开发环境中，单测与 CI 可以全绿通过；
4. **单元测试要求**：新增模块必须在 `tests/unit/` 中配备对应的单元测试，断言明确，容差合理。

---

## Task 1.1：MCNP 输入卡参数化与样本批处理采集器

### 【目标】
基于现有 `MCNP_input/YBS-0.84329.i` 模型，开发参数化解析与自动批处理脚本，支持修改安全棒高度、调节棒高度以及指定网格组件填充类型，并自动提取输出文件中的物理参数。

### 【执行指令 Prompt】
```text
请执行任务 Task 1.1：开发 MCNP 参数化操作与批处理脚本。

1. 目标文件：创建 `src/he3sim/core/mcnp_parser.py` 与 `scripts/run_mcnp_sampling.py`。
2. 业务需求：
   - 读取并解析 `MCNP_input/YBS-0.84329.i`；
   - 实现函数 `modify_mcnp_state(template_path: str, safety_rod_frac: float, reg_rod_frac: float, assembly_overrides: dict) -> str`：
     * 调节棒/安全棒位置：根据分数 [0.0, 1.0] 参数化更新控制棒表面的轴向截止平面坐标；
     * 组件插拔：根据 `(row, col): universe_id` 字典更新 Lattice 20 卡片中的对应 universe 单元；
   - 实现函数 `parse_mcnp_output(output_path: str) -> dict`：
     * 从 MCNP 文本输出提取最终估算的 `k_eff` 及其标准差 `k_eff_sd`；
     * 从 F4:N (Cell 1501) 和 F14:N (Cell 1503) 提取通量计数与相对误差；
   - 编写多进程批处理采集脚本，支持网格采样生成包含 500 组工况的 HDF5 数据集 `outputs/mcnp_samples.h5`。
3. 测试要求：
   - 在 `tests/unit/test_mcnp_parser.py` 编写测试，使用合成 MCNP 输出文本片段，验证解析逻辑完全准确。
4. 运行验证命令：
   pytest tests/unit/test_mcnp_parser.py -v
```

---

## Task 1.2：堆芯物理参数极速 ML 代理模型构建与导出

### 【目标】
基于 MCNP 采样数据集，训练轻量级机器学习代理模型（XGBoost 或 MLP），实现输入控制棒高度与组件状态，微秒级（$<1	ext{ ms}$）输出 $k_{	ext{eff}}$、$eta_{	ext{eff}}$、$\Lambda$ 以及测点 F4、F14 通量。

### 【执行指令 Prompt】
```text
请执行任务 Task 1.2：构建堆芯物理参数轻量级 ML 代理模型。

1. 目标文件：创建 `src/he3sim/core/surrogate_model.py` 与 `scripts/train_surrogate.py`。
2. 业务需求：
   - 支持从 HDF5 数据集加载特征（安全棒高度, 调节棒高度, 组件离散编码向量）和目标值 (k_eff, flux_1501, flux_1503)；
   - 训练多目标回归模型（优先采用 XGBoost/LightGBM 或紧凑型 PyTorch MLP）；
   - 实现推理类 `CoreSurrogatePredictor`：
     * 方法 `predict(safety_rod: float, reg_rod: float, components: np.ndarray) -> CorePhysicsPrediction`；
     * 派生计算总反应性 $ho = (k_{	ext{eff}} - 1) / k_{	ext{eff}}$ 以及瞬发衰减常数 $lpha = (eta_{	ext{eff}} - ho) / \Lambda$；
   - 模型序列化保存至 `models/core_surrogate.joblib` 或 `.onnx`，要求单次推理耗时严格控制在 1 ms 以内。
3. 测试要求：
   - 编写 `tests/unit/test_surrogate.py`：测试加载模型并在测试集上验证 $k_{	ext{eff}}$ 相对误差小于 0.05%，通量相对误差小于 2.0%，且单次推理时间小于 2 ms。
4. 运行验证命令：
   pytest tests/unit/test_surrogate.py -v
```

---

## Task 1.3：堆芯数字孪生可视化交互界面 (Streamlit)

### 【目标】
在 Streamlit 中搭建高交互性的反应堆堆芯数字孪生操作台，支持可视化调整组件与棒位，即时渲染物理参数与测点通量。

### 【执行指令 Prompt】
```text
请执行任务 Task 1.3：开发堆芯数字孪生可视化交互界面。

1. 目标文件：在 `src/he3sim/ui/pages/00_reactor_core.py`（或更新 `src/he3sim/ui/app.py`）。
2. 业务需求：
   - 渲染 YBS 堆芯二维网格俯视图，用颜色区分燃料棒、铍棒、B4C 吸收棒与石墨反射层；
   - 侧边栏/主面板控制组件：
     * 安全棒：提供滑块与“一键紧急停堆 (Scram)”红色按钮；
     * 调节棒：提供 0~100% 连续行程滑块；
     * 组件插拔模式：点击网格单元可切换燃料棒/空道/占位铝棒；
   - 调用 `CoreSurrogatePredictor` 极速计算物理状态，实时渲染指标卡片：
     * $k_{	ext{eff}}$、反应性 $ho$ (pcm / $)、瞬发衰减常数 $lpha$ (1/s)；
   - 用 Plotly 渲染测点 1501 与 1503 处的中子通量动态柱状图，直观展现调节棒动作引发的空间通量阴影效应（Flux Tilt）。
3. 交互性能要求：
   - 滑块拖动过程必须流畅无卡顿，单次界面重绘时间小于 100 ms。
4. 运行验证命令：
   streamlit run src/he3sim/ui/app.py
```

---

## Task 2.1：堆芯测点通量至探测器信号内核转换桥

### 【目标】
在 UI 上增加“打入外源/开堆”状态机控制，将代理模型输出的测点通量转化为探测器到达率，并无缝驱动已有的 `he3sim.physics.chains` 分支模型。

### 【执行指令 Prompt】
```text
请执行任务 Task 2.1：开发堆芯测点通量至探测器微观事件流的映射桥。

1. 目标文件：创建 `src/he3sim/physics/core_signal_bridge.py`。
2. 业务需求：
   - 定义反应堆运行状态机枚举 `CoreRunState`：`SHUTDOWN`（停堆/仅极弱环境本底）、`SOURCE_INJECTED`（打入中子源/启动中）、`CRITICAL_OPERATION`（稳态运行）；
   - 实现类 `CoreToDetectorBridge`：
     * 方法 `flux_to_arrival_rate(flux: float, detector_type: str = "He3_standard") -> float`：利用探测器灵敏体积与宏观吸收截面将空间通量转换为宏观中子到达率 $\lambda_{	ext{true}}$ (cps)；
     * 方法 `generate_event_stream(core_state: CorePhysicsPrediction, duration_s: float, seed: int) -> Tuple[EventTimes, EventTimes]`：分别针对测点 1501 与 1503，调用现有的 `BranchingProcessGenerator`，传入 $(\lambda, lpha, k_{	ext{eff}})$，生成包含分支链谱系的相关中子俘获事件序列。
3. 测试要求：
   - 编写 `tests/unit/test_core_signal_bridge.py`：测试在未打入外源时计数率接近零；打入外源后，计数率与通量成线性正比，且事件时间序列满足预期的超额方差（Fano 因子 > 1）。
4. 运行验证命令：
   pytest tests/unit/test_core_signal_bridge.py -v
```

---

## Task 2.2：DT5800 AWG 14-bit 格式化波形导出器

### 【目标】
将 `he3sim` 合成的微秒级连续模拟电压序列，转换并导出为 CAEN DT5800 AWG 模式要求的标准 14-bit DAC 整数格式数据文件。

### 【执行指令 Prompt】
```text
请执行任务 Task 2.2：实现 DT5800 AWG 14-bit 格式化波形导出模块。

1. 目标文件：创建 `src/he3sim/io/dt5800_awg_export.py`。
2. 业务需求：
   - 根据 CAEN DT5800 官方规格，AWG 模式采用 14-bit DAC，输入量程支持 $\pm 2	ext{ V}$（对应 $50\ \Omega$）或 $\pm 4	ext{ V}$（高阻）；
   - 实现量化转换函数 `quantize_waveform_to_dt5800_dac(voltage_array: np.ndarray, v_range: float = 2.0) -> np.ndarray`：
     * 将浮点电压裁剪在 $[-v_{	ext{range}}, +v_{	ext{range}}]$ 范围内；
     * 线性量化为 14-bit 有符号整数 $[-8192, +8191]$（或无符号 $[0, 16383]$，配置可切换）；
   - 实现文件导出类 `DT5800AWGExporter`：
     * 支持导出为 16-bit 小端二进制格式 `.raw`（高效内存写入）；
     * 支持导出为包含采样率头信息的 ASCII 文本格式 `.txt`（供 CAEN 官方控制台软件直接加载导入）；
     * 具备回读自检函数 `roundtrip_verify()`，验证反量化回来的电压波形与原始浮点波形 RMS 相对误差小于 $0.1\%$。
3. 测试要求：
   - 编写 `tests/unit/test_dt5800_awg_export.py`：使用合成双指数脉冲波形，测试满量程截断、零偏置、以及二进制/文本格式回读一致性。
4. 运行验证命令：
   pytest tests/unit/test_dt5800_awg_export.py -v
```

---

## Task 3.1：CAEN DT5800 底层通信驱动与设备诊断工具

### 【目标】
基于 Python `ctypes` 封装 CAEN 官方 SDK 接口，实现 USB 自动枚举、握手连接与设备诊断，且在无物理设备时自动回退至合成 Mock 驱动。

### 【执行指令 Prompt】
```text
请执行任务 Task 3.1：封装 CAEN DT5800 通信驱动与 Mock 适配层。

1. 目标文件：创建 `src/he3sim/hil/dt5800_driver.py` 与 `scripts/diagnose_dt5800.py`。
2. 业务需求：
   - 依据 CAENComm / CAEN_DT5800_SDK C/C++ 头文件接口，使用 Python `ctypes` 声明核心 API（打开设备、关闭句柄、写寄存器、读寄存器、写波形 RAM）；
   - 实现驱动类 `DT5800Device`：
     * 方法 `connect(port: str = "AUTO") -> bool`；
     * 方法 `get_firmware_version() -> str`；
     * 方法 `configure_channel(channel: int, mode: str, dac_range: float)`；
   - **关键要求（Mock 机制）**：若在测试环境中未找到硬件 DLL 或 USB 设备未插入，自动回退到 `MockDT5800Device`，将发送的数据完整记录在虚拟内存与日志中，保证在任何无设备机器上均能通过单测与 CI。
3. 测试要求：
   - 编写 `tests/unit/test_dt5800_driver.py`：测试 Mock 模式下的握手、配置修改、寄存器读写与内存写入状态断言。
4. 运行验证命令：
   pytest tests/unit/test_dt5800_driver.py -v
```

---

## Task 3.2：DT5800 AWG 波形内存推送与播放控制器

### 【目标】
实现上位机波形向 DT5800 板载 RAM 的块推流与播放控制，支持分段循环播放与状态切换。

### 【执行指令 Prompt】
```text
请执行任务 Task 3.2：实现 DT5800 AWG 波形推流与播放控制器。

1. 目标文件：创建 `src/he3sim/hil/awg_streamer.py`。
2. 业务需求：
   - 实现类 `DT5800AWGStreamer`：
     * 接收经过 `DT5800AWGExporter` 格式化的 14-bit DAC 整数数组（最大 $1	ext{ MSamples}$）；
     * 调用驱动接口，将波形写入指定通道（Channel 1: Det-1, Channel 2: Det-2）的 RAM 地址；
     * 设置触发模式：支持 `SOFTWARE_TRIGGER`、`EXTERNAL_TRIGGER` 与 `CONTINUOUS_LOOP`；
     * 启动/停止播放控制：`start_playback()`, `stop_playback()`；
   - 实现“工况平滑切换”机制：当上位机堆芯状态改变并生成新波形块时，在当前循环周期末尾无闪烁换写下一帧波形。
3. 测试要求：
   - 编写 `tests/unit/test_awg_streamer.py`：验证数据块大小校验、多通道独立推流逻辑与播放状态机转换正确。
4. 运行验证命令：
   pytest tests/unit/test_awg_streamer.py -v
```

---

## Task 4.1：硬件在环闭环数据回采与反演验证流水线

### 【目标】
搭建完整的闭环验证脚本，将示波器/数字化仪采集到的 DT5800 模拟波形读入，运行 `he3sim.analysis` 算法反演 $lpha$ 与反应性，并生成误差比对报告。

### 【执行指令 Prompt】
```text
请执行任务 Task 4.1：实现硬件在环闭环数据回采与反演验证流水线。

1. 目标文件：创建 `src/he3sim/analysis/hil_closed_loop_eval.py`。
2. 业务需求：
   - 读取示波器或数字化仪采集的 CSV / HDF5 波形数据；
   - 运行差分触发与死时间流水线，重构观测事件序列；
   - 执行已有的三大噪声反演算法：
     * Rossi-$lpha$ 拟合指数衰减斜率；
     * Feynman-$lpha$ 方差-均值比拟合；
     * PSD 频域交点分析；
   - 自动读取第一模块堆芯数字孪生的真值设定 $(lpha_{	ext{true}}, ho_{	ext{true}})$，计算反演相对误差；
   - 自动生成结构化评估报告 Markdown/HTML，输出对比表格与拟合曲线图。
3. 验收指标：
   - 在合成基准数据与回采数据上，反演所得 $lpha$ 相对误差严格控制在 $5\%$ 以内。
4. 运行验证命令：
   pytest tests/unit/test_hil_closed_loop_eval.py -v
```
