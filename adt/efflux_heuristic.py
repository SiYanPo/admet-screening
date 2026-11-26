# -*- coding: utf-8 -*-
"""P-gp / BCRP 外排通道启发式（B2 闭环动作，2026-11-03）。

⚠️ 这是**启发式结构代理（heuristic）**，不是预测模型，也不是实测。
  - P-gp 底物识别本质依赖 HBA 间的空间距离（Seelig 1998 的 HBA 距离模型），
    SMARTS 只能近似，距离信息全部丢失；
  - BCRP 识别面更扁平、与 P-gp 部分重叠，SMARTS 更粗。
  本模块所有输出都**不得**进 reliab 计票、不得改 verdict / confidence；
  只用于在 BBB = UNDETERMINED / PASSTHRU 时把"外排通道"从纯叙事升级为
  "有结构依据的可验证假设"，并**强制绑定** Caco-2 ± verapamil / elacridar 验证后才能下结论。

特征来源（共识药效团，文献级，非本包自创）：
  - Seelig A. Eur J Biochem 1998;250(1):252-261 —— HBA 距离模型（≥2 个 HBA 中心）。
  - Penzotti JE et al. 2002 / Crivori P et al. 2006 —— ADMET Predictor P-gp 药效团：
    2 个疏水芳香中心 + 2 个 HBA + 1 个正电荷中心。

人类可读副本与参考文献见 references/transporter_priors.yaml 的 efflux_heuristics 块。
"""

from __future__ import annotations

# ---- 结构特征（可执行源；yaml 仅作审计副本） ----
# 可被质子化的 N（叔/仲胺、吡啶 N、季铵前体）：P-gp 底物常见正电荷中心。
# 注意排除酰胺 N（NC=O）与 N-氧化物（N=O）。
BASIC_N_SMARTS = "[N;!$(NC=O);!$(N=O)]"
# 至少一个芳香环（扁平识别面的粗代理）。
PHENYL_SMARTS = "c1ccccc1"

MANDATORY_ASSAY_PGP = (
    "Caco-2 双向 + verapamil 100 µM（P-gp 特异性抑制剂；外排比 ER 前后差 ≥2× 判 P-gp 底物）；"
    "同时 + elacridar 2 µM（P-gp/BCRP 共抑制剂）以分离 BCRP 贡献。"
    "若任一抑制剂使净通量反转或 ER 下降 ≥2×，则确认外排底物，"
    "有效脑暴露须按『被动渗透 × 外排净效应』重算，不得沿用原 BBB 端点值。"
)
MANDATORY_ASSAY_BCRP = (
    "Caco-2 双向 + elacridar 2 µM（BCRP/P-gp 共抑制剂）；"
    "确认须配合 KO 细胞或特异性探针底物（如 pheophorbide A / sulforhodamine B）。"
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

    basic = Chem.MolFromSmarts(BASIC_N_SMARTS)
    phenyl = Chem.MolFromSmarts(PHENYL_SMARTS)
    return basic, phenyl


def pgp_bcrp_efflux_heuristic(smiles=None, mol=None):
    """对单个 SMILES 计算 P-gp / BCRP 外排启发式。

    返回 dict：
      {
        "available": bool,            # SMILES 是否可解析
        "pgp":  {features, plausibility, verdict, mandatory_assay},
        "bcrp": {features, plausibility, verdict, mandatory_assay},
      }
    plausibility ∈ {unknown, low, low_to_medium, medium}
    verdict       ∈ {unknown, uncertain, plausible_efflux}
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
        "pgp": {
            "features": {},
            "plausibility": "unknown",
            "verdict": "unknown",
            "mandatory_assay": MANDATORY_ASSAY_PGP,
        },
        "bcrp": {
            "features": {},
            "plausibility": "unknown",
            "verdict": "unknown",
            "mandatory_assay": MANDATORY_ASSAY_BCRP,
        },
    }
    if mol is None:
        return res

    basic_pat, phenyl_pat = _compiled()
    basic_n = mol.HasSubstructMatch(basic_pat) if basic_pat else False
    phenyl = mol.HasSubstructMatch(phenyl_pat) if phenyl_pat else False
    hba = int(rdMolDescriptors.CalcNumHBA(mol))
    n_arom = int(rdMolDescriptors.CalcNumAromaticRings(mol))
    mw = float(Descriptors.MolWt(mol))

    # ---- P-gp 评分（共识药效团近似） ----
    pgp_feats = {
        "basic_center": bool(basic_n),
        "hba": hba,
        "hba_ge2": hba >= 2,
        "hba_ge4": hba >= 4,
        "aromatic_rings": n_arom,
        "aromatic_ring_ge2": n_arom >= 2,
        "mw": round(mw, 1),
        "mw_ge400": mw >= 400,
    }
    if (
        pgp_feats["hba_ge2"]
        and pgp_feats["aromatic_ring_ge2"]
        and (pgp_feats["basic_center"] or pgp_feats["hba_ge4"])
    ):
        pgp_plaus = "medium"
    elif pgp_feats["hba_ge2"] and pgp_feats["mw_ge400"]:
        pgp_plaus = "low_to_medium"
    else:
        pgp_plaus = "low"
    res["pgp"]["features"] = pgp_feats
    res["pgp"]["plausibility"] = pgp_plaus
    res["pgp"]["verdict"] = (
        "plausible_efflux" if pgp_plaus in ("medium", "low_to_medium") else "uncertain"
    )

    # ---- BCRP 评分（更保守；扁平芳香 + 可电离基团 + 多 HBA） ----
    bcrp_feats = {
        "planar_aromatic": bool(phenyl),
        "ionizable_basic_n": bool(basic_n),
        "hba": hba,
        "hba_ge3": hba >= 3,
    }
    if (
        bcrp_feats["hba_ge3"]
        and bcrp_feats["planar_aromatic"]
        and bcrp_feats["ionizable_basic_n"]
    ):
        bcrp_plaus = "low_to_medium"
    else:
        bcrp_plaus = "low"
    res["bcrp"]["features"] = bcrp_feats
    res["bcrp"]["plausibility"] = bcrp_plaus
    res["bcrp"]["verdict"] = (
        "plausible_efflux" if bcrp_plaus == "low_to_medium" else "uncertain"
    )

    return res


def summarize(eff):
    """把启发式结果压成一句中文（供 bbb.apply_dual_layer 写进 action）。"""
    if not eff or not eff.get("available"):
        return "（外排启发式未运行：裁决记录未携带 SMILES，须人工补结构后再评估）"
    p = eff["pgp"]
    b = eff["bcrp"]
    parts = [
        f"P-gp 外排 plausibility={p['plausibility']}（特征: HBA={p['features'].get('hba')}, "
        f"芳香环={p['features'].get('aromatic_rings')}, 可质子化N={p['features'].get('basic_center')}, "
        f"MW={p['features'].get('mw')}）"
    ]
    parts.append(f"BCRP 外排 plausibility={b['plausibility']}")
    parts.append(
        "⚠️ 以上为共识药效团启发式，**非实测**；所有命中均须经下方 Caco-2 ± verapamil/elacridar 验证方可下结论，"
        "且不得进入 reliab 计票、不得改写原裁决。"
    )
    return "\n".join(parts)
