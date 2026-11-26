# -*- coding: utf-8 -*-
"""报告规范与可复现层（v3.0.0）：TRIPOD+AI 清单 / model card / FAIR 映射。

三份文献，三个用途
------------------
1. **TRIPOD+AI 2024**（Collins GS et al. BMJ 2024;385:e078378,
   DOI: 10.1136/bmj-2023-078378）：27 条报告清单，统一回归与 ML 预测模型的报告，
   强调**判别力与校准并报**、乐观偏差、代码/数据可得性、亚组公平性。
   本模块把它做成"逐条自查表"，每条给出证据指针与缺口。

2. **Model Cards**（Mitchell M et al. FAT* '19, pp.220-229,
   DOI: 10.1145/3287560.3287596）：随模型发布的说明书。本 skill 有 8 个预测源，
   每个源一张卡（见 references/source_cards.yaml），披露预期用途/训练数据/
   适用域/已知失效/版本/限流/证据等级。

3. **FAIR**（Wilkinson MD et al. Sci Data 2016;3:160018,
   DOI: 10.1038/sdata.2016.18）：F/A/I/R 共 15 条子原则。本 skill 的
   `provenance_url`/`source_version`/`run_manifest`/`ledger` 本来就是 FAIR 的工程落地，
   本模块把这种对应关系**显式化**，便于在论文的 Data Availability 段引用。

**诚实边界**：TRIPOD+AI 的条目文字是本模块按**分节语义**重写的，不是官方逐字原文；
引用时应以 BMJ 原文为准，本表只作为"我们自查到哪一条"的索引。
"""

import csv
import io
import os

import yaml

_HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CARDS = os.path.join(os.path.dirname(_HERE), "references", "source_cards.yaml")


# ---------------------------------------------------------------------------
# 1) TRIPOD+AI 自查表
# ---------------------------------------------------------------------------
TRIPOD_ITEMS = [
    ("1a", "标题/摘要", "标明这是预测模型研究，并给出模型类型（多源聚合）"),
    ("2", "背景", "说明为何需要聚合多源 ADMET 预测（单源不可信）"),
    ("3", "目标", "明确目标化学类、用途（筛选/决策/发表）与时间范围"),
    ("4", "数据来源", "每个源的数据获取方式、抓取日期、版本可追溯"),
    ("5", "研究对象", "化合物入选/排除标准（结构 gate、状态标准化）"),
    ("6", "结局", "端点定义、单位、阈值来源（文献 or 实测）"),
    ("7", "预测因子", "每个源的独立性分组与版本号"),
    ("8", "样本量", "化合物数与阳性事件数"),
    ("9", "缺失数据", "域外/缺失的处理方式（不赋分、不读作阴性）"),
    ("10", "模型开发", "聚合规则（中位数/独立组门控）是否预注册"),
    ("11", "判别力", "AUROC/AUPRC 及聚类 bootstrap 置信区间"),
    ("12", "校准", "校准斜率/截距、Brier、O:E、ECE"),
    ("13", "外部验证", "独立数据集（不同化学类或不同实验室）验证"),
    ("14", "亚组/公平性", "化学型亚组（糖苷/苷元、酸/碱）表现是否分别报告"),
    ("15", "模型输出", "输出形式（概率/类别/档位）与解释方式"),
    ("16", "可得性", "代码、规则表、manifest 是否随报告提供"),
]


def _has(path):
    return bool(path) and os.path.exists(path)


