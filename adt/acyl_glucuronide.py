# -*- coding: utf-8 -*-
"""酰基葡萄糖醛酸化（acyl glucuronidation）结构警示与风险分级。

深水区建议 2.3（Grillo 2021；羟基肉桂酸酰基葡萄糖醛酸苷的亲电反应性研究）：
肉桂酰糖苷及其苷元（肉桂酸 / 咖啡酸 / 阿魏酸）携带羧酸 / 酰基结构，在 II 相代谢中
可形成酰基葡萄糖醛酸苷（acyl glucuronide）。该类结合物具有内在亲电反应性——可经
1,2- 与 1,3-酰基迁移重排为异葡糖醛酸苷，并进一步与蛋白亲核位点形成共价加合物，
介导生物活化与潜在肝毒性。其反应性与**羧酸 α-碳的烯醇化能力**和**共轭延长程度**
直接相关。

设计纪律（与全 skill 一致）：
  - 这不是一个需要外部源的预测端点，而是一个**结构警示 + 风险分级**（role=reference），
    不进质量裁决、不当数值使用。
  - 输入三要素（报告明确要求）：① 羧酸/酰基结构存在（SMARTS）；② α-碳取代模式；
    ③ 共轭程度。输出结构化警示，供"代谢风险"段显式陈述，而不是留白。
"""

import os

from rdkit import Chem, RDLogger

RDLogger.DisableLog("rdApp.*")

# 自由羧酸（含去质子形式）——酰基葡萄糖醛酸化发生的结构前提
_CARBOXYL = Chem.MolFromSmarts("[CX3](=O)[OX1H0-,OX2H1]")
# 酯 / 酰胺（可水解释放羧酸，间接风险）
_ESTER = Chem.MolFromSmarts("[CX3](=O)[OX2;!H1]")
# α,β-不饱和羧酸：羰基 α 碳为 sp2 并经双键延长（如肉桂酸 Ph-CH=CH-COOH）
_CONJ_ALKENE = Chem.MolFromSmarts("[CX3](=O)[#6X3]=[#6]")
# 芳环共轭：羧基直接连在芳环上（如苯甲酸、咖啡酸芳环经烯键共轭）
_CONJ_ARYL = Chem.MolFromSmarts("[CX3](=O)c")


def _alpha_carbon(mol, carboxyl_match):
    """从羧酸匹配里取羰基碳，返回其非氧碳邻居（α-碳）。"""
    for aid in carboxyl_match:
        atom = mol.GetAtomWithIdx(aid)
        if atom.GetSymbol() != "C":
            continue
        for nbr in atom.GetNeighbors():
            if nbr.GetSymbol() == "C":
                return nbr
    return None


# 已知反例（2026-11-19 面板实跑，双氯芬酸 vs 阿托伐他汀）：
#   本规则按"共轭延长 + α-烯醇化"排序，会把**双氯芬酸判 medium、阿托伐他汀判 high**。
#   但文献共识是双氯芬酸的酰基葡糖醛酸苷属经典高危（反应性重排 + 蛋白加合 → 肝损伤），
#   阿托伐他汀则不是其主要毒性通路。原因是双氯芬酸的 α-碳连在两个芳胺上、不与双键共轭，
#   而"共轭"这条代理特征抓不到 2,6-二氯二苯胺骨架的重排风险。
#   → 本模块只作"要不要做该实验"的筛查，**不得用于跨分子风险排序**；
#     排序须以实测为准（与 STATISTICAL_POLICY 的排序封顶条款一致）。


