# -*- coding: utf-8 -*-
"""结构干扰红旗层（Gate 0.5 之后、任何端点计算之前）——完全离线，无需 API。

## 为什么需要这一层

图片里点名的「中药来源化合物常有邻苯二酚、醌类等易报假阳性的结构，务必过滤」
在本 skill 里此前**只有教训、没有代码**：PAINS 全库只出现在 CHANGELOG /
02_source_registry.yaml / 04_decision_funnel.md（设计意图「阶跃硬红旗」）/
07_case_lessons.md 中，无任何 .py 实现。`adt/alerts.py` 是 ICH M7 致突变
专家规则，`adt/transport.py::chemotype_flags` 的邻苯二酚 SMARTS 是转运体/成醌
机制用，两者都不是实验干扰过滤层。本模块补齐这个缺口。

实现基础是 **RDKit 自带的 FilterCatalog**（PAINS_A/B/C + BRENK + NIH），
纯本地、无需联网、无需账号/积分/API key。实测 RDKit 2026.09.1 条目数：
PAINS_A 16 / PAINS_B 55 / PAINS_C 409 / BRENK 105 / NIH 180。

## 三条不可绕过的纪律（与 skill 既有裁决体系对齐）

1. **红旗层不是一票**。输出里 `not_a_vote=True`；本层**不产生 verdict**、
   不写 measurements.csv 长表、不进 `reliab` 计票。它只给 `flag` 与
   `gate_action`，供报告层做措辞降级与实验映射。
2. **永不判 FAIL、永不淘汰分子**。PAINS 命中 ≠ 化合物无效，只说明「这次检测
   或计算可能不可信」。类药性（Lipinski/Veber/QED）同样 `admissible_for_rejection=False`
   ——王百合苷 A 的 TPSA 166、HBD 6 本就违规，若当淘汰判据会直接误伤糖苷类
   天然产物。
3. **弱规则必须分档，且分档依据是 catalog 来源 + 结构上下文，不是规则名**。
   这里纠正一次实测误读：把 5 个 catalog 合并成一个后，`Michael_acceptor_1` /
   `catechol` / `beta-keto/anhydride` 看起来像「PAINS 命中」，**实际全部来自 BRENK**；
   真正的 PAINS 条目是 `catechol_A(92)`（PAINS_B）。按 catalog 分别匹配后才看得见这一点
   （本模块因此为每个 catalog 单独建实例，不合并）。

   分档规则：
     - PAINS_A/B/C 命中 → `strong`（真·频繁命中物结构警报，如 `catechol_A(92)`）
     - BRENK/NIH 命中 → 默认 `weak`：「不希望出现的官能团」是**开发性**警报，
       不是实验干扰证据（实测阿司匹林命中 `phenol_ester` 即典型过判）
     - 两条例外升 `strong`：`beta-keto/anhydride`（β-二酮，姜黄素类真干扰机制）、
       `Michael_acceptor_1` **且分子不是 α,β-不饱和羧酸/酯**
     - `Michael_acceptor_1` 且分子是 α,β-不饱和羧酸/酯 → 保持 `weak`。依据
       `adt/alerts.py` 已记录该子类（肉桂酸/对香豆酸/咖啡酰）是弱 Michael 受体、
       多为 GRAS、文献 Ames 阴性；以及 C87 松 SMARTS 把愈创木基误判成邻苯二酚的教训。
       实测阿魏酸（愈创木基）只命中这一条 → `weak_only`，不折减既有结论；
       咖啡酸（真邻苯二酚）另命中 PAINS_B `catechol_A(92)` → 仍判 `suspect_interference`。

   `weak` 命中只要求「单列需实验确认」，**不得写成确认阳性，也不得据此判 FAIL**。

## 确定性

产物**不含时间戳**，同样输入两次运行逐字节一致（与 reliability.csv 的
确定性纪律一致）。需要时间戳请由外层 run_manifest 提供，本层刻意不写。

## 用法

    from adt import interference as IF
    r = IF.assess("COc1cc(/C=C/C(=O)CC(=O)/C=C/c2ccc(O)c(OC)c2)ccc1O", "curcumin")
    print(r["flag"], r["gate_action"])
    rows, paths = IF.assess_file("out/compounds.csv", outdir="out_interference")
"""