def tripod_checklist(ctx):
    """ctx 是一堆"有没有"的布尔/数值；返回逐条状态。

    状态：satisfied / partial / not_met / not_applicable
    """
    c = dict(ctx or {})
    n_comp = c.get("n_compounds", 0) or 0
    n_pos = c.get("n_pos", 0) or 0
    out = []

    def add(code, section, item, status, evidence, gap=""):
        out.append(
            dict(
                code=code,
                section=section,
                item=item,
                status=status,
                evidence=evidence,
                gap=gap,
            )
        )

    add(
        "1a",
        "标题/摘要",
        TRIPOD_ITEMS[0][2],
        "satisfied" if c.get("skill_version") else "partial",
        "skill 版本 %s" % c.get("skill_version", "-"),
        "" if c.get("skill_version") else "未记录工具版本",
    )
    add(
        "2",
        "背景",
        TRIPOD_ITEMS[1][2],
        "satisfied" if c.get("has_registry") else "not_met",
        "源登记表 %s" % ("有" if c.get("has_registry") else "无"),
        "" if c.get("has_registry") else "缺源登记表",
    )
    add(
        "3",
        "目标",
        TRIPOD_ITEMS[2][2],
        "satisfied" if c.get("has_tier") else "partial",
        "档位 %s" % c.get("tier", "-"),
        (
            ""
            if c.get("has_tier")
            else "未声明证据档位（用途未定，则无法判断是否 fit-for-purpose）"
        ),
    )
    add(
        "4",
        "数据来源",
        TRIPOD_ITEMS[3][2],
        (
            "satisfied"
            if c.get("n_sources_versioned", 0) >= max(1, c.get("n_sources", 1))
            else ("partial" if c.get("n_sources") else "not_met")
        ),
        "%d/%d 个源有版本号" % (c.get("n_sources_versioned", 0), c.get("n_sources", 0)),
        (
            ""
            if c.get("n_sources_versioned", 0) >= max(1, c.get("n_sources", 1))
            else "部分源缺版本号/抓取日期"
        ),
    )
    add(
        "5",
        "研究对象",
        TRIPOD_ITEMS[4][2],
        "satisfied" if c.get("has_normalize") else "not_met",
        "结构 gate %s" % ("已执行" if c.get("has_normalize") else "未执行"),
        "" if c.get("has_normalize") else "未记录结构校验结果",
    )
    add(
        "6",
        "结局",
        TRIPOD_ITEMS[5][2],
        (
            "satisfied"
            if c.get("n_endpoints_with_unit", 0) >= max(1, c.get("n_endpoints", 1))
            else ("partial" if c.get("n_endpoints") else "not_met")
        ),
        "%d/%d 个端点声明单位"
        % (c.get("n_endpoints_with_unit", 0), c.get("n_endpoints", 0)),
        (
            ""
            if c.get("threshold_from_measured")
            else "阈值仍为文献起点值（provisional），需湿实验校准"
        ),
    )
    add(
        "7",
        "预测因子",
        TRIPOD_ITEMS[6][2],
        "satisfied" if c.get("has_source_groups") else "partial",
        "独立性分组 %s" % ("已加载" if c.get("has_source_groups") else "未加载"),
        "" if c.get("has_source_groups") else "未声明源间独立性",
    )
    add(
        "8",
        "样本量",
        TRIPOD_ITEMS[7][2],
        (
            "satisfied"
            if (n_comp >= 30 and n_pos >= 10)
            else ("partial" if n_comp else "not_met")
        ),
        "n=%d，阳性=%d" % (n_comp, n_pos),
        "" if (n_comp >= 30 and n_pos >= 10) else "样本/事件数偏少，性能估计不稳",
    )
    add(
        "9",
        "缺失数据",
        TRIPOD_ITEMS[8][2],
        "satisfied" if c.get("has_coverage") else "not_met",
        "覆盖矩阵 %s" % ("有" if c.get("has_coverage") else "无"),
        "" if c.get("has_coverage") else "未报告覆盖率：域外可能被误读为阴性",
    )
    add(
        "10",
        "模型开发",
        TRIPOD_ITEMS[9][2],
        "satisfied" if c.get("has_manifest") else "partial",
        "manifest %s" % ("有（判据可追溯）" if c.get("has_manifest") else "无"),
        "" if c.get("has_manifest") else "聚合规则未预注册，阈值改动无法追溯",
    )
    add(
        "11",
        "判别力",
        TRIPOD_ITEMS[10][2],
        (
            "satisfied"
            if c.get("has_real_benchmark")
            else ("partial" if c.get("has_benchmark") else "not_met")
        ),
        "非 DEMO 基准 %s" % ("有" if c.get("has_real_benchmark") else "无"),
        "" if c.get("has_real_benchmark") else "无实测真值基准：判别力未知",
    )
    add(
        "12",
        "校准",
        TRIPOD_ITEMS[11][2],
        (
            "satisfied"
            if c.get("has_calibration")
            else ("partial" if c.get("has_benchmark") else "not_met")
        ),
        "校准 %s" % ("已报告" if c.get("has_calibration") else "未报告"),
        "" if c.get("has_calibration") else "概率端点未报校准（Van Calster 2019）",
    )
    add(
        "13",
        "外部验证",
        TRIPOD_ITEMS[12][2],
        "satisfied" if c.get("has_external") else "not_met",
        "外部验证 %s" % ("有" if c.get("has_external") else "无"),
        (
            ""
            if c.get("has_external")
            else "无独立化学类/独立实验室验证；同系类似物不能自证"
        ),
    )
    add(
        "14",
        "亚组/公平性",
        TRIPOD_ITEMS[13][2],
        "satisfied" if c.get("has_subgroup") else "partial",
        "亚组分析 %s" % ("有" if c.get("has_subgroup") else "无"),
        "" if c.get("has_subgroup") else "未按化学型分层报告",
    )
    add(
        "15",
        "模型输出",
        TRIPOD_ITEMS[14][2],
        "satisfied" if c.get("has_tier") else "partial",
        "输出档位与措辞封顶 %s" % ("有" if c.get("has_tier") else "无"),
        "",
    )
    add(
        "16",
        "可得性",
        TRIPOD_ITEMS[15][2],
        "satisfied" if (c.get("has_manifest") and c.get("has_registry")) else "partial",
        "manifest+registry %s"
        % ("齐备" if (c.get("has_manifest") and c.get("has_registry")) else "不全"),
        (
            ""
            if (c.get("has_manifest") and c.get("has_registry"))
            else "代码/规则/清单未随报告一并归档"
        ),
    )
    return out


