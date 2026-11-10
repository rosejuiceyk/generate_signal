import os
import sys
from pathlib import Path
import docx
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import qn, nsdecls

doc_path = Path(r"C:\Users\rosejuice\Desktop\论文\论文_排版后.docx")
fig_dir = Path(r"C:\Users\rosejuice\Desktop\he-3-signal\code_doc\paper\figures")

doc = docx.Document(str(doc_path))

# Locate Chapter 2 and Chapter 3
h2_idx = None
for i, p in enumerate(doc.paragraphs):
    if p.text.strip().startswith("2  软件架构"):
        h2_idx = i
        break

if h2_idx is None:
    raise ValueError("Could not find '2  软件架构' heading!")

h3_idx = None
for i in range(h2_idx + 1, len(doc.paragraphs)):
    if doc.paragraphs[i].text.strip().startswith("3 波形合成评估"):
        h3_idx = i
        break

if h3_idx is None:
    raise ValueError("Could not find '3 波形合成评估' heading!")

print(f"Chapter 2 at {h2_idx}, Chapter 3 at {h3_idx}")

p_end = doc.paragraphs[h3_idx]

# Helper to format run
def format_run(run, font_name="Microsoft YaHei", size_pt=10.5, bold=False, color=None):
    run.font.name = font_name
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.first_child_found_in("w:rFonts")
    if rFonts is None:
        rFonts = OxmlElement("w:rFonts")
        rPr.append(rFonts)
    rFonts.set(qn("w:ascii"), font_name)
    rFonts.set(qn("w:hAnsi"), font_name)
    rFonts.set(qn("w:eastAsia"), font_name)
    if size_pt:
        run.font.size = Pt(size_pt)
    if bold:
        run.bold = True
    if color:
        run.font.color.rgb = color

def add_heading2(text):
    p = p_end.insert_paragraph_before("", style="Heading 2")
    r = p.add_run(text)
    format_run(r, font_name="Microsoft YaHei", size_pt=12, bold=True)
    return p

def add_body(text):
    p = p_end.insert_paragraph_before("", style="Normal")
    r = p.add_run(text)
    format_run(r, font_name="Microsoft YaHei", size_pt=10.5)
    return p

def add_image(img_name, width_in=6.0):
    img_path = fig_dir / img_name
    if not img_path.is_file():
        raise FileNotFoundError(f"Image not found: {img_path}")
    p = p_end.insert_paragraph_before("", style="Normal")
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run()
    r.add_picture(str(img_path), width=Inches(width_in))
    return p

def add_caption(label_zh, title_zh, label_en, title_en):
    p_zh = p_end.insert_paragraph_before("", style="Caption")
    p_zh.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_zh.paragraph_format.space_after = Pt(0)
    p_zh.paragraph_format.line_spacing = 1.0
    r1 = p_zh.add_run(label_zh + "  ")
    format_run(r1, size_pt=9, bold=True)
    r2 = p_zh.add_run(title_zh)
    format_run(r2, size_pt=9, bold=False)

    p_en = p_end.insert_paragraph_before("", style="Caption")
    p_en.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_en.paragraph_format.space_after = Pt(4)
    p_en.paragraph_format.line_spacing = 1.0
    r3 = p_en.add_run(label_en + "  ")
    format_run(r3, size_pt=9, bold=True)
    r4 = p_en.add_run(title_en)
    format_run(r4, size_pt=9, bold=False)

def format_three_line_table(table):
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    for r_idx, row in enumerate(table.rows):
        is_header = (r_idx == 0)
        is_last = (r_idx == len(table.rows) - 1)
        for cell in row.cells:
            tcPr = cell._element.get_or_add_tcPr()
            top_xml = 'w:top w:val="none"'
            bottom_xml = 'w:bottom w:val="none"'
            if is_header:
                top_xml = 'w:top w:val="single" w:sz="12" w:space="0" w:color="000000"'
                bottom_xml = 'w:bottom w:val="single" w:sz="6" w:space="0" w:color="000000"'
            elif is_last:
                bottom_xml = 'w:bottom w:val="single" w:sz="12" w:space="0" w:color="000000"'
            
            border_xml = f'''
            <w:tcBorders {nsdecls("w")}>
                <{top_xml}/>
                <w:left w:val="none"/>
                <{bottom_xml}/>
                <w:right w:val="none"/>
            </w:tcBorders>
            '''
            tcPr.append(parse_xml(border_xml))