from __future__ import annotations

import csv
import io
import json
import os
from collections import OrderedDict

try:
    from rdkit import Chem
    from rdkit.Chem import Descriptors, QED, Crippen, rdMolDescriptors
    from rdkit.Chem import FilterCatalog
except Exception as _e:  # pragma: no cover
    Chem = None
    _IMPORT_ERROR = _e
else:
    _IMPORT_ERROR = None


METHOD = "rdkit-filtercatalog-local"
NOT_A_VOTE = True

# 每个 catalog 单独建，才能标出命中的来源（合并成一个 catalog 会丢掉来源信息）
CATALOG_NAMES = ("PAINS_A", "PAINS_B", "PAINS_C", "BRENK", "NIH")

# BRENK 中两条与实验干扰机制直接相关、可升 strong 的条目
_STRONG_BRENK_DESCRIPTIONS = frozenset(
    {
        "beta-keto/anhydride",  # β-二酮：姜黄素类真干扰机制
        "Michael_acceptor_1",  # 非羧酸/酯上下文下的真 Michael 受体
    }
)

PAINS_CATALOGS = frozenset({"PAINS_A", "PAINS_B", "PAINS_C"})
DEVELOPMENT_CATALOGS = frozenset({"BRENK", "NIH"})

# α,β-不饱和羧酸/酯：C=C-C(=O)O(R)。C87 / alerts.py 的 GRAS 过判子类。
# 姜黄素的 β-二酮（C=C-C(=O)-C）不匹配，故不会被误降级。
_UNSAT_CARBOXYL_SMARTS = "[CX3]=[CX3][CX3](=O)[OX2H1,OX2]"

FLAG_NONE = "none"
FLAG_WEAK_ONLY = "weak_only"
FLAG_SUSPECT = "suspect_interference"
FLAG_INVALID = "invalid_smiles"

ACTION_PROCEED = "proceed"
ACTION_CAVEAT = "proceed_with_caveat"
ACTION_DOWNGRADE = "downgrade_required"
ACTION_REJECT = "reject_for_structure"

CSV_COLS = [
    "compound_id",
    "canonical_smiles",
    "flag",
    "gate_action",
    "n_hits",
    "n_strong",
    "n_weak",
    "strong_hits",
    "weak_hits",
    "lipinski_violations",
    "lipinski_pass",
    "veber_pass",
    "qed",
    "admissible_for_rejection",
    "phys_aggregation",
    "phys_fluorescence",
    "phys_redox_cycling",
    "phys_requires_experiment",
    "note",
]

_CATALOG_CACHE = {}


def rdkit_version():
    try:
        from rdkit import rdBase

        return rdBase.rdkitVersion
    except Exception:
        return "unknown"


def _catalog(name):
    """单个 catalog（带缓存）。RDKit 缺失时抛明确错误，不静默返回空结果。"""
    if Chem is None:
        raise RuntimeError("RDKit 不可用，结构干扰层无法运行：%r" % (_IMPORT_ERROR,))
    if name not in _CATALOG_CACHE:
        enum = getattr(FilterCatalog.FilterCatalogParams.FilterCatalogs, name, None)
        if enum is None:
            raise ValueError("本机 RDKit 无 catalog %r" % name)
        params = FilterCatalog.FilterCatalogParams()
        params.AddCatalog(enum)
        _CATALOG_CACHE[name] = FilterCatalog.FilterCatalog(params)
    return _CATALOG_CACHE[name]


def catalog_sizes():
    """返回 {catalog: 条目数}；用于产物里记录规则集版本，便于换机复核。"""
    return OrderedDict((n, _catalog(n).GetNumEntries()) for n in CATALOG_NAMES)