# ---------------------------------------------------------------------------
# 2) model cards
# ---------------------------------------------------------------------------
def load_cards(path=None):
    p = path or DEFAULT_CARDS
    if not os.path.exists(p):
        return {}
    with io.open(p, encoding="utf-8") as fh:
        d = yaml.safe_load(fh) or {}
    return {s["id"]: s for s in (d.get("sources") or []) if s.get("id")}


def model_cards(path=None, missing=None):
    """返回 (rows, markdown)。rows 用于 csv；markdown 用于报告附录。"""
    cards = load_cards(path)
    rows = []
    for cid in sorted(cards):
        c = cards[cid]
        rows.append(
            dict(
                source=cid,
                label=c.get("label", ""),
                group=c.get("independence_group", ""),
                intended_use=c.get("intended_use", ""),
                model_type=c.get("model_type", ""),
                training_data=str(c.get("training_data", "")),
                applicability_domain=str(c.get("applicability_domain", "")),
                n_known_failures=len(c.get("known_failures") or []),
                known_failures=" | ".join(c.get("known_failures") or []),
                version_tracking=c.get("version_tracking", ""),
                rate_limit=c.get("rate_limit", ""),
                access_mode=c.get("access_mode", ""),
                evidence_level=c.get("evidence_level", ""),
            )
        )
    md = [
        "# 预测源 model card 汇总",
        "",
        "> 依据 Mitchell et al. FAT* '19（DOI 10.1145/3287560.3287596）。",
        "> 未披露的字段写 not_disclosed——**空格比编造好**。",
        "",
    ]
    for r in rows:
        md.append("## %s（%s）" % (r["label"] or r["source"], r["group"]))
        md.append("")
        md.append("| 字段 | 内容 |")
        md.append("|---|---|")
        for k, v in (
            ("预期用途", r["intended_use"]),
            ("模型类型", r["model_type"]),
            ("训练数据", r["training_data"]),
            ("适用域", r["applicability_domain"]),
            ("版本追踪", r["version_tracking"]),
            ("限流", r["rate_limit"]),
            ("接入方式", r["access_mode"]),
            ("证据等级", r["evidence_level"]),
        ):
            md.append("| %s | %s |" % (k, v))
        md.append("")
        if r["known_failures"]:
            md.append("**已知失效（本项目实测）**")
            for f in cards[r["source"]].get("known_failures") or []:
                md.append("- %s" % f)
            md.append("")
    if missing:
        md.append("## 未登记的源")
        md.append("")
        md.append(
            "本批用到但**没有 model card** 的源（不得当作已评估）：%s"
            % "、".join(sorted(missing))
        )
        md.append("")
    return rows, "\n".join(md)


