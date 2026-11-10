# Zotero 自动化文献阅读流程（探测器信号模拟）

## 当前可行性与已执行检查

- 检查日期：2026-08-20。
- Zotero Desktop：10.0；本地 API v3 与 Connector 均已连通。
- 集合：`探测器信号模拟`，Zotero collection key：`YYD2LUYQ`。
- 集合对象：77 个；其中顶层题录 31 条、PDF 附件 41 个、HTML 附件 3 个。
- 全文索引：41 个 PDF 中 40 个可由 Zotero 本地 API 返回全文文本；1 个 PDF（attachment key `V6ZL89H3`）尚未建立可用全文索引。
- 已用原文验证的样本：`核中子探测器信号负指数时域响应模拟`、`3He 正比计数管集成核电子学器件研制与测试`、`辐射场中 NaI(Tl)探测器输出信号全过程模拟`。

结论：可以在不下载、不移动、不修改 Zotero 条目或附件的前提下，执行“题录筛选—全文读取—阅读卡片—文献矩阵”的自动化流程。

## 自动化流程

| 步骤 | 自动动作 | 产物 / 人工边界 |
|---|---|---|
| 1. 连接检查 | 查询 Zotero API、集合与本地全文索引 | 记录 API 状态、集合 key、附件数量；不读取或导出附件路径 |
| 2. 题录筛选 | 读取题名、作者、年份、条目类型、摘要与标签 | 将文献分为“直接方法、相邻技术、理论佐证、待排除” |
| 3. 附件映射 | 建立 Zotero 顶层条目与 PDF attachment key 对应关系 | 标出孤立 PDF、网页快照及缺失元数据条目 |
| 4. 全文预检 | 通过本地 API 检查每个 PDF 是否已有全文索引及文本长度 | 不复制全文；未索引项进入人工 OCR / 重建索引队列 |
| 5. 批量阅读 | 对直接方法层全文提取摘要、方法、验证对象、输出变量、局限性与可引用结论 | 形成逐篇阅读卡片；结论须回链到 Zotero item/attachment key |
| 6. 文献矩阵 | 汇总“模型链路、随机过程、电子学、采样、验证、适用性、局限性”字段 | 供论文综述与方法章节使用；不自动把相邻探测器结论外推为 He-3 标定 |
| 7. 引用交付 | 由 Zotero 生成 BibTeX / APA 题录，并在写作稿中插入 citation key | 题录格式自动化；引用语义仍需人工最终确认 |

## 已建立的优先阅读队列

| 层级 | Zotero 顶层条目 / 附件 key | 文献 | 阅读目的 |
|---|---|---|---|
| A | `FYIS26H9` | 核中子探测器信号负指数时域响应模拟 | 提取指数衰减、幅度/时间常数随机化和 Monte Carlo 信号生成依据 |
| A | `Q3TZ86F6` | 3He 正比计数管集成核电子学器件研制与测试 | 提取 He-3 读出链路、放大/成形/甄别与高斯脉冲输出依据 |
| A | `D63ERKYA` | 辐射场中 NaI(Tl)探测器输出信号全过程模拟 | 提取“粒子沉积—光学传输—光电转换—电路输出”的端到端分层建模路线 |
| A | `9MR9QGZB` | 基于 FPGA 的 SDD 探测器随机信号模拟发生器 | 提取可配置随机脉冲发生器实现思路 |
| A | `VNVS5QRM` | 多电极高纯锗探测器信号读出模拟研究 | 提取读出模型与多电极信号建模要素 |
| A | `PKDVBZE8` | Design and implementation of a virtual nuclear pulse signal generator | 提取虚拟核脉冲发生器的功能边界和验证方法 |
| A | `Z5M659VQ` | Design of a Random Simulated Nuclear Pulse Signal Generator | 提取随机脉冲序列与参数可调策略 |
| A | `MAUZL8F6` | Development and application of a Monte Carlo virtual detector—A novel nuclear pulse signal generator | 提取 Monte Carlo 虚拟探测器路线 |
| A | `J2QPU3GC` | Software emulator of nuclear pulse generation with different pulse shapes and pile-up | 提取脉冲形状、堆积与软件模拟实现 |
| A | `RBPSIRNB` | End-to-End Geant4 Waveform Modeling and Geometry Selection of EJ-276/SiPM Detectors for Neutron-Gamma Discrimination | 提取端到端波形、几何与 PSD 验证流程 |
| A | `GFVN9SG9` | Synthesis of pulses from particle detectors with a Generative Adversarial Network (GAN) | 仅作为数据驱动脉冲合成的相邻路线比较，不进入物理核心依据 |
| A | `RLVJ9SS6` | Waveform simulation for scintillation characteristics of NaI(Tl) crystal | 提取闪烁波形时间结构与合成逻辑 |
| A | `4GK4GH2T` | Digitalization of inverting filter shaping circuit for nuclear pulse signals | 提取数字成形环节与模拟波形接口 |
| A | `K3MRREB6` | Signal Simulation and Test of Cadmium Zinc Telluride Nuclear Radiation Detector | 提取半导体探测器信号仿真与实验核对设计 |

## 可重复执行的只读命令