# Delete old outline paragraphs
old_paragraphs = [doc.paragraphs[k] for k in range(h2_idx + 1, h3_idx)]
print(f"Removing {len(old_paragraphs)} old outline paragraphs...")
for op in old_paragraphs:
    op._element.getparent().remove(op._element)

# Add 2.1
add_heading2("2.1  软件分层架构与交互仿真平台设计")

add_body(
    "为确保核物理瞬发分支过程抽样的严谨性、脉冲成形卷积的高保真度以及核噪声反演验证的可复现性，"
    "本文设计并实现了基于分层解耦思想的 ³He 脉冲信号全链路数字孪生软件系统。系统总体架构如图 4 所示，"
    "自底向上划分为物理源项动力学层、探测响应与波形合成层、电子学观测与触发甄别层、核噪声多法联合反演层以及交互式科研仪表盘展示层。"
)

add_body(
    "各功能层职责明确、接口隔离，且数据链路严格遵循单向可追溯原则：\n"
    "（1）物理源项动力学层（he3sim.physics）：以次临界点堆动力学方程为基础，基于 Zucker & Holden U-235 "
    "热中子诱发裂变瞬发多重性离散分布（ν̄=2.414097，Diven 因子 0.796051）开展蒙特卡洛分支过程抽样。"
    "系统递归追踪外源中子注入后的每一条裂变链谱系结构（包括中子寿命、反应类型、链 ID 与繁衍代数），"
    "生成包含精确绝对到达时间戳 t_s 与能量沉积信息的无偏真值事件表。"
    "底层配置由 Pydantic 强类型模型严格校验，并同元数据计算哈希指纹，保证前向物理事件生成完全独立且不受后续电子学甄别的影响。\n"
    "（2）探测响应与波形合成层（he3sim.synthesis）：根据 ³He(n,p)³H 反应的 764 keV 能谱展宽与壁效应 Beta 分布计算脉冲幅度，"
    "并以双指数电荷积分与泄放核函数（式 4，τ_r=1.0 μs，τ_d=10.0 μs）进行峰值归一化卷积。"
    "合成引擎采用高效时间分块叠加算法，在连续时间轴上精准重现高计数率下的脉冲堆积（Pile-up）物理现象，"
    "并混入宽带高斯白噪声与基线扰动，输出连续模拟前放电压波形 y(t)。\n"
    "（3）电子学观测与触发甄别层（he3sim.acquisition）：模拟高速数字采集卡（ADC）的高频采样过程，"
    "利用平滑延迟差分阈值甄别算法（延迟 0.5 μs，平滑窗 0.2 μs，甄别阈值 4 mV）提取脉冲过阈时间戳，"
    "有效克服了基线缓漂与直流偏置对触发时刻的影响；甄别后施加非扩展死时间模型（典型值 4.0 μs），"
    "生成包含接受/拒绝标记、峰值电压与积分电荷的观测事件集。\n"
    "（4）核噪声多法联合反演层（he3sim.analysis）：针对同一批事件序列，同时调用 Rossi-α、Feynman-α 与功率谱密度（PSD，Cohn-α）"
    "三套独立的经典时频域反演算法，提取瞬发中子衰减常数 α 的反演值，并通过非参数 Bootstrap 重抽样评估反演不确定度。\n"
    "（5）交互式科研仪表盘展示层（he3sim.ui）：为提高物理建模与波形调试效率，研发了基于 Streamlit 的现代化本地科研仪表盘系统。"
    "平台采用深邃科研蓝与核物理特征橙的高对比设计体系，通过卡片式容器对物理源动力学、前放响应核、示波器采集等模块进行结构化参数配置，"
    "提供典型实验工况一键预设；同时开发了数字示波器级连续电压实时波形追踪界面、微观到达时序与对数间隔概率密度分析工具，"
    "以及三合一核噪声拟合反演综合看板，实现了“参数配置—波形仿真—多法反演—自洽评估”的全链路闭环验证。"
)

add_image("fig4_software_architecture.png", width_in=6.2)
add_caption(
    "图4", "软件系统总体分层架构与交互式 Web 仿真流水线",
    "Fig. 4", "Overall layered software architecture and interactive Web simulation pipeline"
)

# Add 2.2
add_heading2("2.2  波形输出以及噪声分析")