def druglikeness(mol):
    """类药性三态所需描述符。**明确声明不用于淘汰**。

    Lipinski 违规数按标准 5 条计（MW>500 / logP>5 / HBD>5 / HBA>10），
    `lipinski_pass` 沿用 local_admet 的口径（违规 <=1）。
    Veber：TPSA<=140 且可旋转键<=10。
    """
    mw = Descriptors.MolWt(mol)
    logp = Crippen.MolLogP(mol)
    tpsa = rdMolDescriptors.CalcTPSA(mol)
    hbd = rdMolDescriptors.CalcNumHBD(mol)
    hba = rdMolDescriptors.CalcNumHBA(mol)
    rot = rdMolDescriptors.CalcNumRotatableBonds(mol)
    viol = sum([mw > 500, logp > 5, hbd > 5, hba > 10])
    return OrderedDict(
        [
            ("MW", round(mw, 4)),
            ("logP_crippen", round(logp, 4)),
            ("TPSA", round(tpsa, 4)),
            ("HBD", hbd),
            ("HBA", hba),
            ("rotatable_bonds", rot),
            ("lipinski_violations", viol),
            ("lipinski_pass", bool(viol <= 1)),
            ("veber_pass", bool(tpsa <= 140 and rot <= 10)),
            ("qed", round(QED.qed(mol), 6)),
            ("admissible_for_rejection", False),
            (
                "note",
                "类药性仅作探索层描述；糖苷/天然产物常天然违规，禁止据此淘汰或判 FAIL",
            ),
        ]
    )


# --------------------------------------------------------------------------- #
# 物理 / 光学 / 反应性干扰（2026-11-11 补齐）
#
# 此前 `not_covered_endpoints` 把胶体聚集、荧光干扰、成醌列为 not_covered：
# PAINS/BRENK/NIH 只覆盖「结构频繁命中物」，识别不了这三类机制。
# 这里补的是**结构级预警（rule-based proxy）**，不是实验判据：
#   - 不产生 verdict、不进 reliab 计票、不淘汰分子
#   - 任何 suspect 都必须去 `required_evidence` 所指的正交实验确认
#   - 端点表中的状态因此只能升到 `partially_covered`，不得写成「已覆盖」
#
# 判据来源（公认经验，非本 skill 训练所得）：
#   - 聚集：Irwin et al. Aggregator Advisor 的主要风险因子 = 高 cLogP + 平面芳环；
#           浓度依赖、±0.01% Triton X-100 对照 / DLS 才是判据。
#   - 自荧光：扩展共轭体系、香豆素/色酮发色团；多酚有内滤与淬灭（中药高发）。
#   - 成醌：邻苯二酚 / 对苯二酚 / 邻氨基酚可氧化成醌；GSH 捕获 + HRMS 才是判据。
#   - C87 纪律：愈创木基（4-OH-3-OMe）**不是**邻苯二酚，SMARTS 必须严格。
# --------------------------------------------------------------------------- #
PHYSICAL_METHOD = "rdkit-rule-proxy-offline"
PHYSICAL_CATEGORIES = (
    "colloidal_aggregation",
    "fluorescence_interference",
    "redox_cycling",
)

_CATECHOL_SMARTS = "[c;$(c[OX2H1])][c;$(c[OX2H1])]"  # 相邻两个带 OH 的芳碳
_HYDROQUINONE_SMARTS = "[c]1([OX2H1])[cH][cH][c]([OX2H1])[cH][cH]1"
_O_AMINOPHENOL_SMARTS = "[c]([NX3;H2,H1])[c]([OX2H1])"
_COUMARIN_SMARTS = "O=c1ccc2ccccc2o1"
_CHROMONE_SMARTS = "O=c1cc(oc2ccccc12)"

_EXPERIMENT = {
    "colloidal_aggregation": "±0.01% Triton X-100 的活性/抑制曲线对比 + DLS 或 NMR 聚集证据",
    "fluorescence_interference": "无酶/无靶对照下的化合物本底荧光与内滤效应测定；正交（非光学）读数复核",
    "redox_cycling": "GSH 捕获 + HRMS/MS（± NADPH）、或 DCFH/过氧化氢定量",
}


def _phenolic_oh(mol):
    """芳香环上直接相连的羟基氧数（内滤/成醌的粗略代理）。"""
    return sum(
        1
        for a in mol.GetAtoms()
        if a.GetSymbol() == "O"
        and a.GetTotalNumHs() >= 1
        and any(nb.GetIsAromatic() for nb in a.GetNeighbors())
    )