以下命令只读取 Zotero 本地 API；不导入、删除或改写 Zotero 文库。Windows 环境中使用已验证的 Python 运行时：

```powershell
& 'C:\Program Files\LibreOffice\program\python.exe' `
  'C:\Users\rosejuice\.codex\plugins\cache\openai-curated-remote\zotero\0.1.2\skills\zotero\scripts\zotero.py' `
  status --json
```

```powershell
& 'C:\Program Files\LibreOffice\program\python.exe' `
  'C:\Users\rosejuice\.codex\plugins\cache\openai-curated-remote\zotero\0.1.2\skills\zotero\scripts\zotero.py' `
  fulltext FYIS26H9
```

## 当前限制

- Zotero 中有 16 个孤立 PDF，尚未与顶层题录关联；流程仍可读取全文，但 APA 题录需人工补全或在 Zotero 中关联。
- `V6ZL89H3` 没有可用全文索引，不能自动深读；建议在 Zotero 右键“重新建立索引”或确认该 PDF 可搜索。
- 自动阅读只提取和归纳论文原文，不等同于人工逐页复核。正式论文中的关键物理论断、公式和实验数值仍应在原 PDF 页面上人工核验。
- 本项目参数依然属于 `synthetic_demo` / `provisional` 范围；相邻探测器文献只能支撑建模路线，不得表述为 He-3 实物标定。

## 已完成的第一批全文阅读卡片

以下结论均来自 Zotero 全文索引的原文提取，而非仅由题名推断；每条保留 attachment key 以便回到 Zotero 核对。

| attachment key | 原文提取的技术内容 | 对本项目的可用边界 |
|---|---|---|
| `FYIS26H9` | 以峰值和衰减常数的概率分布驱动 Monte Carlo，生成负指数时域响应；文中还讨论高斯滤波、导数寻峰和拉普拉斯变换。 | 可支撑“幅度与衰减时间常数可随机化”的波形合成思路；其测井对象和单指数近似不能直接替代 He-3 前放标定。 |
| `Q3TZ86F6` | 3He 读出模块集成电荷灵敏前放、滤波成形、幅度甄别和高/低压电源，可输出高斯模拟脉冲及 TTL 脉冲；原文以中子源测试。 | 是 He-3 电子学链路的直接工程依据，可用于说明前放—成形—甄别层的建模边界。 |
| `D63ERKYA` | 建立 NaI(Tl) 的 MCNP 能量沉积、Birks 光转换、光子输运、PMT 与处理电路的端到端模型，并与 137Cs 实验作脉冲时域对比。 | 是“物理沉积—光/电转换—电子学输出”分层建模的强参考；仅可借鉴框架，不能将其数值参数迁移至 He-3。 |
| `9MR9QGZB` | FPGA 使用随机数产生与伯努利试验，将均匀随机数变换为指数分布的到达间隔；报告脉冲间隔、计数率和电压范围测试。 | 直接支持以指数到达间隔与可控随机脉冲序列驱动读出测试；其 SDD 电压和速率数值不用于本项目。 |
| `PKDVBZE8` | 虚拟核脉冲发生器面向标定、维护、算法验证和教学，明确要求保留真实核脉冲的幅度分布、时间随机性及幅度随机性。 | 可支撑软件发生器的用途与功能边界，不可据此证明合成波形等同于真实 He-3 波形。 |
| `Z5M659VQ` | FPGA+C# 方案生成多类仿核脉冲，包含标准高斯波形、随机数、特征谱脉冲和脉宽转换，并以核素特征谱进行仪器测试。 | 可用于讨论可配置脉冲库与软硬件协同发生器；本项目若只做软件原型，不应声称实现了相同硬件输出。 |
| `MAUZL8F6` | Monte Carlo virtual detector 以能量对应幅度、相邻到达间隔服从指数分布为基本验证对象，并用于多道脉冲幅度分析器测试。 | 与“事件层生成—波形/仪器测试”路线高度相关，可作为事件统计和脉冲幅度一致性验证的旁证。 |
| `J2QPU3GC` | 可编程脉冲发生器按给定脉冲数、形状和幅度，以采样点形式模拟闪烁探测器信号，并覆盖 pile-up 情形。 | 直接支持连续波形叠加与堆积不可忽略的设计原则；探测器对象不同，参数需独立定义。 |
| `RBPSIRNB` | Geant4 光学输运结合物理信号形成模型，预测前放电压波形，并以波形相关系数、nRMSE、峰值、定时和积分对实验验证。 | 为后续从“统计 α 恢复”扩展到“波形相似性指标”的验证设计提供高价值参考；当前项目尚无对应实测标定。 |
| `GFVN9SG9` | GAN 以实测闪烁体脉冲训练，生成可保持波形形状及脉冲高度分布的合成脉冲。 | 仅作为数据驱动合成的比较与局限性文献；项目物理核心不采用机器学习生成事件或波形。 |

## 下一轮自动执行内容

对上述 A 层余下条目继续提取“方法—输入随机量—输出波形量—验证指标—局限性”，随后生成可直接服务论文第二章的文献矩阵；Zotero 中的引用、附件和标签保持只读。
