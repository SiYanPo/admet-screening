# -*- coding: utf-8 -*-
"""糖苷水解-苷元暴露轴（深水区 2.3 增量）。

报告 2.3 的核心立场：对肉桂酰糖苷类，**酰基葡萄糖醛酸化（acyl glucuronidation）不是最紧迫的
代谢风险**——本类 14/14 是酯键糖苷、无自由羧酸，不形成酰基葡萄糖醛酸（已在 acyl_glucuronide
模块判 low）。本类真正的暴露决定因素是：

  (1) **糖苷键的肠道水解**：糖基（葡萄糖）通过 O-糖苷键接到苷元/甘油上，肠菌与肠黏膜糖苷酶
      （β-葡萄糖苷酶、乳糖酶-根皮苷水解酶）会将其水解；
  (2) **苷元首过效应**：水解/直接吸收的苷元（如阿魏酸/咖啡酸）经历极低胃肠稳定性、
      极短血浆半衰期、低口服生物利用度、以及"虽能过 BBB 但脑浓度极低"（见 verified 文献
      PMC10005154 / Tu 2012）。

本模块把"糖苷稳定性-苷元暴露轴"形式化为结构警示 + 风险分级，与 acyl_glucuronide 模块互补：
前者是"豁免"（本类不适用），后者是"需实验定位的真实风险"。

分类（O-糖苷键的苷元连接类型）：
  - acyl_glycoside   : 糖的端位 O 酯化到羧酸（酯型糖苷键）→ 酯酶广谱水解，最易水解
  - phenolic_glycoside: 糖 O 连到芳环碳（酚苷/芳苷，如 salicin/arbutin）→ β-糖苷酶/结肠菌
  - alkyl_glycoside  : 糖 O 连到脂肪碳（烷基苷）→ 醚样，相对最稳定

风险分级透明、结构驱动，不依赖外部预测；产物清晰标注为"结构警示 + 风险分级"。
"""

import os

from rdkit import Chem, RDLogger

RDLogger.DisableLog("rdApp.*")


# 糖环（吡喃/呋喃己糖）含一个环内 O 与 5 个环碳；端位（异头）碳接一个环外 O
_SUGAR_RING_O = Chem.MolFromSmarts("[O;R]")  # 环内氧
_ESTER = Chem.MolFromSmarts("[#6](=[#8])-[#8]-[#6]")  # 酯 C(=O)-O-C（任意醇/酚酯）
# 芳环-羧酸/酯（酚酸/肉桂酸类苷元）：咖啡酸/阿魏酸是**肉桂酸型**（芳环经乙烯基接羧基），
# 苯甲酸型（芳环直接接羧基）也要覆盖。二者分别给 SMARTS 取并集。
_AROMATIC_ACID = [
    Chem.MolFromSmarts("[#6]1:[#6]:[#6]:[#6]:[#6]:[#6]1-[#6](=[#8])"),  # 苯甲酸型
    Chem.MolFromSmarts(
        "[#6]1:[#6]:[#6]:[#6]:[#6]:[#6]1-[#6]=[#6]-[#6](=[#8])"
    ),  # 肉桂酸型
]
# 乙酰酯（CH3-C(=O)-O-）：增加亲脂性、减少自由羟基 → 与"同系物暴露差异"直接相关
_ACETYL = Chem.MolFromSmarts("[CH3][C](=[O])[O]")