def physical_interference(mol):
    """三类非结构警报型干扰的离线结构预警。返回 OrderedDict（确定性）。

    flag 只有三态：`suspect`（需正交实验，措辞必须保留）/ `possible` / `none`。
    **没有 FAIL 态**；`requires_experiment=True` 恒为真。
    """
    logp = Crippen.MolLogP(mol)
    arom = rdMolDescriptors.CalcNumAromaticRings(mol)
    conj = sum(
        1
        for b in mol.GetBonds()
        if b.GetBondTypeAsDouble() == 2.0 and b.GetIsConjugated()
    )
    phoh = _phenolic_oh(mol)
    hits = [
        name
        for name, q in (
            ("catechol", _CATECHOL_SMARTS),
            ("hydroquinone", _HYDROQUINONE_SMARTS),
            ("o_aminophenol", _O_AMINOPHENOL_SMARTS),
            ("coumarin", _COUMARIN_SMARTS),
            ("chromone", _CHROMONE_SMARTS),
        )
        if mol.HasSubstructMatch(Chem.MolFromSmarts(q))
    ]

    # 1) 胶体聚集：高 cLogP + 平面芳环共同出现才升 suspect
    if logp >= 3.0 and arom >= 2:
        agg_flag, agg_why = (
            "suspect",
            "cLogP=%.2f≥3.0 且芳香环=%d≥2（聚集物主要风险因子）" % (logp, arom),
        )
    elif logp >= 3.0 or arom >= 3:
        agg_flag, agg_why = (
            "possible",
            "单因子达到关注阈值（cLogP=%.2f / 芳香环=%d）" % (logp, arom),
        )
    else:
        agg_flag, agg_why = "none", "cLogP=%.2f、芳香环=%d，均未达关注阈值" % (
            logp,
            arom,
        )

    # 2) 自荧光：明确发色团或长共轭 → suspect；多酚/多芳环 → possible
    chrom = [x for x in hits if x in ("coumarin", "chromone")]
    if chrom or conj >= 4:
        flu_flag = "suspect"
        flu_why = (
            ("命中发色团 %s" % "/".join(chrom))
            if chrom
            else "共轭双键=%d≥4（长共轭体系）" % conj
        )
    elif phoh >= 2 or arom >= 3:
        flu_flag, flu_why = (
            "possible",
            "酚羟基=%d / 芳香环=%d（多酚内滤与淬灭高发）" % (phoh, arom),
        )
    else:
        flu_flag, flu_why = "none", "无发色团、共轭双键=%d、酚羟基=%d" % (conj, phoh)

    # 3) 成醌：严格 SMARTS；愈创木基不命中（C87）
    quinone_precursors = [
        x for x in hits if x in ("catechol", "hydroquinone", "o_aminophenol")
    ]
    if quinone_precursors:
        redox_flag, redox_why = "suspect", "命中可氧化成醌前体：%s" % "/".join(
            quinone_precursors
        )
    elif phoh >= 2:
        redox_flag, redox_why = "possible", "多酚但未命中邻/对二酚严格模式，需结构复核"
    else:
        redox_flag, redox_why = "none", "无邻苯二酚/对苯二酚/邻氨基酚前体"

    indicators = OrderedDict(
        [
            ("logP_crippen", round(logp, 4)),
            ("aromatic_rings", arom),
            ("conjugated_double_bonds", conj),
            ("phenolic_OH", phoh),
            ("chromophore_hits", chrom),
            ("quinone_precursor_hits", quinone_precursors),
        ]
    )
    out = OrderedDict(
        [
            ("method", PHYSICAL_METHOD),
            ("not_a_vote", True),
            ("admissible_for_rejection", False),
            ("requires_experiment", True),
            ("indicators", indicators),
            ("categories", OrderedDict()),
            (
                "policy",
                (
                    "结构级预警（rule-based proxy），非实验判据；不产生 verdict、"
                    "不进 reliab 计票、不判 FAIL、不淘汰分子；suspect 只表示"
                    "需要正交读数/去污剂对照/GSH 捕获实验确认"
                ),
            ),
        ]
    )
    for cid, fl, why in (
        ("colloidal_aggregation", agg_flag, agg_why),
        ("fluorescence_interference", flu_flag, flu_why),
        ("redox_cycling", redox_flag, redox_why),
    ):
        out["categories"][cid] = OrderedDict(
            [
                ("flag", fl),
                ("why", why),
                ("required_evidence", _EXPERIMENT[cid]),
                ("endpoint_registry_status", "partially_covered（仅结构预警）"),
            ]
        )
    return out


