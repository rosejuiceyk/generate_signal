# 相关中子事件生成、噪声分析与 He-3 波形建模：文献综述（初稿）

## 使用边界

本文献综述服务于“合成相关中子事件—He-3 波形生成—事件级 α 恢复”的方法学论文。它支持方法选择、模型假设和局限性讨论；不将合成验证表述为真实反应堆或真实探测器的标定。

## 一、方法脉络

Rossi-α 以事件对时间差/自相关函数中的指数衰减提取提示中子衰减常数；Feynman-α 则拟合不同计数门宽下的方差均值比。二者在单模态点堆近似下应给出同一基本 α 模态，但多模态、探测器死时间和门宽选择会造成差异。Cohn-α（PSD）是频域表述：噪声功率谱的洛伦兹型折点与 α 有关。三者都应被理解为同一随机分枝过程在时延、门计数和频谱域的互补投影。

对点堆、提示近似，反应性定义为 ρ=(k_eff-1)/k_eff 时，常用关系为 α≈-ρ/Λ；包含延迟中子效应的常见表达是 α=(β_eff-ρ)/Λ。本文软件中的 α=(1-k_eff)/Λ 是为合成事件生成器定义的纯提示、简化耦合关系，不应与含延迟中子的完整动力学公式混同。

He-3 比例计数器的波形生成需要至少区分：中子俘获的 p–t 产物沉积与壁效应、气体电离与电荷收集、前置放大/整形、电子噪声与基线、ADC、阈值触发和死时间。对本项目，波形模型的角色是研究“这些获取环节是否保持事件时间相关性”，而不是代替 Geant4/Garfield++ 的真实器件标定。

## 二、核心文献矩阵

| 类别 | 文献 | 与本文的用途 | 获取状态 |
|---|---|---|---|
| Feynman-α 原始理论 | R. P. Feynman, F. de Hoffmann, R. Serber, *Dispersion of the Neutron Emission in U-235 Fission*, J. Nucl. Energy 3 (1956), 64–69. | 方差均值比与单模态 Feynman-Y 的原始来源。 | 待通过馆藏/Scholar 获取原文。 |
| Rossi/Feynman 理论扩展 | *Determination of the Prompt Neutron Period from the Fluctuations of the Number of Neutrons in a Reactor*, J. Nucl. Energy 17 (1963), 395–409, DOI: 10.1016/0368-3230(63)90086-7. | 讨论延迟中子、Rossi 及 Feynman 方法适用条件。 | 出版商摘要可访问；全文待下载。 |
| Cohn-α 原始理论 | C. E. Cohn, *A Simplified Theory of Pile Noise*, Nucl. Sci. Eng. 7 (1960), 472–475, DOI: 10.13182/NSE60-4. | PSD/Cohn-α 的频域理论起点。 | 出版商页面可访问；全文可能需馆藏。 |
| Feynman-α 不确定度 | *Analytic Derivation of the Statistical Error in the Feynman-α Method*, Ann. Nucl. Energy 88 (2016), 186–193, DOI: 10.1016/j.anucene.2015.11.003. | 支撑门宽、统计误差及近临界误差解释。 | 出版商摘要可访问；全文待下载。 |
| 多 α 模态 | C. Berglöf et al., *Auto-correlation and variance-to-mean measurements in a subcritical core obeying multiple alpha-modes*, Ann. Nucl. Energy 38 (2011), 194–202, DOI: 10.1016/j.anucene.2010.11.009. | 解释单指数拟合的局限性及 Rossi/Feynman 差异。 | 出版商摘要可访问；全文待下载。 |
| Rossi-α 不确定度 | *Measurement uncertainty of Rossi-alpha neutron experiments*, Ann. Nucl. Energy 2021, DOI: 10.1016/j.anucene.2020.107765. | 支撑本项目 bootstrap、重复种子和不确定度报告。 | 出版商摘要与预印本线索可访问；全文待下载。 |
| 反射体影响 | *On the Feynman-alpha Method for Reflected Fissile Assemblies* (2020). | 两区/反射体模型可使单区模型产生约 10% 偏差；作为局限性来源。 | 公开 arXiv 可获取。 |
| PSD 数值敏感性 | *Sensitivity of power spectral density techniques to numerical parameters in analyzing neutron noise experiments*, Prog. Nucl. Energy (2017). | 支撑 PSD 的 bin 宽、Welch 参数和拟合频段敏感性分析。 | 出版商摘要可访问；全文待下载。 |
| α–反应性关系 | *Reactor Kinetics*, Springer chapter, DOI: 10.1007/978-981-16-0344-0_3. | 给出 α=(β_eff-ρ)/Λ 及参数定义。 | 章节页面可访问；全文依权限而定。 |
| 次临界测量 | *Subcriticality Measurements*, Springer chapter, DOI: 10.1007/978-981-97-8070-9_10. | 对 α 与提示负反应性关系及测量外推的权威综述。 | 章节页面可访问；全文依权限而定。 |
| He-3 波形/上升时间 | T. J. Langford et al., *Event Identification in He-3 Proportional Counters Using Risetime Discrimination*, NIM A 717 (2013), 51–57, DOI: 10.1016/j.nima.2013.03.062. | 直接证明上升时间、脉冲高度和微放电/α 本底会影响事件判选；应支撑触发模型。 | **公开 NIST PDF 可下载。** |
| He-3 响应蒙特卡洛 | *Design Parameters and Technology Optimization of 3He-filled Proportional Counters for Thermal Neutron Detection and Spectrometry Applications*, Radiat. Meas. 47 (2012), 577–587, DOI: 10.1016/j.radmeas.2012.06.002. | 涉及壁效应、电子附着与脉冲高度分布的 Monte Carlo 建模。 | 出版商摘要可访问；全文待下载。 |
| He-3 脉冲形状与 PSD | E. Rossi, *Characterisation of the Spatial Resolution and the Gamma-ray Discrimination of Helium-3 Proportional Counters* (2017), arXiv:1702.06501. | 给出能量分辨、γ 灵敏度和 He-3 PSD/Monte Carlo 的公开资料。 | **公开 arXiv PDF 可下载。** |
| 高压 He-3 PSD | *Improved pulse shape discrimination for high pressure 3He counters*, NIM A (2018). | 含 He-3 探测器 Monte Carlo 与实验波形比较，适合丰富波形建模章节。 | 出版商摘要可访问；全文待下载。 |