def has_sugar_ring(mol):
    """是否存在真正的糖环（吡喃糖/呋喃糖），而不是"任何含氧环"。

    v4.21.2 修复：此前判据是"5/6 元环里有 1 个氧"，于是
      小檗碱的亚甲二氧基（O-CH2-O，环内 2 个 O）、
      胺碘酮的苯并呋喃（环内 O 邻接芳香碳）、
      槲皮素/黄芩苷母核的黄酮 C 环（色酮，环内 O 两侧是 sp2）
    全部被判成"有糖环"。结论 low 虽侥幸正确，但**理由是错的**，
    一旦口径放宽就会把非糖苷当成糖苷处理。

    现在的四条硬条件（缺一不可）：
      1) 环大小 5 或 6，且环内**恰好 1 个**氧（糖环的单氧特征；缩醛例外不在此列）；
      2) 环内氧的两个环内邻居都是 **sp3** 碳（排除呋喃/色酮/香豆素/亚甲二氧基）；
      3) 环上至少 **2 个碳**各挂一个**环外氧**（羟基/烷氧基/糖苷键）；
      4) 环内碳全部为 sp3（饱和糖）。
    """
    if mol is None:
        return False
    ri = mol.GetRingInfo()
    for ring in ri.AtomRings():
        if len(ring) not in (5, 6):
            continue
        ring_set = set(ring)
        ring_o = [i for i in ring if mol.GetAtomWithIdx(i).GetAtomicNum() == 8]
        if len(ring_o) != 1:  # 条件 1
            continue
        o = mol.GetAtomWithIdx(ring_o[0])
        nbrs = [a for a in o.GetNeighbors() if a.GetIdx() in ring_set]
        if len(nbrs) != 2:
            continue
        if any(a.GetHybridization() != Chem.HybridizationType.SP3 for a in nbrs):
            continue  # 条件 2
        carbons = [i for i in ring if mol.GetAtomWithIdx(i).GetAtomicNum() == 6]
        if len(carbons) < 4:
            continue
        if any(
            mol.GetAtomWithIdx(i).GetHybridization() != Chem.HybridizationType.SP3
            for i in carbons
        ):
            continue  # 条件 4
        n_exo_o = 0
        for i in carbons:  # 条件 3
            a = mol.GetAtomWithIdx(i)
            if any(
                nb.GetAtomicNum() == 8 and nb.GetIdx() not in ring_set
                for nb in a.GetNeighbors()
            ):
                n_exo_o += 1
        if n_exo_o >= 2:
            return True
    return False


def _anomeric_attachment(mol):
    """返回端位（异头）碳所连的环外原子的元素/芳香性，用于判定苷元连接类型。

    近似：糖环里与外环 O 相连、且该 O 还连着一个环外重原子的那个碳，取其环外邻居。
    """
    if mol is None:
        return None
    ri = mol.GetRingInfo()
    for ring in ri.AtomRings():
        if len(ring) not in (5, 6):
            continue
        ring_set = set(ring)
        if not any(mol.GetAtomWithIdx(i).GetAtomicNum() == 8 for i in ring):
            continue
        for i in ring:
            a = mol.GetAtomWithIdx(i)
            # 端位碳：连接一个环外 O（糖苷键的供体 O）
            for nbr in a.GetNeighbors():
                if nbr.GetIdx() in ring_set:
                    continue
                if nbr.GetAtomicNum() == 8:  # 环外 O
                    # 这个 O 再连到苷元原子
                    for nn in nbr.GetNeighbors():
                        if nn.GetIdx() == i:
                            continue
                        return nn  # 苷元原子
    return None


def _aglycone_has_aryl(mol, ana):
    """从异头邻居（苷元入口原子）出发，深度≤2 内是否存在芳环（经至多一个 O 桥接）。

    覆盖两类"酚苷/芳苷"：
      - 直接酚苷（ary-O-糖，如 arbutin：异头邻居即芳碳）；
      - 苄醇/水杨苷型（糖-O-CH2-O-芳环，如 salicin：芳环在异头邻居外 2 键处）。
    不进入糖环（葡萄糖均为脂肪碳，不会误报），复杂度 O(1)。
    """
    if mol is None or ana is None:
        return False
    seen = {ana.GetIdx()}
    stack = [(ana.GetIdx(), 0)]
    while stack:
        idx, d = stack.pop()
        if d > 2:
            continue
        a = mol.GetAtomWithIdx(idx)
        if a.GetIsAromatic():
            return True
        for n in a.GetNeighbors():
            ni = n.GetIdx()
            if ni in seen:
                continue
            if n.GetAtomicNum() in (6, 8):  # 只走 C/O，不进杂原子分支
                seen.add(ni)
                stack.append((ni, d + 1))
    return False