PHYSICAL_SELFTEST_CASES = OrderedDict(
    [
        ("caffeic_acid", ("O=C(O)/C=C/c1ccc(O)c(O)c1", "redox_cycling", "suspect")),
        ("ferulic_acid_C87", ("COc1cc(/C=C/C(=O)O)ccc1O", "redox_cycling", "none")),
        ("hydroquinone", ("Oc1ccc(O)cc1", "redox_cycling", "suspect")),
        ("coumarin", ("O=c1ccc2ccccc2o1", "fluorescence_interference", "suspect")),
        (
            "curcumin",
            (
                "COc1cc(/C=C/C(=O)CC(=O)/C=C/c2ccc(O)c(OC)c2)ccc1O",
                "fluorescence_interference",
                "suspect",
            ),
        ),
        ("caffeine", ("Cn1cnc2c1c(=O)n(C)c(=O)n2C", "colloidal_aggregation", "none")),
        (
            "caffeine_flu",
            ("Cn1cnc2c1c(=O)n(C)c(=O)n2C", "fluorescence_interference", "none"),
        ),
    ]
)


def physical_selftest():
    """物理层正/负对照自检（C87 愈创木基 + 干净对照）。"""
    details = []
    for name, (smi, cat, expect) in PHYSICAL_SELFTEST_CASES.items():
        m = Chem.MolFromSmiles(smi)
        got = physical_interference(m)["categories"][cat]["flag"] if m else "invalid"
        details.append(
            dict(case=name, category=cat, expect=expect, got=got, ok=(got == expect))
        )
    return dict(
        passed=all(d["ok"] for d in details),
        n_cases=len(details),
        details=details,
        failures=[d for d in details if not d["ok"]],
    )


def allowed_statement_for(flag):
    """该 flag 下允许的最高表述 + 禁用表述（措辞封顶钩子）。

    与 `adt/phrasing.py::allowed_statement` 同为「模板 + forbidden」结构，
    但**刻意不并入** phrasing.py：本层不是 verdict 路径，混进去会让
    UNDETERMINED/PASS 的既有模板语义被污染。
    """
    common = [
        "“证明/无毒/安全”等定论词",
        "由预测值推断人体剂量/安全窗",
        "把结构警报命中写成化合物无效",
    ]
    if flag == FLAG_NONE:
        return dict(
            allowed="未命中已知结构干扰警报（不等于已排除干扰；正交实验对照仍必需）",
            forbidden=common + ["已排除干扰", "确认无假阳性风险"],
        )
    if flag == FLAG_WEAK_ONLY:
        return dict(
            allowed=(
                "命中弱规则/需实验确认类警报；该结果须单列为「需实验确认」，"
                "不得写成确认阳性，也不得据此折减既有结论"
            ),
            forbidden=common
            + ["确认阳性", "已排除风险", "未见风险信号", "据该警报判 FAIL"],
        )
    if flag == FLAG_SUSPECT:
        return dict(
            allowed=(
                "命中强结构干扰警报（PAINS 条目或公认干扰机制）：该分子的检测与"
                "计算结果可能受干扰，结论须经去污剂对照/正交检测或实测确认后方可引用"
            ),
            forbidden=common
            + [
                "未见风险信号",
                "已排除风险",
                "未见毒性",
                "安全",
                "证明有效",
                "直接用该端点下 PASS/FAIL 结论",
                "把该端点计入 reliab 独立票",
            ],
        )
    return dict(
        allowed="SMILES 无法解析，结构真实性未通过；整批该分子不得进入下游",
        forbidden=common + ["任何下游端点结论"],
    )


