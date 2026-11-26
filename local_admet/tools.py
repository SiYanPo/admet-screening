# -*- coding: utf-8 -*-
"""Offline, RDKit-based approximations of the six SciMiner tools used by admet-pkpd.

This module is bundled into the **admet-screening** skill so the six tools can run
**without any API, key, credits, or network**.

Design contract (read before trusting any number):
  * Everything here is **rule / descriptor based**, computed locally with RDKit.
  * It is a *screening-level surrogate* for the SciMiner trained models — it is
    NOT the same model. Its numbers must be labelled as local proxies, never
    presented as SciMiner output.
  * Every result carries ``"method": "rule-based-local-proxy"`` and a
    ``"warning"`` string that downstream reports must keep.

Tool → local function
  ADMET Predictor       -> admet_predictor()
  AOMP                  -> aomp()
  OBA                   -> oba()
  Graph-pKa             -> graph_pka()
  DeepEsol              -> deep_esol()
  Molecular Descriptors -> molecular_descriptors()
"""
from __future__ import annotations

from rdkit import Chem
from rdkit.Chem import Crippen, Descriptors, QED
from rdkit.Chem import rdMolDescriptors as rdMD

METHOD = "rule-based-local-proxy"
WARNING = (
    "本地 RDKit 规则型近似（离线、无 API、无积分消耗）。"
    "这不是 SciMiner 的训练模型，数值仅供筛查排序，"
    "不得当作 SciMiner 模型输出，也不得用于对外定论。"
)

TOOL_NAMES = [
    "ADMET Predictor",
    "AOMP",
    "OBA",
    "Graph-pKa",
    "DeepEsol",
    "Molecular Descriptors",
]

TOOL_ALIASES = {
    "admet predictor": "ADMET Predictor",
    "admet": "ADMET Predictor",
    "predictor": "ADMET Predictor",
    "aomp": "AOMP",
    "oba": "OBA",
    "graph-pka": "Graph-pKa",
    "graph_pka": "Graph-pKa",
    "graphpka": "Graph-pKa",
    "pka": "Graph-pKa",
    "deepesol": "DeepEsol",
    "deep-esol": "DeepEsol",
    "esol": "DeepEsol",
    "molecular descriptors": "Molecular Descriptors",
    "descriptors": "Molecular Descriptors",
    "molecular_descriptors": "Molecular Descriptors",
}


# --------------------------------------------------------------------------- #
# core helpers
# --------------------------------------------------------------------------- #
def _parse(smiles_or_mol):
    if hasattr(smiles_or_mol, "GetNumAtoms"):
        mol = smiles_or_mol
    else:
        mol = Chem.MolFromSmiles(str(smiles_or_mol))
    if mol is None:
        raise ValueError("无法解析 SMILES: %r" % (smiles_or_mol,))
    return mol


def _canon(mol):
    return Chem.MolToSmiles(mol)


def _has_match(mol, smarts):
    patt = Chem.MolFromSmarts(smarts)
    return patt is not None and mol.HasSubstructMatch(patt)


def _matches(mol, smarts):
    patt = Chem.MolFromSmarts(smarts)
    if patt is None:
        return []
    return list(mol.GetSubstructMatches(patt))


def _has_basic_amine(mol):
    # 脂肪族碱性胺：非酰胺/磺酰胺、非亚胺/腈、非苯胺
    return _has_match(mol, "[NX3;!$(N[C,S,P]=O);!$(N=*);!$(N#*);!$(Nc)]")


def _has_carboxylic_acid(mol):
    return _has_match(mol, "[CX3](=O)[OX2H1]")


