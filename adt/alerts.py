# -*- coding: utf-8 -*-
"""最小结构警示层（expert rule-based）—— 补齐 ICH M7 要求的"第一法"。

## 为什么需要这个模块（这不是新卖点，是补方法链的缺口）

ICH M7(R2)《评估和控制药物中 DNA 反应性（致突变）杂质以限制潜在致癌风险》
（ICH 2023 通过 R2；国家药监局 2024-01-05 公告适用）§6 明确要求：

    用 (Q)SAR 方法预测细菌回复突变试验结果时，应采用**两种互补的预测方法**：
    一种**基于专家知识规则**，另一种**基于统计学**；两者均须符合 OECD 的
    (Q)SAR 验证一般原则。两种方法均无警示结构时，方可判定该杂质无致突变关注
    （Class 5），无需进一步试验。

ICH M7(R2) Q&A 6.2 进一步规定：**两种模型中任一给出"域外/未覆盖"结果时，
不得据此判为 Class 5**，需补充评估（类似物 read-across / 专家复核 / 另一模型）。

本框架原有三个源（RF-Morgan / Ridge-描述符 / RF-MACCS）**全部是统计模型**，
没有任何专家规则层。因此按 ICH M7，它**根本不满足双方法要求**——
这解释了为什么 ames 在框架里只能被登记为"不推荐计算"：
不是端点不可用，是**方法链不全**。

## 本模块的边界（必须一起读）

1. 这是一份**官能团级最小警示集**，取自致突变机制教科书共识（烷化剂 / 芳胺 / 硝基 /
   环氧化物 / 亚硝胺 等），**不是** Benigni–Bossa 或 Kazius 全表，也**不等价于**
   Derek/Sarah 等商业规则库。任何"本模块已覆盖 XX 条规则"的说法都是夸大。
2. 每条规则只标"命中/未命中"，**不给概率**。它只能把结论推向"需复核"，
   不能单独支撑"安全"。
3. 它的表现必须在本仓库实测（`run_ames_alerts.py`），不得只凭"教科书都说"。
4. **假阴性是默认风险**：最小集的敏感性必然低于全表规则库。因此本层的
   正确用法是"命中即升级"，不是"未命中即放行"——与 ICH M7 的保守方向一致。
"""

import re

try:
    from rdkit import Chem
except Exception:  # pragma: no cover
    Chem = None


# (id, SMARTS, 机制类别, 说明)
# 机制类别只用于分组统计，不参与判定。
ALERTS = [
    (
        "aromatic_nitro",
        "c[N+](=O)[O-]",
        "nitro_reduction",
        "芳硝基：经硝基还原酶活化生成亚硝基/羟胺中间体",
    ),
    (
        "nitro_aliphatic",
        "[CX4][N+](=O)[O-]",
        "nitro_reduction",
        "脂肪族硝基：同类活化路径，证据弱于芳硝基，仍按警示处理",
    ),
    (
        "aromatic_amine",
        "[NX3;!$(NC=O);!$(N=O);!$(NS(=O)=O)]c",
        "nitrenium",
        "芳胺：经 CYP 氧化生成羟胺，再经酯化形成氮宾离子",
    ),
    (
        "n_aryl_amide",
        "[NX3;$(NC=O);!$(N=O)]c",
        "nitrenium_prodrug",
        "N-芳基酰胺（乙酰芳胺等）：体内脱乙酰后成为芳胺，属经典致突变前体"
        "（如 2-乙酰氨基芴）。**弱规则**：同时会命中对乙酰氨基酚等非致突变物，"
        "故单独成条，验证时给「含/不含」两套结果",
    ),
    (
        "nitroso",
        "[NX2]=O",
        "nitroso",
        "亚硝基/N-亚硝胺类：直接烷化，属 ICH M7 cohort of concern 相邻类",
    ),
    (
        "n_nitroso",
        "[NX3][NX2]=O",
        "nitroso",
        "N-亚硝胺：ICH M7 明确指出 TTC 不适用（cohort of concern）",
    ),
    ("epoxide", "C1OC1", "alkylation", "环氧化物：三元环张力驱动 SN2 烷化"),
    ("aziridine", "C1CN1", "alkylation", "氮丙啶：同等烷化能力"),
    ("aziridinium_like", "[NX3+]1CC1", "alkylation", "季铵化氮丙啶鎓"),
    ("mustard", "[Cl,Br,I][CX4][CX4][NX3]", "alkylation", "氮芥类双官能烷化剂"),
    (
        "alkyl_halide",
        "[CX4;!$(C=O)][Cl,Br,I]",
        "alkylation",
        "非芳基卤代烷：SN2 烷化（芳卤不计入，反应性低得多）",
    ),
    (
        "sulfonate_ester",
        "[OX2][S](=O)(=O)[#6]",
        "alkylation",
        "磺酸酯：优良离去基，烷化活性高",
    ),
    ("aldehyde", "[CX3H1](=O)[#6]", "michael", "脂肪/芳香醛：可形成 Schiff 碱加合物"),
    (
        "michael_acceptor",
        "[CX3]=[CX3][CX3]=O",
        "michael",
        "α,β-不饱和羰基：Michael 加成。**已知过判**（v4.5）：该 SMARTS 同时命中"
        "α,β-不饱和羧酸（肉桂酸/对香豆酸/咖啡酰奎宁酸等），而羧酸根是弱 Michael 受体，"
        "此类物质多为食品级 GRAS、文献 Ames 阴性。华山参数据集 16 个命中者中 4 个属此列，"
        "剔除后 Ames FAIL 由 15 降至 11。保守侧保留现规则（ICH M7 命中即升级），"
        "但报告须把酸类单列为'需实验确认'而非'确认阳性'。v4.6 候选：拆出"
        " alpha_beta_unsaturated_acid 弱规则并以 TDC AMES 重新标定。",
    ),
    ("aromatic_diazonium", "c[N+]#N", "nitrenium", "芳基重氮盐：极活泼亲电试剂"),
    ("hydrazine", "[NX3][NX3]", "nitro_reduction", "肼/取代肼：氧化生成重氮或氮宾"),
    (
        "aromatic_hydroxylamine",
        "[NX3][OH]",
        "nitrenium",
        "N-羟基芳胺：芳胺活化的直接前体",
    ),
]