add_body(
    "为直观展现软件系统的波形输出能力与核噪声反演精度，选取一组典型次临界反应堆物理测量工况进行仿真与全链路测试。典型输入参数设置如下：\n"
    "（1）堆物理源动力学参数：有效增殖因子 k_eff = 0.70（次临界度 β - ρ = 0.30），设定瞬发中子衰减常数真值 α = 1000.0 s⁻¹，"
    "系统宏观探测效率 ε = 0.30，外源强根据式（2）匹配为设定目标计数率；\n"
    "（2）观测与前放成形参数：目标计数率 R = 3000 cps，连续观测时长 T = 10.0 s，随机种子 Seed = 20260720；"
    "前放脉冲上升时间常数 τ_r = 1.0 μs，电荷泄放时间常数 τ_d = 10.0 μs，脉冲归一化峰值幅值 150 mV，前放叠加等效热噪声 RMS = 1.0 mV；\n"
    "（3）数字示波器采集参数：ADC 等效采样率 100 MS/s，示波器微观观测时窗 10.0 ms，平滑差分触发阈值 4.0 mV，非扩展死时间 4.0 μs。"
)

add_body(
    "2.2.1 连续前放模拟电压输出与微观时序特征\n"
    "在上述典型工况下，物理源项层在 10.0 s 仿真时间内共生成 29,521 个真值中子反应事件，实测统计计数率为 2952.1 cps。"
    "软件数字示波器模块对连续模拟前放电压输出及微观到达时序的追踪结果如图 5 所示。"
)

add_image("fig5_waveform_scope_output.png", width_in=6.0)
add_caption(
    "图5", "典型工况下连续前放模拟电压示波跟踪与中子到达时序分布",
    "Fig. 5", "Analog preamplifier voltage oscilloscope trace and neutron arrival timing distribution under typical conditions"
)

add_body(
    "由图 5(a) 的数字示波器连续波形可见，模拟前放电压信号表现出清晰的双指数脉冲形态，单脉冲在 1.0 μs 内迅速上升至约 150 mV 峰值，"
    "并沿 10.0 μs 的特征衰减时间缓慢泄放；在多中子密集到达的时间区间（如 2.5–4.5 ms），由于前一脉冲尚未完全衰减至基线，"
    "后续脉冲叠加在其拖尾之上，软件高保真地再现了真实前放输出端的脉冲堆积（Pile-up）物理现象；"
    "橙色虚线对应底层无偏真值中子的实际到达时刻，清晰揭示了微伏级高斯白噪声与堆积电平对差分触发甄别精度的影响。\n"
    "图 5(b) 给出了全部中子事件到达时间间隔 Δt 的双对数概率密度统计分布，并与相同计数率下的独立泊松指数衰减理论基准 Exp(2952 s⁻¹) 进行了对比。"
    "在长间隔区域（Δt > 1.0 ms），由于外源驱动在宏观时间尺度上近似随机，事件间隔严格服从泊松分布；"
    "而在短时间间隔区域（Δt < 1.0 ms ≈ 1/α），由于单裂变事件诱发的多代瞬发中子在极短时间内连续产生，"
    "概率密度显著高出泊松理论直线，呈现出明显的超额聚束（Bunching）特征，直接在微观时序层面上印证了次临界核裂变分支过程的时间相关特性。"
)

add_body(
    "2.2.2 核噪声多法联合反演与一致性分析\n"
    "基于生成的 29,521 个脉冲到达事件序列，调用软件内核集成的 Rossi-α、Feynman-α 与功率谱密度（PSD）"
    "三套算法进行瞬发中子衰减常数 α 的反演拟合，各方法的拟合谱图如图 6 所示，拟合参数与反演结果对比见表 1。"
)

add_image("fig6_noise_analysis_joint_inversion.png", width_in=6.2)
add_caption(
    "图6", "典型工况下 Rossi-α、Feynman-α 与 PSD 三合一联合反演拟合谱图",
    "Fig. 6", "Joint inversion fitting spectra of Rossi-alpha, Feynman-alpha, and PSD under typical conditions"
)

# Table 1 Caption
p_tbl_zh = p_end.insert_paragraph_before("", style="Normal")
p_tbl_zh.alignment = WD_ALIGN_PARAGRAPH.CENTER
p_tbl_zh.paragraph_format.space_after = Pt(2)
r_t1 = p_tbl_zh.add_run("表1  典型输入工况下三种核噪声方法 α 反演结果对比")
format_run(r_t1, size_pt=9.5, bold=True)

p_tbl_en = p_end.insert_paragraph_before("", style="Caption")
p_tbl_en.alignment = WD_ALIGN_PARAGRAPH.CENTER
p_tbl_en.paragraph_format.space_after = Pt(4)
r_t2 = p_tbl_en.add_run("Table 1  Comparison of alpha inversion results across three neutron noise methods under typical conditions")
format_run(r_t2, size_pt=9, bold=False)