# --------------------------------------------------------------------------- #
# 1) Molecular Descriptors  (high fidelity: RDKit direct)
# --------------------------------------------------------------------------- #
def molecular_descriptors(smiles):
    mol = _parse(smiles)
    mw = Descriptors.MolWt(mol)
    clogp = Crippen.MolLogP(mol)
    tpsa = Descriptors.TPSA(mol)
    hbd = rdMD.CalcNumHBD(mol)
    hba = rdMD.CalcNumHBA(mol)
    rot = rdMD.CalcNumRotatableBonds(mol)
    rings = rdMD.CalcNumRings(mol)
    arom = rdMD.CalcNumAromaticRings(mol)
    lip_viol = int(sum([mw > 500, clogp > 5, hbd > 5, hba > 10]))
    veber = bool(rot <= 10 and tpsa <= 140)
    return {
        "tool": "Molecular Descriptors",
        "method": METHOD,
        "warning": WARNING,
        "fidelity": "high (RDKit 精确计算)",
        "smiles": str(smiles) if isinstance(smiles, str) else _canon(mol),
        "canonical_smiles": _canon(mol),
        "formula": rdMD.CalcMolFormula(mol),
        "MW": round(mw, 4),
        "exact_MW": round(Descriptors.ExactMolWt(mol), 4),
        "heavy_atoms": mol.GetNumHeavyAtoms(),
        "logP_crippen": round(clogp, 4),
        "TPSA": round(tpsa, 3),
        "HBD": int(hbd),
        "HBA": int(hba),
        "rotatable_bonds": int(rot),
        "rings": int(rings),
        "aromatic_rings": int(arom),
        "fraction_csp3": round(rdMD.CalcFractionCSP3(mol), 4),
        "molar_refractivity": round(Crippen.MolMR(mol), 4),
        "QED": round(QED.qed(mol), 4),
        "lipinski_violations": lip_viol,
        "lipinski_pass": bool(lip_viol <= 1),
        "veber_pass": veber,
    }


# --------------------------------------------------------------------------- #
# 2) DeepEsol  (approx: Delaney ESOL aqueous solubility)
# --------------------------------------------------------------------------- #
def deep_esol(smiles):
    mol = _parse(smiles)
    d = molecular_descriptors(mol)
    mw, clogp = d["MW"], d["logP_crippen"]
    rot = d["rotatable_bonds"]
    heavy = mol.GetNumHeavyAtoms() or 1
    arom_atoms = sum(1 for a in mol.GetAtoms() if a.GetIsAromatic())
    ap = arom_atoms / heavy
    # Delaney (2004) ESOL: logS = 0.16 - 0.63*clogP - 0.0062*MW + 0.066*RB - 0.74*AP
    logs = 0.16 - 0.63 * clogp - 0.0062 * mw + 0.066 * rot - 0.74 * ap
    s_mol = 10.0 ** logs
    mg_l = s_mol * mw * 1000.0
    dg_proxy = -1.363 * logs  # kcal/mol proxy, -RT ln10 * logS at 298 K (labelled as proxy)
    return {
        "tool": "DeepEsol",
        "method": METHOD,
        "warning": WARNING,
        "fidelity": "medium (ESOL 经验式替代 DeepEsol 的 ΔG_solv)",
        "smiles": str(smiles) if isinstance(smiles, str) else _canon(mol),
        "canonical_smiles": _canon(mol),
        "esol_logS_mol_per_L": round(logs, 4),
        "esol_solubility_mg_per_L": round(mg_l, 4),
        "solubility_class": ("high" if logs > -2 else ("medium" if logs > -4 else "low")),
        "dG_solv_proxy_kcal_per_mol": round(dg_proxy, 4),
        "note": ("DeepEsol 预测的是水合自由能 ΔG_solv；本地无法复刻其训练模型，"
                 "此处给出公认的 Delaney ESOL 溶解度与一个自由能代理量，两者不等价。"),
    }


# --------------------------------------------------------------------------- #
# 3) Graph-pKa  (approx: functional-group SMARTS + empirical pKa)
# --------------------------------------------------------------------------- #
_PKA_GROUPS = [
    dict(name="carboxylic acid", smarts="[CX3](=O)[OX2H1]", pka=4.2, kind="acid"),
    dict(name="tetrazole", smarts="c1nnnn1", pka=4.9, kind="acid"),
    dict(name="sulfonamide", smarts="[SX4](=O)(=O)[NX3]", pka=9.5, kind="acid"),
    dict(name="phenol", smarts="[OX2H]c", pka=10.0, kind="acid"),
    dict(name="aliphatic alcohol", smarts="[OX2H][CX4]", pka=16.0, kind="acid"),
    dict(name="imidazole", smarts="c1cnc[nH]1", pka=6.0, kind="base"),
    dict(name="pyridine", smarts="n1ccccc1", pka=5.2, kind="base"),
    dict(name="aromatic amine (aniline)", smarts="[NX3;H2,H1]c", pka=4.6, kind="base"),
    dict(name="primary aliphatic amine", smarts="[NX3;H2][CX4]", pka=10.6, kind="base"),
    dict(name="secondary aliphatic amine", smarts="[NX3;H1]([CX4])[CX4]", pka=10.8, kind="base"),
    dict(name="tertiary aliphatic amine", smarts="[NX3;H0]([CX4])([CX4])[CX4]", pka=10.0, kind="base"),
]