## 三、可写入论文的综述性结论

1. 事件级三个 α 估计器应作为互补方法报告，而非互相替代。Rossi-α 直接作用于事件时差；Feynman-α 受门宽和相邻门计数相关性影响；PSD/Cohn-α 受采样 bin、谱估计及频段拟合影响。
2. 本项目已观察到深次临界工况的不确定度升高，以及波形触发后 Feynman-α 对系统性时标扰动更敏感。这与多模态、死时间及统计误差相关文献指出的限制方向一致，但仍需避免声称对真实系统完成了外部验证。
3. α–k_eff 的软件耦合应在论文中明确为“固定 Λ 下的合成纯提示模型”。真实系统若有延迟中子、空间/能量模态、反射体或外源驱动，需要使用更完整的动力学关系。
4. He-3 波形模型的最低可辩护层级应包含物理脉冲形状、阈值和死时间；进一步提高可信度则应补入壁效应/电荷收集/整形电子学的参数化，且以公开实验波形或厂家/实验室标定数据约束。

## 四、建议的引用优先级

正文优先引用：Feynman et al.、Cohn、1963 prompt-period 论文、Berglöf et al.、Rossi-α 不确定度论文、Langford et al.、He-3 设计优化论文。方法局限性与展望中引用 PSD 数值敏感性、反射体 Feynman-α 与 Rossi 的 He-3 PSD 论文。

## 五、下载记录

本轮未自动下载 PDF。原因是 Chrome 插件控制通道未能建立，不能可靠地在 Google Scholar 中执行下载；未绕过出版商访问限制。可直接从公开来源优先下载的两项：Langford et al. 的 NIST PDF、Rossi 的 arXiv PDF。其余请在学校 VPN/馆藏或 Google Scholar 的“all versions”中下载并保存到 `references/papers/`。