def assess(smiles, compound_id="", include_catalogs=CATALOG_NAMES):
    """单分子评估。返回 dict（不含时间戳，逐次一致）。

    `gate_action` 语义：
      proceed              无红旗，正常继续
      proceed_with_caveat  仅弱规则，继续但措辞必须封顶、单列需实验确认
      downgrade_required   强 PAINS 命中，报告层必须降级/转 UNDETERMINED
      reject_for_structure SMILES 无效，不进入下游
    """
    mol = Chem.MolFromSmiles(str(smiles)) if Chem is not None else None
    if mol is None:
        return OrderedDict(
            [
                ("compound_id", compound_id or ""),
                ("input_smiles", str(smiles)),
                ("canonical_smiles", ""),
                ("flag", FLAG_INVALID),
                ("gate_action", ACTION_REJECT),
                ("not_a_vote", NOT_A_VOTE),
                ("hits", []),
                ("n_hits", 0),
                ("n_strong", 0),
                ("n_weak", 0),
                ("druglikeness", None),
                ("physical_interference", None),
                ("phrasing", allowed_statement_for(FLAG_INVALID)),
                ("method", METHOD),
                ("source_version", "rdkit %s" % rdkit_version()),
                ("catalog_sizes", catalog_sizes()),
            ]
        )

    canon = Chem.MolToSmiles(mol)
    unsat_acid = mol.HasSubstructMatch(Chem.MolFromSmarts(_UNSAT_CARBOXYL_SMARTS))
    hits = []
    for name in include_catalogs:
        if name not in CATALOG_NAMES:
            raise ValueError("未知 catalog %r；可选 %s" % (name, list(CATALOG_NAMES)))
        fc = _catalog(name)
        for entry in fc.GetMatches(mol):
            desc = entry.GetDescription()
            if name in PAINS_CATALOGS:
                sev = "strong"
                reason = "PAINS %s 结构警报（Baell & Holloway 类频繁命中物）" % name
            elif desc in _STRONG_BRENK_DESCRIPTIONS:
                if desc == "Michael_acceptor_1" and unsat_acid:
                    sev = "weak"
                    reason = (
                        "α,β-不饱和羧酸/酯子类：弱 Michael 受体，GRAS / Ames 阴性"
                        "已知过判（adt/alerts.py；C87）；只单列「需实验确认」"
                    )
                else:
                    sev = "strong"
                    reason = (
                        "BRENK 警报但属公认实验干扰机制（%s），且非 GRAS 不饱和酸子类"
                        % desc
                    )
            else:
                sev = "weak"
                reason = (
                    "%s 开发性官能团警报（%s），非实验干扰证据；"
                    "阿司匹林 phenol_ester 即典型过判" % (name, desc)
                )
            hits.append(
                OrderedDict(
                    [
                        ("catalog", name),
                        ("description", desc),
                        ("severity", sev),
                        ("reason", reason),
                    ]
                )
            )
    # 稳定排序（catalog 名 + 描述），保证逐字节确定性
    hits.sort(key=lambda h: (h["catalog"], h["description"], h["severity"]))

    n_strong = sum(1 for h in hits if h["severity"] == "strong")
    n_weak = len(hits) - n_strong
    if n_strong:
        flag, action = FLAG_SUSPECT, ACTION_DOWNGRADE
    elif n_weak:
        flag, action = FLAG_WEAK_ONLY, ACTION_CAVEAT
    else:
        flag, action = FLAG_NONE, ACTION_PROCEED

    dl = druglikeness(mol)
    phys = physical_interference(mol)
    return OrderedDict(
        [
            ("compound_id", compound_id or ""),
            ("input_smiles", str(smiles)),
            ("canonical_smiles", canon),
            ("flag", flag),
            ("gate_action", action),
            ("not_a_vote", NOT_A_VOTE),
            ("hits", hits),
            ("n_hits", len(hits)),
            ("n_strong", n_strong),
            ("n_weak", n_weak),
            ("druglikeness", dl),
            ("physical_interference", phys),
            ("phrasing", allowed_statement_for(flag)),
            ("method", METHOD),
            ("source_version", "rdkit %s" % rdkit_version()),
            ("catalog_sizes", catalog_sizes()),
            (
                "policy",
                OrderedDict(
                    [
                        ("not_a_verdict", True),
                        ("admissible_for_rejection", False),
                        ("enters_reliab_vote", False),
                        ("writes_measurements_long_table", False),
                        (
                            "forced_on_strong_hit",
                            "结论降级或转 UNDETERMINED；需正交实验确认",
                        ),
                    ]
                ),
            ),
        ]
    )