# Table 1 Construction
tbl_data = [
    ["反演方法", "统计物理域", "设定真值 α / s⁻¹", "反演估计值 α̂ / s⁻¹", "相对误差", "关键拟合参数"],
    ["Rossi-α", "时域配对相关", "1000.0", "1020.68", "+2.07%", "A=8.64×10⁵ s⁻², B=8.71×10⁶ s⁻²"],
    ["Feynman-α", "时间门积分涨落", "1000.0", "1013.49", "+1.35%", "Y_∞=0.312"],
    ["PSD (Cohn-α)", "频域功率谱密度", "1000.0", "1053.19", "+5.32%", "f_c=167.6 Hz"],
]

table = doc.add_table(rows=len(tbl_data), cols=len(tbl_data[0]))
p_end._element.addprevious(table._element)
format_three_line_table(table)

for r_idx, row in enumerate(tbl_data):
    for c_idx, val in enumerate(row):
        cell = table.cell(r_idx, c_idx)
        cell.text = val
        cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
        if cell.paragraphs[0].runs:
            format_run(cell.paragraphs[0].runs[0], size_pt=9, bold=(r_idx == 0), font_name="Microsoft YaHei")

add_body(
    "由图 6 与表 1 的反演结果可以看出：\n"
    "（1）Rossi-α 时域配对拟合（图 6a）：时间差分布由短时域内的纯单指数相关项与长时域的平坦偶然符合平台复合而成，"
    "拟合得到瞬发中子衰减常数 α̂_Rossi = 1020.68 s⁻¹，相对设定真值（1000.0 s⁻¹）的相对误差为 +2.07%，相关项振幅 A = 8.64×10⁵ s⁻²；\n"
    "（2）Feynman-α 方差均值比拟合（图 6b）：随着积分门宽 T 从 0.1 ms 增加至 100 ms，中子计数超泊松方差均值比 Y(T) "
    "呈现出经典单极点动力学响应的上升并渐进饱和至 Y_∞ ≈ 0.312，通过非线性最小二乘拟合获得 α̂_Feynman = 1013.49 s⁻¹，相对真值误差仅为 +1.35%；\n"
    "（3）PSD 功率谱密度洛伦兹拟合（图 6c）：采用 Welch 分段平均周期图法估计计数序列的自功率谱，在双对数坐标下清晰展现出低频白噪声平台向高频 f⁻² 滚降的单极点洛伦兹特征，"
    "拟合得到的拐点频率为 f_c = 167.6 Hz，反演得到 α̂_PSD = 1053.19 s⁻¹，相对设定真值的偏差为 +5.32%；\n"
    "（4）综合自洽性评估：三种建立在截然不同统计物理原理（时域两两配对差、时间门积分统计涨落、频域周期图谱）之上的反演算法，"
    "对同一段连续合成波形序列均给出了优异的拟合优度，平均反演值为 1029.12 s⁻¹，总体平均偏差仅为 +2.91%，各方法相对真值的偏差均严格处于允许的工程验证区间内。"
    "该典型输出成果充分证明了本文构建的软件系统在物理源项模拟、探测器脉冲卷积成形、电子学波形追踪以及核噪声逆向反演全链路上具备高度的物理自洽性与算法可靠性，"
    "为后续开展多工况、多随机种子的大规模冻结合成评估奠定了坚实的工具基础。"
)

# Update subsequent table labels and text references in Chapter 3
for p in doc.paragraphs:
    # Update text references
    if "表1给出三种估计器" in p.text:
        p.text = p.text.replace("表1给出三种估计器", "表2给出三种估计器")
    if "表2按工况汇总" in p.text:
        p.text = p.text.replace("表2按工况汇总", "表3按工况汇总")
    # Update table captions
    if p.text.strip().startswith("表1  事件级"):
        p.text = p.text.replace("表1  事件级", "表2  事件级")
    if p.text.strip().startswith("Table 1  Alpha"):
        p.text = p.text.replace("Table 1  Alpha", "Table 2  Alpha")
    if p.text.strip().startswith("表2  五种子"):
        p.text = p.text.replace("表2  五种子", "表3  五种子")
    # Fix heading duplicate "3  结论" -> "4  结论"
    if p.text.strip() == "3  结论":
        p.text = "4  结论"

doc.save(str(doc_path))
print("Document updated successfully and saved to " + str(doc_path))
