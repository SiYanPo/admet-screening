# -*- coding: utf-8 -*-
"""OATP1A2 / LAT1 / GLUT1 摄取通道启发式（B2 闭环动作，2026-11-03 续）。

⚠️ 这是**启发式结构代理（heuristic）**，不是预测模型，也不是实测。
  - OATP1A2 识别大体积有机阴离子（电荷 + 疏水区），SMARTS 只能近似电荷与疏水，丢失空间排布；
  - LAT1 识别大体积中性 L-氨基酸（α-氨基 + α-羧基 + 大疏水侧链），SMARTS 对 L-立体专一性近似很差；
  - GLUT1 只转运**游离单糖**（D-葡萄糖的 C1–C6 空间排布），**不转运完整糖苷**。
  本模块所有输出都**不得**进 reliab 计票、不得改 verdict / confidence；
  只用于在 BBB = UNDETERMINED / PASSTHRU 时把"摄取通道"从纯叙事升级为
  "有结构依据的可验证假设"，并**强制绑定**对应过表达细胞摄取 ± 竞争抑制剂验证后才能下结论。

注意与 efflux_heuristic.py 的对称性：外排（P-gp/BCRP）主导**负项**（压低脑暴露），
本模块的三通道（OATP1A2/LAT1/GLUT1）主导**正项候选**（升高脑暴露），二者独立取证。

生物学保真（与 bbb.py 的 UPTAKE_ACTION 一致，不得夸大）：
  - GLUT1 是 BBB 内皮主要葡萄糖转运体，但**只转运游离单糖**，不转运完整糖苷；
  - SGLT1 在 BBB 内皮**无功能性表达**（Yu et al. 实证），其真实作用位点是肠上皮（决定 Fa 而非脑暴露），
    故本模块**不含 SGLT1 的结构规则**（它不属于 BBB 侧摄取通道，留作肠侧 Fa 通道）。

特征来源（共识药效团，文献级，非本包自创）：
  - OATP 家族（含 OATP1A2，脑内皮）：偏好大体积有机阴离子
    （Hagenbuch B, Meier PJ. Pflugers Arch 2004;447:653-665；König J et al. 综述）；
    经典探针底物 estrone-3-sulfate、fexofenadine。
  - LAT1（SLC7A5，脑内皮）：大体积中性 L-氨基酸
    （Kanai Y et al. J Biol Chem 1998;273:23629-23635；系统 L 氨基酸转运体），
    底物含 L-DOPA、甲状腺氨酸、亮/异亮/缬氨酸、苯丙/色/酪氨酸。
  - GLUT1（SLC2A1，BBB 内皮）：游离 D-己糖（Mueckler M. Eur J Biochem 1994;219:713-725），
    不转运完整糖苷（糖基接到苷元/甘油后分子过大且失去单糖空间排布）。

人类可读副本与参考文献见 references/transporter_priors.yaml 的 uptake_heuristics 块。
"""

from __future__ import annotations

# ---- 结构特征（可执行源；yaml 仅作审计副本） ----
# 有机阴离子（生理 pH 下解离）。注意：多数 SMILES 把羧酸写成中性 C(=O)O，
# 故须同时匹配去质子化 [O-]C(=O) 与中性 [OH]C(=O)（后者只匹配羧酸 OH，不匹配酯氧）。
ANIONIC_CARBOXYLATE_DEPROT = "[O-]C(=O)"
ANIONIC_CARBOXYLATE_NEUTRAL = "[OH]C(=O)"
ANIONIC_SULFONATE = "[S](=O)(=O)[O-]"
ANIONIC_SULFATE = "[O-]S(=O)(=O)[O-]"
ANIONIC_PHOSPHATE = "[O-]P(=O)([O-])[O-]"
# 广义羧基（去质子化或中性），用于 LAT1 的 α-氨基酸识别（氨基酸在 SMILES 中常为中性写法）
CARBOXYLATE_BROAD = "[$([O-]C(=O)),$([OH]C(=O))]"
# 可质子化/可电离的 N（仲/叔胺、吡啶 N；排除酰胺与 N-氧化物）——LAT1 侧链的常见碱性中心
BASIC_N_SMARTS = "[N;!$(NC=O);!$(N=O)]"
# 芳香环（疏水区粗代理）
PHENYL_SMARTS = "c1ccccc1"
# α-氨基酸骨架（zwitterion 近似）：N–C(非羰基)–C(=O)[O-,OH]，即游离中性 L-氨基酸的粗代理。
# 注：L-立体专一性无法用 SMARTS 表达，这里是"包含"而非"等于"判断；中性写法 C(=O)O 也匹配。
AA_BACKBONE_SMARTS = "[N;!$(NC=O)][C;!$(C=O)]([C;!$(C=O)])C(=O)[$([O-]),$([OH])]"
# 游离己糖吡喃环（GLUT1 候选；C1 为游离 OH，即还原端未成苷）
FREE_MONOSACCHARIDE_SMARTS = "OC1OC(CO)C(O)C(O)C1O"