def _frac_ionized(pka, kind, ph=7.4):
    if kind == "acid":
        return 1.0 / (1.0 + 10.0 ** (pka - ph))
    return 1.0 / (1.0 + 10.0 ** (ph - pka))


def graph_pka(smiles, ph=7.4):
    mol = _parse(smiles)
    groups = []
    seen = set()
    for g in _PKA_GROUPS:
        for m in _matches(mol, g["smarts"]):
            atom = m[0]
            key = (g["name"], atom)
            if key in seen:
                continue
            seen.add(key)
            frac = _frac_ionized(g["pka"], g["kind"], ph)
            groups.append({
                "group": g["name"],
                "atom_index": int(atom),
                "kind": g["kind"],
                "pKa_estimate": g["pka"],
                "fraction_ionized_at_pH%.1f" % ph: round(frac, 4),
            })
    groups.sort(key=lambda x: x["pKa_estimate"])
    key_frac = "fraction_ionized_at_pH%.1f" % ph
    dom = "neutral" if not groups else (
        "ionized" if max(g[key_frac] for g in groups) > 0.5 else "mostly neutral")
    return {
        "tool": "Graph-pKa",
        "method": METHOD,
        "warning": WARNING,
        "fidelity": "low-medium (官能团经验 pKa，非 GNN 模型)",
        "smiles": str(smiles) if isinstance(smiles, str) else _canon(mol),
        "canonical_smiles": _canon(mol),
        "ionizable_groups": groups,
        "n_ionizable_groups": len(groups),
        "dominant_state_at_pH%.1f" % ph: dom,
        "note": ("基于常见可电离基团的文献 pKa 经验值，未考虑邻位电子效应/分子内氢键；"
                 "仅用于快速判断电离状态，精确 pKa 需实验或专用模型。"),
    }


# --------------------------------------------------------------------------- #
# 4) OBA  (approx: Martin bioavailability score + dose-solubility limit)
# --------------------------------------------------------------------------- #
def oba(smiles, dose_mg=None):
    mol = _parse(smiles)
    d = molecular_descriptors(mol)
    mw, clogp = d["MW"], d["logP_crippen"]
    tpsa, hbd, rot = d["TPSA"], d["HBD"], d["rotatable_bonds"]
    passes = (mw <= 500 and clogp <= 5)
    score = 0.55 if passes else 0.17
    if tpsa <= 140 and hbd <= 5 and rot <= 10 and mw <= 500 and clogp <= 5:
        cat, rng = "high", "~30-80%"
    elif tpsa <= 180 and hbd <= 6 and mw <= 700:
        cat, rng = "medium", "~10-30%"
    else:
        cat, rng = "low", "<10%"
    dose_note = None
    if dose_mg is not None:
        es = deep_esol(mol)
        need = float(dose_mg) / 0.25  # mg/L in 250 mL
        sol = es["esol_solubility_mg_per_L"]
        if sol > 0 and need > sol:
            cat = {"high": "medium", "medium": "low"}.get(cat, "low")
            dose_note = ("剂量 %.3g mg / 250 mL = %.1f mg/L > 预测溶解度 %.1f mg/L，"
                         "存在溶出/溶解限制，F 下调一档。" % (float(dose_mg), need, sol))
        else:
            dose_note = "剂量未超过预测溶解度，未见溶解限制。"
    return {
        "tool": "OBA",
        "method": METHOD,
        "warning": WARNING,
        "fidelity": "low (规则型 F 分类，非 OBA 训练模型)",
        "smiles": str(smiles) if isinstance(smiles, str) else _canon(mol),
        "canonical_smiles": _canon(mol),
        "dose_mg": dose_mg,
        "bioavailability_score_martin": score,
        "F_category": cat,
        "F_estimate_range": rng,
        "dose_solubility_note": dose_note,
        "note": ("F 分类基于 Veber/Lipinski 吸收友好度与 Martin(2005) 评分，"
                 "叠加剂量-溶解度粗判；不是 SciMiner OBA 的剂量依赖预测。"),
    }