def risk(smiles, name=""):
    """对单个 SMILES 做酰基葡萄糖醛酸化结构警示。

    返回 dict(
      name, has_carboxylic_acid(bool), has_ester(bool),
      alpha_substitution(str: primary/secondary/tertiary/none),
      enolizable(bool), conjugated(bool),
      grade(str: high/medium/low), reasons(list[str]))
    """
    mol = Chem.MolFromSmiles(smiles) if smiles else None
    out = dict(
        name=name,
        smiles=smiles,
        has_carboxylic_acid=False,
        has_ester=False,
        alpha_substitution="none",
        enolizable=False,
        conjugated=False,
        grade="low",
        reasons=[],
    )
    if mol is None:
        out["reasons"].append("SMILES 解析失败，无法评估")
        return out

    cooh = mol.HasSubstructMatch(_CARBOXYL)
    ester = mol.HasSubstructMatch(_ESTER)
    out["has_carboxylic_acid"] = cooh
    out["has_ester"] = ester and not cooh

    enolizable = False
    alpha_sub = "none"
    if cooh:
        m = mol.GetSubstructMatch(_CARBOXYL)
        ac = _alpha_carbon(mol, m)
        if ac is not None:
            n_h = ac.GetTotalNumHs()
            # α-碳的"重邻居数（排除羰基碳）"决定取代度
            heavy = [x for x in ac.GetNeighbors() if x.GetSymbol() != "C" or True]
            # 去掉羰基碳本身
            heavy = [x for x in ac.GetNeighbors() if x.GetIdx() != m[0]]
            n_heavy = len(heavy)
            enolizable = n_h >= 1
            alpha_sub = (
                "primary"
                if n_heavy <= 1
                else "secondary" if n_heavy == 2 else "tertiary"
            )
            out["enolizable"] = enolizable
            out["alpha_substitution"] = alpha_sub

    conjugated = mol.HasSubstructMatch(_CONJ_ALKENE) or mol.HasSubstructMatch(
        _CONJ_ARYL
    )
    out["conjugated"] = conjugated

    reasons = []
    if not cooh and not ester:
        out["grade"] = "low"
        reasons.append("无羧酸/酯酰基结构：酰基葡萄糖醛酸化前提缺失，风险低")
        out["reasons"] = reasons
        return out

    if not cooh and ester:
        out["grade"] = "low"
        reasons.append(
            "含酯键（无自由羧酸）：酯酶水解可能释放羧酸，间接产生酰基"
            "葡萄糖醛酸化风险，但本结构本身不形成酰基葡萄糖醛酸苷"
        )
        out["reasons"] = reasons
        return out

    # 有自由羧酸
    if conjugated and enolizable:
        out["grade"] = "high"
        reasons.append(
            "羧酸 + α-碳可烯醇化（%s, α-H 存在）+ 共轭延长"
            "（芳环/烯键）→ 酰基葡萄糖醛酸苷亲电反应性与酰基迁移风险高" % alpha_sub
        )
    elif conjugated:
        out["grade"] = "medium"
        reasons.append(
            "羧酸 + 共轭延长；α-碳无烯醇化氢（如芳环直接相连）→ "
            "酰基葡萄糖醛酸苷重排风险中等，仍需监测"
        )
    elif enolizable:
        out["grade"] = "medium"
        reasons.append(
            "羧酸 + α-碳可烯醇化（%s）→ 标准酰基葡萄糖醛酸化风险，"
            "需肝安全监测" % alpha_sub
        )
    else:
        out["grade"] = "low"
        reasons.append(
            "羧酸但 α-碳无烯醇化氢（%s）→ 仍形成葡萄糖醛酸苷，"
            "但酰基迁移/共价加合风险低" % alpha_sub
        )
    reasons.append(
        "注意：此为结构警示（Grillo 2021 机制），非实测肝毒性；"
        "须与实测（酰基葡糖醛酸苷稳定性 / 蛋白加合物）一并权衡，"
        "不得单独用作安全性判定"
    )
    out["reasons"] = reasons
    return out


def assess_file(path, outdir=None):
    """对 compounds.csv（含 calc_smiles / input_smiles）逐分子评估，返回行列表。"""
    import csv

    rows = []
    with open(path, encoding="utf-8-sig") as fh:
        rdr = csv.DictReader(fh)
        for r in rdr:
            smi = r.get("calc_smiles") or r.get("input_smiles") or r.get("smiles") or ""
            cid = r.get("compound_id") or r.get("name") or ""
            res = risk(smi, name=cid)
            rows.append(
                dict(
                    compound_id=cid,
                    has_carboxylic_acid=int(res["has_carboxylic_acid"]),
                    has_ester=int(res["has_ester"]),
                    alpha_substitution=res["alpha_substitution"],
                    enolizable=int(res["enolizable"]),
                    conjugated=int(res["conjugated"]),
                    acyl_glucuronide_risk=res["grade"],
                    reasons=" | ".join(res["reasons"]),
                )
            )
    if outdir:
        os.makedirs(outdir, exist_ok=True)
        op = os.path.join(outdir, "acyl_glucuronide.csv")
        with open(op, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        return rows, op
    return rows, None