def _bond_position(ana):
    """糖苷键所连苷元碳的取代度：primary/secondary/tertiary。

    这是区分"同分异构/同系糖苷"的关键结构维度：端位糖苷键（primary）位阻小、
    糖苷酶易接近 → 水解快；中位（secondary）位阻大 → 水解慢、完整糖苷存活更久。
    Regaloside A（糖在甘油 C1，primary）vs Regaloside B（糖在甘油 C2，secondary）
    正是这一维度的天然对照。
    """
    if ana is None:
        return "n/a"
    if ana.GetIsAromatic():
        return "aromatic"
    if ana.GetAtomicNum() != 6:
        return "hetero"
    deg = ana.GetDegree()
    return {2: "primary", 3: "secondary", 4: "tertiary"}.get(deg, "other")


def classify(smiles, name=""):
    """返回完整诊断 dict。"""
    mol = Chem.MolFromSmiles(smiles) if smiles else None
    if mol is None:
        return dict(
            compound_id=name,
            smiles=smiles,
            parse_ok=False,
            sugar_ring=False,
            glycosidic_bond=False,
            glycoside_bond_type="n/a",
            ester_bond=False,
            phenolic_acid_moiety=False,
            bond_position="n/a",
            n_ester_bonds=0,
            acetylated=False,
            intestinal_hydrolysis_risk="n/a",
            aglycone_first_pass_risk="n/a",
            summary="糖苷水解警示：SMILES 解析失败，无法评估；需人工核对结构",
            reasons=["smiles_parse_failed"],
        )

    sugar = has_sugar_ring(mol)
    ana = _anomeric_attachment(mol)
    ester_matches = mol.GetSubstructMatches(_ESTER) if _ESTER else []
    ester = bool(ester_matches)
    aromatic_acid = any(mol.HasSubstructMatch(p) for p in _AROMATIC_ACID)
    bond_position = _bond_position(ana)
    acetylated = bool(mol.HasSubstructMatch(_ACETYL)) if _ACETYL else False

    glycosidic = bool(sugar and ana is not None)
    bond_type = "none"
    if glycosidic:
        if (
            ana.GetAtomicNum() == 6
            and ana.GetDegree() == 3
            and any(
                b.GetBondType().name == "DOUBLE"
                for b in ana.GetBonds()
                if b.GetOtherAtom(ana).GetAtomicNum() == 8
            )
        ):
            bond_type = "acyl_glycoside"  # 糖外 O 连到羰基碳（酯型糖苷键）
        elif _aglycone_has_aryl(mol, ana):
            bond_type = "phenolic_glycoside"  # 芳环在苷元内（直接酚苷或苄醇/水杨苷型）
        else:
            bond_type = "alkyl_glycoside"

    reasons = []
    if not sugar:
        reasons.append("无糖环：不是糖苷（可能为苷元/游离酸）")
    if glycosidic:
        reasons.append("检出 O-糖苷键，类型=%s" % bond_type)
    else:
        reasons.append("未检出糖-苷元 O-糖苷键")
    if ester:
        reasons.append(
            "检出酯键 C(=O)-O-C（肠酯酶/胰酯酶广谱水解；若苷元为酚酸则释放活性酚酸）"
        )
    if aromatic_acid:
        reasons.append("检出芳环-羧酸/酯（酚酸/肉桂酸类苷元：咖啡酸/阿魏酸型）")

    # ---- 风险分级（透明、结构驱动）----
    if not glycosidic and not ester:
        hyd = "low"
        fp = "low"
        if not sugar:
            summ = (
                "糖苷水解警示：非糖苷（无 O-糖苷键、无酯键）→ 本轴不适用；"
                "注意若含自由羧酸仍可能走 acyl_glucuronide 轴"
            )
        else:
            summ = "糖苷水解警示：有糖环但无苷元 O-糖苷键（可能已在苷元端闭环）→ 本轴低相关"
    elif not glycosidic and ester:
        # 2026-11-19（面板实跑）：阿司匹林这类**非糖苷但有酯键**的分子，旧代码落进
        # 糖苷分支，输出 "糖苷水解风险=high / 键型=none" —— 名字与内容自相矛盾，
        # 读者会把它当成"糖苷轴结论"。这里单列一支：明确本轴不适用，酯酶水解另行登记。
        hyd = "high"
        fp = "high" if aromatic_acid else "medium"
        summ = (
            "非糖苷（未检出 O-糖苷键，仅检出 %d 个酯键）：**糖苷水解轴不适用**；"
            "但酯键可被肠/胰酯酶广谱水解（风险=high），水解产物须按活性代谢物处理，"
            "并回到 acyl_glucuronide 轴复核。" % len(ester_matches)
        )
    else:
        # 肠道水解风险
        if bond_type == "acyl_glycoside" or ester:
            hyd = "high"  # 酯型最易水解
        elif bond_type == "phenolic_glycoside":
            hyd = "medium"  # β-糖苷酶/结肠菌
        else:  # alkyl_glycoside
            hyd = "medium"
        # 苷元首过风险：酚酸/肉桂酸类苷元 → 低 GI 稳定、短 t½、低 Bioavailability、低脑浓度
        fp = "high" if aromatic_acid else "medium"
        summ = (
            "糖苷水解-苷元暴露轴：肠道水解风险=%s、苷元首过风险=%s。"
            "本类真实暴露决定因素为糖苷键水解 + 苷元（酚酸）首过/肾清除，"
            "而非酰基葡萄糖醛酸（已在 acyl_glucuronide 模块判 low）。"
            "框架将其标为需实验：模拟肠液稳定性 + 门静脉/外周血苷元定量" % (hyd, fp)
        )

    return dict(
        compound_id=name,
        smiles=smiles,
        parse_ok=True,
        sugar_ring=sugar,
        glycosidic_bond=glycosidic,
        glycoside_bond_type=bond_type,
        ester_bond=bool(ester),
        phenolic_acid_moiety=bool(aromatic_acid),
        bond_position=bond_position,
        n_ester_bonds=len(ester_matches),
        acetylated=acetylated,
        axis_applicable=bool(glycosidic),
        intestinal_hydrolysis_risk=hyd,
        aglycone_first_pass_risk=fp,
        summary=summ,
        reasons=reasons,
    )