# --------------------------------------------------------------------------- #
# 5) AOMP  (approx: AOX substrate structural alerts + SOM heuristics)
# --------------------------------------------------------------------------- #
_AOX_PATTERNS = [
    ("aldehyde", "[CX3H1](=O)", "high", "醛基是醛氧化酶(AOX)经典底物；SOM 在羰基碳"),
    ("phthalazine", "c1ccc2cnncc2c1", "high", "酞嗪类稠环含 aza-N，AOX 经典底物"),
    ("quinazoline", "c1ccc2ncncc2c1", "high", "喹唑啉类稠环，AOX 易氧化"),
    ("cinnoline", "c1ccc2ccnnc2c1", "high", "噌啉类稠环，AOX 敏感"),
    ("aza-arene", "[nX2]", "medium", "含芳环氮杂原子，可能经 AOX 氧化"),
]


def aomp(smiles):
    mol = _parse(smiles)
    hits = []
    som_atoms = set()
    rank = {"low": 0, "medium": 1, "high": 2}
    best = "low"
    for name, smarts, level, why in _AOX_PATTERNS:
        ms = _matches(mol, smarts)
        if not ms:
            continue
        hits.append({"motif": name, "n_matches": len(ms), "level": level, "rationale": why})
        if rank[level] > rank[best]:
            best = level
        for m in ms:
            for atom in m:
                som_atoms.add(int(atom))
    return {
        "tool": "AOMP",
        "method": METHOD,
        "warning": WARNING,
        "fidelity": "low (结构警报启发，非 AOX SOM 模型)",
        "smiles": str(smiles) if isinstance(smiles, str) else _canon(mol),
        "canonical_smiles": _canon(mol),
        "aox_substrate_likelihood": best,
        "matched_motifs": hits,
        "candidate_som_atoms": sorted(som_atoms),
        "note": ("以醛基与含 aza-N 稠环等 AOX 结构警报做底物可能性粗判；"
                 "SOM 原子为启发式候选，需实验(如 LC-MS 代谢物)确认。"),
    }


# --------------------------------------------------------------------------- #
# 6) ADMET Predictor  (approx: multi-endpoint rule / alert screening)
# --------------------------------------------------------------------------- #
_AMES_ALERTS = [
    ("nitro", ["[N+](=O)[O-]", "N(=O)=O"], "硝基"),
    ("aromatic_amine", ["[NX3;H2,H1]c"], "芳香伯/仲胺"),
    ("epoxide", ["[OX2r3]1[CX4r3][CX4r3]1"], "环氧化物"),
    ("azo", ["[NX2]=[NX2]"], "偶氮"),
    ("azide", ["[NX2-]=[NX2+]=[NX2-]", "N=[N+]=[N-]"], "叠氮"),
    ("n_nitroso", ["[NX3](=O)[NX3]"], "亚硝胺"),
    ("michael_acceptor", ["[CX3]=[CX3][CX3]=O"], "Michael 受体"),
]

_FEATURE_LETTERS = {
    "A": ["caco2_permeability", "human_intestinal_absorption", "pgp_substrate"],
    "D": ["bbb_penetration", "plasma_protein_binding", "volume_of_distribution_class"],
    "M": ["cyp2d6_inhibition", "cyp3a4_inhibition", "cyp2c9_inhibition"],
    "E": ["clearance_class", "half_life_class"],
    "T": ["herg_risk", "dili_risk", "ames_mutagenicity"],
}
_ALL_ENDPOINTS = [e for es in _FEATURE_LETTERS.values() for e in es]


def _ep(cat, prob, rule):
    return {"category": cat, "prob_proxy": prob, "rule": rule}


def _alert_hits(mol):
    hits = []
    for name, smarts_list, _label in _AMES_ALERTS:
        for sm in smarts_list:
            if _has_match(mol, sm):
                hits.append(name)
                break
    return hits