def _read_input(path):
    """兼容 compounds.csv（带表头，优先 calc_smiles）与 `id<TAB>smiles` 无表头输入。

    与 adt/cli.py::load_compounds_csv 的嗅探口径一致；不 import cli 避免循环依赖。
    """
    rows = []
    with io.open(path, encoding="utf-8-sig") as fh:
        first = fh.readline()
        fh.seek(0)
        if "," in first:
            for r in csv.DictReader(fh):
                cid = (r.get("compound_id") or "").strip()
                smi = (
                    r.get("calc_smiles")
                    or r.get("input_smiles")
                    or r.get("smiles")
                    or ""
                ).strip()
                if cid or smi:
                    rows.append((cid, smi))
        else:
            for ln in fh:
                ln = ln.rstrip("\n")
                if not ln.strip() or ln.lstrip().startswith("#"):
                    continue
                parts = ln.split("\t") if "\t" in ln else ln.split()
                if len(parts) >= 2:
                    rows.append((parts[0].strip(), parts[1].strip()))
    return rows


def _csv_row(r):
    dl = r.get("druglikeness") or {}
    return {
        "compound_id": r["compound_id"],
        "canonical_smiles": r["canonical_smiles"],
        "flag": r["flag"],
        "gate_action": r["gate_action"],
        "n_hits": r["n_hits"],
        "n_strong": r["n_strong"],
        "n_weak": r["n_weak"],
        "strong_hits": ";".join(
            h["description"] for h in r["hits"] if h["severity"] == "strong"
        ),
        "weak_hits": ";".join(
            h["description"] for h in r["hits"] if h["severity"] == "weak"
        ),
        "lipinski_violations": dl.get("lipinski_violations", ""),
        "lipinski_pass": dl.get("lipinski_pass", ""),
        "veber_pass": dl.get("veber_pass", ""),
        "qed": dl.get("qed", ""),
        "admissible_for_rejection": dl.get("admissible_for_rejection", False),
        "phys_aggregation": _phys_flag(r, "colloidal_aggregation"),
        "phys_fluorescence": _phys_flag(r, "fluorescence_interference"),
        "phys_redox_cycling": _phys_flag(r, "redox_cycling"),
        "phys_requires_experiment": bool(
            (r.get("physical_interference") or {}).get("requires_experiment", False)
        ),
        "note": r["phrasing"]["allowed"],
    }


def _phys_flag(r, category):
    p = r.get("physical_interference") or {}
    c = (p.get("categories") or {}).get(category) or {}
    return c.get("flag", "not_assessed")


def assess_file(input_path, outdir, include_catalogs=CATALOG_NAMES):
    """批量评估并落盘 `interference_flags.csv` + `interference_report.json`。

    产物不含时间戳 → 逐字节可复现。返回 (results, {"csv":..., "json":...})。
    """
    src = _read_input(input_path)
    if not src:
        raise ValueError("输入解析出 0 个分子：%s（检查格式/BOM/表头）" % input_path)
    results = [assess(smi, cid, include_catalogs) for cid, smi in src]
    os.makedirs(outdir, exist_ok=True)
    csv_path = os.path.join(outdir, "interference_flags.csv")
    json_path = os.path.join(outdir, "interference_report.json")

    with io.open(csv_path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_COLS, extrasaction="ignore")
        w.writeheader()
        for r in results:
            w.writerow(_csv_row(r))

    payload = OrderedDict(
        [
            ("method", METHOD),
            ("source_version", "rdkit %s" % rdkit_version()),
            ("catalog_sizes", catalog_sizes()),
            ("n_compounds", len(results)),
            ("n_none", sum(1 for r in results if r["flag"] == FLAG_NONE)),
            ("n_weak_only", sum(1 for r in results if r["flag"] == FLAG_WEAK_ONLY)),
            ("n_suspect", sum(1 for r in results if r["flag"] == FLAG_SUSPECT)),
            ("n_invalid", sum(1 for r in results if r["flag"] == FLAG_INVALID)),
            ("not_a_vote", NOT_A_VOTE),
            ("deterministic", True),
            ("physical_interference_method", PHYSICAL_METHOD),
            (
                "n_physical_suspect",
                sum(
                    1
                    for r in results
                    for c in (
                        (r.get("physical_interference") or {}).get("categories") or {}
                    ).values()
                    if c.get("flag") == "suspect"
                ),
            ),
            (
                "policy_note",
                (
                    "红旗层，不产生 verdict、不进 reliab 计票、不写长表；"
                    "弱规则命中不折减结论，强命中须降级并做正交实验确认；"
                    "物理/光学/反应性层同为结构预警，需正交实验确认"
                ),
            ),
            ("results", results),
        ]
    )
    with io.open(json_path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False))
    return results, {"csv": csv_path, "json": json_path}