_COMPILED = []


def _compiled():
    global _COMPILED
    if _COMPILED:
        return _COMPILED
    if Chem is None:
        raise RuntimeError("结构警示层需要 RDKit")
    out = []
    for aid, smarts, mech, note in ALERTS:
        patt = Chem.MolFromSmarts(smarts)
        if patt is None:
            raise RuntimeError("警示 SMARTS 无法编译：%s (%s)" % (aid, smarts))
        out.append((aid, patt, mech, note))
    _COMPILED = out
    return out


def alerts_of(mol):
    """返回该分子命中的警示列表 [(id, mechanism, note)]；未命中返回 []。"""
    if mol is None:
        return []
    hits = []
    for aid, patt, mech, note in _compiled():
        if mol.HasSubstructMatch(patt):
            hits.append((aid, mech, note))
    return hits


def alerts_from_smiles(smi):
    if Chem is None:
        raise RuntimeError("结构警示层需要 RDKit")
    m = Chem.MolFromSmiles(smi)
    return alerts_of(m)


def alert_positive(smi_or_mol):
    """便捷布尔接口：是否命中任一警示。"""
    if isinstance(smi_or_mol, str):
        return bool(alerts_from_smiles(smi_or_mol))
    return bool(alerts_of(smi_or_mol))


def rule_table():
    """可审计的规则清单（写进报告/附录用）。"""
    return [{"id": a, "smarts": s, "mechanism": m, "note": n} for a, s, m, n in ALERTS]


def two_method_verdict(stat_verdict, alert_hit, in_domain=True):
    """ICH M7 双方法合成规则。

    stat_verdict : "PASS"（统计模型判为无致突变）/ "FAIL" / "UNDETERMINED"
    alert_hit    : 结构警示层是否命中（True 表示有警示）
    in_domain    : 统计模型是否在适用域内

    返回 (verdict, reason)。规则逐条对应 ICH M7：
      · 统计阴性 + 无警示 + 域内        → PASS（Class 5 方向），**唯一允许放行的组合**
      · 任一阳性（统计阳性 或 有警示）    → FAIL 方向（不得判 Class 5）
      · 统计域外                        → UNDETERMINED（Q&A 6.2：不得判 Class 5）
      · 统计 UNDETERMINED               → UNDETERMINED
    """
    if not in_domain:
        return "UNDETERMINED", (
            "ICH M7 Q&A 6.2：两模型中任一域外时不得判 Class 5，"
            "需 read-across / 专家复核 / 另一经验证模型"
        )
    if stat_verdict == "UNDETERMINED":
        return "UNDETERMINED", "统计模型未给出二值结论（多源冲突或投票不足）"
    if stat_verdict == "FAIL" or alert_hit:
        why = []
        if stat_verdict == "FAIL":
            why.append("统计模型阳性")
        if alert_hit:
            why.append("结构警示命中")
        return "FAIL", "ICH M7：任一方法阳性即不得判 Class 5（" + "；".join(why) + "）"
    return "PASS", (
        "ICH M7：统计模型阴性且无结构警示（两种互补方法均阴性）"
        "→ 可判无致突变关注；**不得**据此推导任何限量数值"
    )