MANDATORY_ASSAY_OATP1A2 = (
    "MDCK-OATP1A2 / HEK293-OATP1A2 摄取（2 µM，2–5 min，37°C）± "
    "estrone-3-sulfate 50 µM 或 rifampicin 50 µM 竞争；摄取抑制 ≥50%（IC50 < 对照）判底物。"
    "注意与 OATP2B1（肠侧）区分：用脑内皮来源细胞系或人原代 BBB 模型更贴近脑暴露；"
    "若确为底物，脑暴露截距上调，但须与外排通道（P-gp/BCRP）净效应叠乘。"
)
MANDATORY_ASSAY_LAT1 = (
    "HEK293-LAT1 / MDCK-LAT1 摄取（2 µM，1–2 min，± L-亮氨酸 1 mM 或 BCH 10 mM 竞争）；"
    "氨基酸类或氨基酸样分子（如 L-DOPA、甲状腺氨酸、加巴喷丁）优先验证。"
    "L-立体专一性无法由本启发式保证，必须以实验确认。"
)
MANDATORY_ASSAY_GLUT1 = (
    "仅对**游离单糖/苷元水解产物**考虑：原代 BBB 内皮细胞或 hCMEC/D3 ± "
    "cytochalasin B（GLUT 抑制剂）或高浓度 D-葡萄糖竞争。"
    "⚠️ **完整糖苷不是 GLUT1 底物**（糖基接到苷元/甘油后体积过大且失去单糖空间排布）；"
    "若分子为糖苷，其 GLUT1 相关性仅存在于**苷元/单糖水解产物**，须先水解再评估。"
)


def _mol_from(smiles):
    from rdkit import Chem

    if not smiles:
        return None
    try:
        return Chem.MolFromSmiles(str(smiles))
    except Exception:
        return None


def _compiled():
    from rdkit import Chem

    pats = {}
    for name, sm in (
        (
            "anionic",
            "[$([O-]C(=O)),$([OH]C(=O)),$([S](=O)(=O)[O-]),$([O-]S(=O)(=O)[O-]),$([O-]P(=O)([O-])[O-])]",
        ),
        ("carboxylate_broad", CARBOXYLATE_BROAD),
        ("basic_n", BASIC_N_SMARTS),
        ("phenyl", PHENYL_SMARTS),
        ("aa_backbone", AA_BACKBONE_SMARTS),
        ("free_monosaccharide", FREE_MONOSACCHARIDE_SMARTS),
    ):
        pats[name] = Chem.MolFromSmarts(sm)
    return pats


def _has(mol, pat):
    return bool(mol.HasSubstructMatch(pat)) if pat else False


