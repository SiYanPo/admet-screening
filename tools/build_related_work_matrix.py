# -*- coding: utf-8 -*-
"""生成 Related Work 逐构件差异矩阵（Supplementary Table 1）。

数据来源：references/PRIOR_ART_UPDATE_2026-11-24_LIBRARY.md 与
references/PRIOR_ART_2026_SCAN.md 的人工核实条目。本脚本只做结构化输出，不引入新事实。

输出：references/RELATED_WORK_MATRIX.md
运行：python tools/build_related_work_matrix.py
"""

from __future__ import annotations

import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 构件列（C1–C6）：与 PRIOR_ART_2026_SCAN.md §1.1 的五构件 + 本轮新增 C6
COLUMNS = [
    ("C1", "源级准入单位"),
    ("C2", "先于统计组合器"),
    ("C3", "可审计+归因"),
    ("C4", "统一三价代价"),
    ("C5", "代价依赖失效边界"),
    ("C6", "异源独立队列"),
]

# 每条：id, 名称, 出处, 各构件状态(✓/△/✗) + 一句差异
WORKS = [
    (
        "W1",
        "Chow / Cortes / Geifman",
        "1970 / 2016 / 2017",
        ("✗", "✗", "✗", "△", "✗", "✗"),
        "样本级拒判与代价，非源级",
    ),
    (
        "W2",
        "Caruana 2004 / Zhou 2002 / Shafer 1976",
        "ensemble selection / GASEN / Dempster",
        ("△", "✓", "✗", "✗", "✗", "✗"),
        "先于组合但按成员性能，无代价",
    ),
    (
        "W3",
        "Dawid–Skene 1979 / Hendrickx 2024",
        "无金标准可靠性 / 多拒判器",
        ("✗", "✗", "△", "✗", "✗", "✗"),
        "估计可靠性与拒因，非源准入",
    ),
    (
        "W4",
        "Honest ADMET",
        "Zenodo 10.5281/zenodo.20710324",
        ("✗", "✗", "✗", "✗", "✗", "△"),
        "22 端点样本级选择性预测；ρ=0.07",
    ),
    (
        "W5",
        "Trustworthy ADMET Benchmark",
        "Zenodo 10.5281/zenodo.21374237",
        ("✗", "✗", "✗", "✗", "✗", "△"),
        "22×5×5 评选型，非组合前源准入",
    ),
    (
        "W6",
        "TRUST-ADMET",
        "Zenodo 10.5281/zenodo.20997792",
        ("✗", "△", "△", "✗", "✗", "△"),
        "全套技术组件但无源级决策层",
    ),
    (
        "W7",
        "AdmitOR",
        "arXiv:2608.15565",
        ("△", "△", "✓", "✗", "✗", "✗"),
        "label-free 准入，FDR 判据，LLM 技能库",
    ),
    (
        "W8",
        "SciForge / PRML",
        "arXiv:2607.16038 / spec.falsify.dev",
        ("✗", "✗", "✓", "✗", "✗", "✗"),
        "审计基础设施与规范，无决策实验",
    ),
    (
        "W9",
        "PACT",
        "arXiv:2609.01662",
        ("△", "△", "✓", "✗", "✗", "✗"),
        "机器人领域溯源融合 + typed action admission",
    ),
    (
        "W10",
        "CADT",
        "10.3390/ph19091445",
        ("✗", "△", "△", "✗", "✗", "✗"),
        "样本级置信度门控，结论同向但无统一代价",
    ),
    (
        "W11",
        "MIRAGE-DTA",
        "10.1093/bioinformatics/btag812",
        ("△", "△", "✓", "✗", "△", "✗"),
        "证据仲裁在融合旁，risk@coverage 但无三价代价",
    ),
    (
        "W12",
        "NeuroBACE-ML",
        "10.1016/j.jmgm.2026.109415",
        ("✗", "✗", "△", "✗", "✗", "✗"),
        "单模型可靠性筛选",
    ),
    (
        "W13",
        "ADMET-EvO",
        "arXiv:2609.10121",
        ("△", "✗", "✓", "✗", "✗", "△"),
        "证据门+账本+冻结+source-held-out，无三价代价边界",
    ),
    (
        "THIS",
        "本工作",
        "Stage 1 RR（本地包）",
        ("✓", "✓", "✓", "✓", "✓", "✓"),
        "源级准入 + 统一代价 + 代价边界 + FDA 异源队列",
    ),
]

LEGEND = {
    "✓": "明确实现",
    "△": "部分覆盖 / 相邻概念",
    "✗": "未覆盖",
}


def main():
    out = [
        "# Supplementary Table 1｜Related Work 逐构件差异矩阵",
        "",
        "> 生成器：`tools/build_related_work_matrix.py`（可重算）。",
        "> 数据来源：`references/PRIOR_ART_2026_SCAN.md`、`references/PRIOR_ART_UPDATE_2026-11-23.md`、",
        "> `references/PRIOR_ART_UPDATE_2026-11-24_LIBRARY.md`（均为一手/预印本核实条目）。",
        "> 判读：只有 THIS 行在 C1–C6 六列全为 ✓；W11（MIRAGE-DTA）在 C5 有相邻概念（risk@coverage），",
        "> 但无统一三价代价下的符号翻转边界。",
        "",
        "| ID | 工作 | 出处 | "
        + " | ".join("%s %s" % c for c in COLUMNS)
        + " | 关键差异 |",
        "|---|---|---|" + "---|" * len(COLUMNS) + "---|",
    ]
    for wid, name, src, marks, diff in WORKS:
        out.append(
            "| %s | **%s** | %s | %s | %s |" % (wid, name, src, " | ".join(marks), diff)
        )
    out += [
        "",
        "## 图例",
        "",
    ]
    for k, v in LEGEND.items():
        out.append("- `%s` = %s" % (k, v))
    out += [
        "",
        "## 必须随表声明",
        "",
        "1. 表中 `△` 表示相邻概念或部分覆盖，**不得**在正文中升格为「已实现」。",
        "2. W4/W5/W6 为软件记录或预印本，W7/W8/W9/W13 为预印本，引用时须标注未经同行评审。",
        "3. C6 的 ✓ 仅表示有异源独立队列（FDA DILIrank 2.0，n=60），不表示前瞻金标准；"
        "DILI estimand=PARTIAL，只可比较决策排序。",
        "4. 本矩阵不覆盖中文库全部命中；CNKI 四组检索记录见 `lib_search/CNKI_SEARCH_LOG.md`。",
        "",
    ]
    p = os.path.join(ROOT, "references", "RELATED_WORK_MATRIX.md")
    io.open(p, "w", encoding="utf-8", newline="\n").write("\n".join(out))
    print("[matrix] 14 行 × 6 列 -> references/RELATED_WORK_MATRIX.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