def assess_file(path, outdir=None):
    import csv

    rows = []
    with open(path, encoding="utf-8-sig") as fh:
        rdr = csv.DictReader(fh)
        for r in rdr:
            smi = r.get("calc_smiles") or r.get("input_smiles") or r.get("smiles") or ""
            cid = r.get("compound_id") or r.get("name") or ""
            res = classify(smi, name=cid)
            rows.append(
                dict(
                    compound_id=cid,
                    sugar_ring=res["sugar_ring"],
                    glycosidic_bond=res["glycosidic_bond"],
                    glycoside_bond_type=res["glycoside_bond_type"],
                    ester_bond=res["ester_bond"],
                    phenolic_acid_moiety=res["phenolic_acid_moiety"],
                    bond_position=res["bond_position"],
                    n_ester_bonds=res["n_ester_bonds"],
                    acetylated=res["acetylated"],
                    # 2026-11-19：新增列必须落盘，否则"本轴不适用"只活在内存里，
                    # 下游读 CSV 时看不到，仍会把 high 当成糖苷结论。
                    axis_applicable=res.get("axis_applicable"),
                    intestinal_hydrolysis_risk=res["intestinal_hydrolysis_risk"],
                    aglycone_first_pass_risk=res["aglycone_first_pass_risk"],
                    summary=res["summary"],
                )
            )
    if outdir:
        os.makedirs(outdir, exist_ok=True)
        op = os.path.join(outdir, "glycoside_hydrolysis.csv")
        with open(op, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        return rows, op
    return rows, None