# ---------------------------------------------------------------------------
# 3) FAIR 映射
# ---------------------------------------------------------------------------
FAIR_ITEMS = [
    ("F1", "数据与元数据有全球唯一持久标识", "compound_id + inchikey + provenance_url"),
    (
        "F2",
        "数据用丰富元数据描述",
        "measurements schema（endpoint/unit/source/retrieved_at/domain_flag）",
    ),
    ("F3", "元数据明确包含数据标识", "source_version + retrieved_at 逐行记录"),
    ("F4", "元数据在可检索资源中登记", "references/02_source_registry.yaml（源清单）"),
    ("A1", "可用标识符检索数据", "compound_id / inchikey 定位"),
    ("A1.1", "协议开放且免费", "全部本地 CLI，无服务端依赖"),
    (
        "A2",
        "元数据在数据不可用时仍可访问",
        "即使源失效，registry 仍记录该源与其失效原因",
    ),
    (
        "I1",
        "使用形式化、可获取的词汇表",
        "references/endpoint_aliases.yaml + unit_for() 单一真源",
    ),
    (
        "I2",
        "使用 FAIR 词汇表",
        "端点 id 与单位沿用社区口径（µL/min/mg、log10 cm/s、fraction）",
    ),
    ("I3", "引用其他数据时带限定引用", "provenance_url 指向原始源/文献"),
    (
        "R1.1",
        "数据有清晰可用的使用许可",
        "各源许可随源而异；本 skill 只做二次分析与引用",
    ),
    (
        "R1.2",
        "数据有详细来源（provenance）",
        "run_manifest.yaml（输入哈希）+ evidence_ledger.csv",
    ),
    (
        "R1.3",
        "符合领域相关社区标准",
        "OECD QAF 四原则 / TRIPOD+AI 报告清单 / PROBAST 偏倚评估",
    ),
]


def fair_mapping(ctx):
    """把 FAIR 15 条映射到本 skill 的产物，返回逐条状态。"""
    c = dict(ctx or {})
    out = []
    for code, principle, artifact in FAIR_ITEMS:
        if code.startswith("F"):
            ok = c.get("has_inchikey_or_id", True) and (
                c.get("has_registry") if code == "F4" else True
            )
            gap = "" if ok else "缺源登记表"
        elif code.startswith("A"):
            ok = c.get("has_manifest", True)
            gap = "" if ok else "缺 manifest：无法在数据不可用时提供元数据"
        elif code.startswith("I"):
            ok = c.get("has_units", True)
            gap = "" if ok else "端点单位未统一声明"
        else:
            ok = bool(c.get("has_manifest")) and bool(c.get("has_ledger", True))
            gap = "" if ok else "缺 manifest / ledger：provenance 链不完整"
        out.append(
            dict(
                code=code,
                principle=principle,
                artifact=artifact,
                status="covered" if ok else "partial",
                gap=gap,
            )
        )
    return out


def write_csv(path, rows, cols):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with io.open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return len(rows)