# --------------------------------------------------------------------------- #
# 内置自检：正/负对照 + C87 教训回归（CLI --selftest 与 pytest 共用）
# --------------------------------------------------------------------------- #
SELFTEST_CASES = OrderedDict(
    [
        # 姜黄素：β-二酮 + Michael 受体（BRENK 两条升 strong）；注意 PAINS catalog 本身 0 命中
        ("curcumin", ("COc1cc(/C=C/C(=O)CC(=O)/C=C/c2ccc(O)c(OC)c2)ccc1O", "strong")),
        # 真 PAINS_B 命中 catechol_A(92)
        (
            "EGCG",
            (
                "Oc1cc(O)c2C[C@H](OC(=O)c3cc(O)c(O)c(O)c3)[C@H](Oc2c1)"
                "c4cc(O)c(O)c(O)c4",
                "strong",
            ),
        ),
        ("quercetin", ("O=c1c(O)c(-c2ccc(O)c(O)c2)oc3cc(O)cc(O)c13", "strong")),
        ("caffeine", ("Cn1cnc2c1c(=O)n(C)c(=O)n2C", "none")),
        ("aspirin", ("CC(=O)Oc1ccccc1C(=O)O", "weak_only")),
        # 咖啡酸：真邻苯二酚（PAINS_B 命中）→ 仍判红旗
        ("caffeic_acid", ("O=C(O)/C=C/c1ccc(O)c(O)c1", "strong_and_catechol")),
        # 阿魏酸：愈创木基，C87 教训必须不命中 catechol；GRAS 子类只判 weak_only
        ("ferulic_acid", ("COc1cc(/C=C/C(=O)O)ccc1O", "gras_weak")),
    ]
)


def selftest():
    """返回 dict(passed, n_cases, failures, details)；不写盘。"""
    details, failures = [], []
    for name, (smi, expect) in SELFTEST_CASES.items():
        r = assess(smi, name)
        descs = [h["description"] for h in r["hits"]]
        ok = True
        if expect == "strong":
            ok = r["flag"] == FLAG_SUSPECT and r["n_strong"] >= 1
        elif expect == "none":
            ok = r["flag"] == FLAG_NONE and r["n_hits"] == 0
        elif expect == "weak_only":
            ok = r["flag"] == FLAG_WEAK_ONLY and r["n_strong"] == 0
        elif expect == "not_none":
            ok = r["n_hits"] >= 1
        elif expect == "strong_and_catechol":
            ok = (
                r["flag"] == FLAG_SUSPECT
                and any("catechol" in d for d in descs)
                and any(h["catalog"].startswith("PAINS") for h in r["hits"])
            )
        elif expect == "gras_weak":
            ok = (
                r["flag"] == FLAG_WEAK_ONLY
                and r["n_strong"] == 0
                and not any("catechol" in d for d in descs)
            )
        if not ok:
            failures.append(
                dict(
                    case=name,
                    expect=expect,
                    flag=r["flag"],
                    n_strong=r["n_strong"],
                    n_weak=r["n_weak"],
                    hits=descs,
                )
            )
        details.append(
            dict(
                case=name,
                expect=expect,
                flag=r["flag"],
                n_strong=r["n_strong"],
                n_weak=r["n_weak"],
                hits=descs,
                ok=ok,
            )
        )
    return dict(
        passed=not failures,
        n_cases=len(SELFTEST_CASES),
        failures=failures,
        details=details,
    )