def _sel_features(features):
    if not features:
        return set(_ALL_ENDPOINTS)
    sel = set()
    for tok in [t.strip() for t in str(features).replace(";", ",").split(",") if t.strip()]:
        if len(tok) == 1 and tok.upper() in _FEATURE_LETTERS:
            sel.update(_FEATURE_LETTERS[tok.upper()])
        elif tok in _ALL_ENDPOINTS:
            sel.add(tok)
        else:
            low = tok.lower().replace(" ", "_")
            if low in _ALL_ENDPOINTS:
                sel.add(low)
    return sel or set(_ALL_ENDPOINTS)


def admet_predictor(smiles, features=None):
    mol = _parse(smiles)
    d = molecular_descriptors(mol)
    mw, clogp, tpsa = d["MW"], d["logP_crippen"], d["TPSA"]
    hbd, hba, rot = d["HBD"], d["HBA"], d["rotatable_bonds"]
    basic = _has_basic_amine(mol)
    acidic = _has_carboxylic_acid(mol)
    arom_rings = d["aromatic_rings"]

    eps = {}
    # Absorption
    if tpsa > 140 or hbd > 4 or mw > 600:
        eps["caco2_permeability"] = _ep("low", 0.25, "TPSA>140 或 HBD>4 或 MW>600")
    elif tpsa < 90 and hbd <= 2 and 0 <= clogp <= 4:
        eps["caco2_permeability"] = _ep("high", 0.75, "TPSA<90 且 HBD<=2 且 0<=logP<=4")
    else:
        eps["caco2_permeability"] = _ep("medium", 0.5, "介于高/低判据之间")

    if tpsa > 150 or hbd > 6 or mw > 700:
        eps["human_intestinal_absorption"] = _ep("low", 0.25, "TPSA>150 或 HBD>6 或 MW>700")
    elif tpsa <= 120 and hbd <= 5 and mw <= 500:
        eps["human_intestinal_absorption"] = _ep("high", 0.75, "TPSA<=120 且 HBD<=5 且 MW<=500")
    else:
        eps["human_intestinal_absorption"] = _ep("medium", 0.5, "中等吸收友好度")

    if mw > 400 and hba >= 8 and clogp > 2 and hbd < 3:
        eps["pgp_substrate"] = _ep("likely", 0.65, "MW>400 且 HBA>=8 且 logP>2 且 HBD<3")
    else:
        eps["pgp_substrate"] = _ep("unlikely", 0.35, "未满足 P-gp 底物通用特征")

    # Distribution
    if tpsa < 90 and hbd < 3 and mw < 450 and 1 < clogp < 4 and hba < 8:
        eps["bbb_penetration"] = _ep("high", 0.75, "TPSA<90 且 HBD<3 且 MW<450 且 1<logP<4")
    elif tpsa > 120 or mw > 500:
        eps["bbb_penetration"] = _ep("low", 0.25, "TPSA>120 或 MW>500")
    else:
        eps["bbb_penetration"] = _ep("medium", 0.5, "中等穿透潜力")

    if clogp > 4 or (clogp > 3 and acidic):
        eps["plasma_protein_binding"] = _ep("high", 0.75, "logP>4 或 (logP>3 且酸性)")
    elif clogp < 1:
        eps["plasma_protein_binding"] = _ep("low", 0.25, "logP<1")
    else:
        eps["plasma_protein_binding"] = _ep("medium", 0.5, "中等结合倾向")

    if clogp > 4 and mw > 400:
        eps["volume_of_distribution_class"] = _ep("large", 0.65, "logP>4 且 MW>400")
    elif clogp < 1:
        eps["volume_of_distribution_class"] = _ep("small", 0.35, "logP<1")
    else:
        eps["volume_of_distribution_class"] = _ep("moderate", 0.5, "中等分布")

    # Metabolism
    if basic and arom_rings >= 1 and clogp > 2:
        eps["cyp2d6_inhibition"] = _ep("high", 0.65, "碱性胺 + 芳环 + logP>2")
    else:
        eps["cyp2d6_inhibition"] = _ep("low", 0.3, "缺 CYP2D6 抑制通用特征")

    if mw > 400 and clogp > 3:
        eps["cyp3a4_inhibition"] = _ep("high", 0.65, "MW>400 且 logP>3")
    elif mw > 350 and clogp > 2.5:
        eps["cyp3a4_inhibition"] = _ep("medium", 0.5, "MW>350 且 logP>2.5")
    else:
        eps["cyp3a4_inhibition"] = _ep("low", 0.3, "缺 CYP3A4 抑制通用特征")

    if acidic and clogp > 2.5:
        eps["cyp2c9_inhibition"] = _ep("high", 0.6, "酸性 + logP>2.5")
    else:
        eps["cyp2c9_inhibition"] = _ep("low", 0.3, "缺 CYP2C9 抑制通用特征")

    # Excretion (very rough)
    if clogp > 4:
        eps["clearance_class"] = _ep("high", 0.55, "logP>4 倾向高清除（很粗）")
        eps["half_life_class"] = _ep("short", 0.55, "logP>4 倾向短 t1/2（很粗）")
    elif clogp < 1:
        eps["clearance_class"] = _ep("low", 0.45, "logP<1 倾向低清除（很粗）")
        eps["half_life_class"] = _ep("long", 0.45, "logP<1 倾向长 t1/2（很粗）")
    else:
        eps["clearance_class"] = _ep("medium", 0.5, "中等清除（很粗）")
        eps["half_life_class"] = _ep("medium", 0.5, "中等 t1/2（很粗）")

    # Toxicity
    if basic and clogp > 3 and tpsa < 90:
        eps["herg_risk"] = _ep("high", 0.7, "碱性胺 + logP>3 + TPSA<90")
    elif clogp < 1:
        eps["herg_risk"] = _ep("low", 0.25, "logP<1")
    else:
        eps["herg_risk"] = _ep("medium", 0.5, "介于高/低判据之间")

    ames_hits = _alert_hits(mol)
    if ames_hits:
        eps["ames_mutagenicity"] = _ep("alert_positive", 0.6, "结构警报: " + ", ".join(ames_hits))
    else:
        eps["ames_mutagenicity"] = _ep("no_alert", 0.2, "未命中已知致突变结构警报")

    if clogp > 3 and mw > 400 and (ames_hits or arom_rings >= 2):
        eps["dili_risk"] = _ep("high", 0.6, "logP>3 且 MW>400 且有警报/多芳环")
    elif clogp < 1:
        eps["dili_risk"] = _ep("low", 0.25, "logP<1")
    else:
        eps["dili_risk"] = _ep("medium", 0.45, "中等肝毒性风险")

    sel = _sel_features(features)
    filtered = {k: v for k, v in eps.items() if k in sel}
    return {
        "tool": "ADMET Predictor",
        "method": METHOD,
        "warning": WARNING,
        "fidelity": "low (多端点规则/警报筛查，非训练模型)",
        "smiles": str(smiles) if isinstance(smiles, str) else _canon(mol),
        "canonical_smiles": _canon(mol),
        "features_requested": features,
        "endpoints": filtered,
        "n_endpoints": len(filtered),
        "note": ("各端点 category / prob_proxy 由描述符阈值与结构警报生成，"
                 "prob_proxy 为名义值，不是校准概率；E 类(清除/t1/2)尤其粗糙，仅供排序。"),
    }


# --------------------------------------------------------------------------- #
# dispatch
# --------------------------------------------------------------------------- #
def normalize_tool(tool):
    key = str(tool).strip().lower()
    if key in TOOL_ALIASES:
        return TOOL_ALIASES[key]
    for name in TOOL_NAMES:
        if name.lower() == key:
            return name
    raise ValueError("未知工具 %r，可选：%s" % (tool, TOOL_NAMES))


def run_tool(tool, smiles, **kw):
    name = normalize_tool(tool)
    if name == "Molecular Descriptors":
        return molecular_descriptors(smiles)
    if name == "DeepEsol":
        return deep_esol(smiles)
    if name == "Graph-pKa":
        return graph_pka(smiles, ph=kw.get("ph", 7.4))
    if name == "OBA":
        return oba(smiles, dose_mg=kw.get("dose_mg"))
    if name == "AOMP":
        return aomp(smiles)
    if name == "ADMET Predictor":
        return admet_predictor(smiles, features=kw.get("features"))
    raise ValueError("未实现工具 %r" % (tool,))