def oatp1a2_lat1_glut1_uptake_heuristic(smiles=None, mol=None):
    """对单个 SMILES 计算 OATP1A2 / LAT1 / GLUT1 摄取启发式。

    返回 dict：
      {
        "available": bool,
        "oatp1a2": {features, plausibility, verdict, mandatory_assay},
        "lat1":    {features, plausibility, verdict, mandatory_assay},
        "glut1":   {features, plausibility, verdict, mandatory_assay},
      }
    plausibility ∈ {unknown, low, low_to_medium, medium}
    verdict       ∈ {unknown, uncertain, plausible_uptake, excluded_for_intact_glycoside}
    若 SMILES 不可解析：available=False，各 plausibility="unknown"，verdict="unknown"。
    """
    from rdkit import Chem
    from rdkit.Chem import rdMolDescriptors, Descriptors
    import rdkit.RDLogger

    rdkit.RDLogger.DisableLog("rdApp.*")

    if mol is None:
        mol = _mol_from(smiles)

    res = {
        "available": mol is not None,
        "oatp1a2": {
            "features": {},
            "plausibility": "unknown",
            "verdict": "unknown",
            "mandatory_assay": MANDATORY_ASSAY_OATP1A2,
        },
        "lat1": {
            "features": {},
            "plausibility": "unknown",
            "verdict": "unknown",
            "mandatory_assay": MANDATORY_ASSAY_LAT1,
        },
        "glut1": {
            "features": {},
            "plausibility": "unknown",
            "verdict": "unknown",
            "mandatory_assay": MANDATORY_ASSAY_GLUT1,
        },
    }
    if mol is None:
        return res

    p = _compiled()
    anionic = _has(mol, p["anionic"])
    carboxylate = _has(mol, p["carboxylate_broad"])
    basic_n = _has(mol, p["basic_n"])
    phenyl = _has(mol, p["phenyl"])
    aa_backbone = _has(mol, p["aa_backbone"])
    free_sugar = _has(mol, p["free_monosaccharide"])
    hba = int(rdMolDescriptors.CalcNumHBA(mol))
    mw = float(Descriptors.MolWt(mol))
    n_carbon = int(sum(1 for a in mol.GetAtoms() if a.GetAtomicNum() == 6))

    # ---- OATP1A2：大体积有机阴离子（电荷 + 疏水/多重 HBA） ----
    oatp_feats = {
        "anionic_group": bool(anionic),
        "hba": hba,
        "hba_ge3": hba >= 3,
        "aromatic_rings": int(rdMolDescriptors.CalcNumAromaticRings(mol)),
        "mw": round(mw, 1),
        "mw_ge300": mw >= 300,
    }
    if oatp_feats["anionic_group"] and oatp_feats["mw_ge300"]:
        oatp_plaus = "medium"
    elif oatp_feats["anionic_group"] and (
        oatp_feats["hba_ge3"] or oatp_feats["mw_ge300"]
    ):
        oatp_plaus = "low_to_medium"
    else:
        oatp_plaus = "low"
    res["oatp1a2"]["features"] = oatp_feats
    res["oatp1a2"]["plausibility"] = oatp_plaus
    res["oatp1a2"]["verdict"] = (
        "plausible_uptake" if oatp_plaus in ("medium", "low_to_medium") else "uncertain"
    )

    # ---- LAT1：大体积中性 L-氨基酸（α-氨基 + α-羧基 + 大疏水侧链） ----
    # 放宽到：含 α-氨基酸骨架，或（碱性 N + 羧基 + 大侧链）。L-立体专一性须实验确认。
    lat_aa_like = bool(aa_backbone) or (basic_n and carboxylate)
    lat_feats = {
        "aa_backbone": bool(aa_backbone),
        "basic_n_and_carboxylate": bool(basic_n and carboxylate),
        "aromatic_sidechain": bool(phenyl),
        "n_carbon": n_carbon,
        "hba": hba,
        "mw": round(mw, 1),
        # LAT1 偏好大体积中性氨基酸：芳香侧链，或碳数≥6（亮/异亮/缬/甲硫氨酸等支链也覆盖）
        "large_sidechain": bool(phenyl) or n_carbon >= 6,
    }
    if lat_aa_like and lat_feats["large_sidechain"]:
        lat_plaus = "medium"
    elif lat_aa_like:
        lat_plaus = "low_to_medium"
    else:
        lat_plaus = "low"
    # 过小的氨基酸（甘氨酸 C2 / 丙氨酸 C3）不是 LAT1 底物：强制降级为 uncertain
    if n_carbon < 4:
        lat_plaus = "low"
    res["lat1"]["features"] = lat_feats
    res["lat1"]["plausibility"] = lat_plaus
    res["lat1"]["verdict"] = (
        "plausible_uptake" if lat_plaus in ("medium", "low_to_medium") else "uncertain"
    )

    # ---- GLUT1：仅游离单糖（MW 阈值区分游离糖 vs 糖苷/结合态） ----
    glut_feats = {
        "free_monosaccharide": bool(free_sugar),
        "mw": round(mw, 1),
    }
    if free_sugar and mw < 220:
        # 游离单糖（如葡萄糖、甘露糖）：GLUT1 候选
        glut_plaus = "medium"
        glut_verdict = "plausible_uptake"
    elif free_sugar and mw >= 220:
        # 含糖但分子量偏大 → 极可能是糖苷/结合态 → 完整糖苷不是 GLUT1 底物
        glut_plaus = "low"
        glut_verdict = "excluded_for_intact_glycoside"
    else:
        glut_plaus = "low"
        glut_verdict = "uncertain"
    res["glut1"]["features"] = glut_feats
    res["glut1"]["plausibility"] = glut_plaus
    res["glut1"]["verdict"] = glut_verdict

    return res


def summarize(upt):
    """把摄取启发式结果压成一句中文（供 bbb.apply_dual_layer 写进 action）。"""
    if not upt or not upt.get("available"):
        return "（摄取启发式未运行：裁决记录未携带 SMILES，须人工补结构后再评估）"
    o = upt["oatp1a2"]
    l = upt["lat1"]
    g = upt["glut1"]
    parts = [
        f"OATP1A2（脑内皮摄取，正项候选）plausibility={o['plausibility']}（特征: 阴离子={o['features'].get('anionic_group')}, HBA={o['features'].get('hba')}, MW={o['features'].get('mw')}）",
        f"LAT1（脑内皮摄取，正项候选）plausibility={l['plausibility']}（特征: α-氨基酸骨架={l['features'].get('aa_backbone')}, 大疏水侧链={l['features'].get('large_sidechain')}）",
        f"GLUT1（脑内皮葡萄糖转运）plausibility={g['plausibility']}（verdict={g['verdict']}；完整糖苷非 GLUT1 底物，仅游离单糖/水解产物相关）",
    ]
    parts.append(
        "⚠️ 以上为共识药效团启发式，**非实测**；所有命中均须经对应过表达细胞摄取 ± 竞争抑制剂验证方可下结论，"
        "且不得进入 reliab 计票、不得改写原裁决。"
    )
    return "\n".join(parts)
