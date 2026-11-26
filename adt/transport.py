# -*- coding: utf-8 -*-
"""转运体先验层（v2.5.0）——**决策清单，不是预测模型**。

为什么存在：本类（咖啡酰糖苷）TPSA 175–195，被动跨膜通量极低，若观察到吸收
几乎必然是转运体介导。但**没有任何计算源能给肠侧转运体的 Km/Vmax**：

  ADMETlab 3.0  只有 5 个转运体，全是肝/胆侧（OATP1B1/1B3/BCRP/BSEP/MRP1）
  ADMET-AI      只有 Pgp（抑制剂数据集，不是底物）
  vNN            Pgp 抑制剂/底物，本类 14/14 NoPrediction

所以本模块的产物是三件事，**没有一件是"预测值"**：
  1. 按化学型给出"最可能被哪个转运体识别"的先验（hypothesis，证据级别明写）；
  2. 给出对应的**实验处方**（细胞系、底物浓度、抑制剂、判据）；
  3. 明确声明：这些先验**不得**进 reliab 计票、不得当数值使用。

实测回填后，用 `domain_flag=measured` + `provenance_url` 写入长表，
端点见 references/transporter_priors.yaml 的 backfill_endpoints
（role=reference 已在规则表登记）。
"""

import io
import os

import yaml

_HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PRIORS = os.path.join(
    os.path.dirname(_HERE), "references", "transporter_priors.yaml"
)


def load_priors(path=None):
    p = path or DEFAULT_PRIORS
    if not os.path.exists(p):
        return dict(chemotypes=[], data_availability={}, backfill_endpoints=[])
    with io.open(p, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _rdkit():
    from rdkit import Chem, RDLogger
    from rdkit.Chem import Descriptors

    RDLogger.DisableLog("rdApp.*")
    return Chem, Descriptors


# 吡喃糖环（通用，不限定 D/L 与端基构型）
_PYRANOSE = "[CX4;R]1[OX2;R][CX4;R][CX4;R][CX4;R][CX4;R]1"
# 芳环-O-端基碳（端基碳同时连芳氧与环氧）→ "糖基接在芳环上"
_ARYL_GLYCOSIDE = "[c][OX2][CX4;R]([OX2])"


def moiety_flags(smiles):
    """判定苷元/糖苷与糖基连接位置（Peng 2023 的构效前提）。

    返回 dict：
      has_pyranose      是否含吡喃糖环
      sugar_on_aryl     糖基是否接在芳环碳上（C3-O-糖 / C7-O-糖 型）
      sugar_on_aliphatic 有糖但接在脂肪碳上（1-O-糖基甘油、糖酯 型）
      note              给人看的判定依据
    """
    Chem, _ = _rdkit()
    m = Chem.MolFromSmiles(smiles) if smiles else None
    if m is None:
        return dict(
            has_pyranose=False,
            sugar_on_aryl=False,
            sugar_on_aliphatic=False,
            note="SMILES 解析失败",
        )
    pyr = m.HasSubstructMatch(Chem.MolFromSmarts(_PYRANOSE))
    aryl = m.HasSubstructMatch(Chem.MolFromSmarts(_ARYL_GLYCOSIDE))
    if not pyr:
        note = "无吡喃糖（苷元/非糖苷）"
    elif aryl:
        note = "糖基接在芳环碳上（C3/C7-O-糖型）"
    else:
        note = "糖基接在脂肪碳上（非芳环氧苷）"
    return dict(
        has_pyranose=pyr,
        sugar_on_aryl=aryl,
        sugar_on_aliphatic=bool(pyr and not aryl),
        note=note,
    )


_ORDER = ["low", "low_to_medium", "medium", "high"]


def _shift(level, steps):
    """档位平移（steps<0 下调）。未知档位原样返回。"""
    if level not in _ORDER:
        return level
    i = max(0, min(len(_ORDER) - 1, _ORDER.index(level) + steps))
    return _ORDER[i]


def apply_moiety_rules(base_level, transporter, moi, rules):
    """按 moiety_rules 调整档位。返回 dict(level, base, reason, evidence, tag)。

    tag 取值：
      ""            未调整
      direct       有直接实测构效证据的调整（Peng 2023 的 C3/C7 糖基化）
      extrapolated 由该证据外推的调整（糖基在脂肪碳上）
    设计纪律：**只下调、只作用于指定转运体**，并永远回传 base 值——
    任何档位变化都必须可追溯，禁止静默改写先验。
    """
    res = dict(level=base_level, base=base_level, reason="", evidence="", tag="")
    if not moi:
        return res
    for r in rules or []:
        if (r.get("transporter") or "").upper() != (transporter or "").upper():
            continue
        when = r.get("when")
        if when == "sugar_on_aryl" and not moi.get("sugar_on_aryl"):
            continue
        if when == "sugar_not_on_aryl" and not moi.get("sugar_on_aliphatic"):
            continue
        eff = r.get("effect")
        lvl = res["level"]
        if eff == "downgrade_one_rank":
            res["level"], res["tag"] = _shift(lvl, -1), "direct"
        elif eff == "downgrade_one_rank_weak":
            # 半档：medium -> low_to_medium；其余档位不动（避免过度外推）
            if lvl == "medium":
                res["level"], res["tag"] = "low_to_medium", "extrapolated"
            else:
                res["tag"] = "extrapolated"
        elif eff == "note_only":
            continue
        else:
            continue
        res["reason"] = (
            r.get("id", "") + "：" + (r.get("detail") or "").strip().split("\n")[0][:80]
        )
        res["evidence"] = r.get("evidence", "")
    return res


def chemotype_flags(smiles, priors):
    """返回命中的化学型 id 列表（SMARTS 或 tpsa 规则）。"""
    Chem, Desc = _rdkit()
    m = Chem.MolFromSmiles(smiles) if smiles else None
    if m is None:
        return [], None
    tpsa = Desc.TPSA(m)
    hits = []
    for ct in priors.get("chemotypes") or []:
        rule = (ct.get("rule") or "").strip().lower()
        if rule.startswith("tpsa>"):
            try:
                if tpsa > float(rule.split(">")[1]):
                    hits.append(ct["id"])
            except (ValueError, IndexError):
                pass
            continue
        sma = ct.get("smarts")
        if not sma:
            continue
        q = Chem.MolFromSmarts(sma)
        if q is not None and m.HasSubstructMatch(q):
            hits.append(ct["id"])
    return hits, tpsa


def assess(compound_id, smiles, priors):
    """单个分子 -> 行列表（每行 = 一个化学型 × 一个候选转运体）。

    v3.0.0：每行额外给出 `plausibility_base`（未调整）与 `adjust_reason`——
    档位可能被 moiety_rules 下调（Peng 2023），调整必须可追溯。
    """
    hits, tpsa = chemotype_flags(smiles, priors)
    mo = moiety_flags(smiles)
    rules = priors.get("moiety_rules") or []
    by_id = {ct["id"]: ct for ct in (priors.get("chemotypes") or [])}
    out = []
    for cid_ct in hits:
        ct = by_id.get(cid_ct, {})
        for tr in ct.get("transporters") or []:
            base = tr.get("plausibility", "")
            adj = apply_moiety_rules(base, tr.get("name", ""), mo, rules)
            ev = tr.get("evidence_level", "")
            if adj["tag"] == "direct":
                ev = "measured_literature_SAR"
            elif adj["tag"] == "extrapolated":
                ev = "extrapolated_from_literature_SAR"
            out.append(
                dict(
                    compound_id=compound_id,
                    chemotype=cid_ct,
                    chemotype_label=ct.get("label", ""),
                    tpsa=round(tpsa, 1) if tpsa is not None else "",
                    moiety=mo.get("note", ""),
                    transporter=tr.get("name", ""),
                    role=tr.get("role", ""),
                    plausibility_base=base,
                    plausibility=adj["level"],
                    adjust_reason=adj["reason"],
                    adjust_evidence=adj["evidence"],
                    rationale=(tr.get("rationale") or "").strip().replace("\n", " "),
                    evidence_level=ev,
                    recommended_assay=tr.get("assay", ""),
                    predictive_value="none（先验，不是预测值；不得进 reliab 计票）",
                )
            )
    return out, hits, tpsa


_RANK = {"unknown": 0, "low": 1, "low_to_medium": 2, "medium": 3, "high": 4}


def summarize(rows):
    """按转运体汇总：**按分子去重**（同一分子可能命中多个化学型而重复列出同一转运体）。

    每个（转运体, 分子）取最高的 plausibility，避免"行数当分子数"的误读。
    """
    agg = {}
    for r in rows:
        d = agg.setdefault(
            r["transporter"],
            dict(transporter=r["transporter"], role=r["role"], mols={}, assays=set()),
        )
        prev = d["mols"].get(r["compound_id"])
        if prev is None or _RANK.get(r["plausibility"], 0) > _RANK.get(prev, 0):
            d["mols"][r["compound_id"]] = r["plausibility"]
        if r["recommended_assay"]:
            d["assays"].add(r["recommended_assay"])
    out = []
    for d in agg.values():
        d["n"] = len(d["mols"])
        d["n_medium_up"] = sum(1 for v in d["mols"].values() if _RANK.get(v, 0) >= 2)
        d["assays"] = sorted(d["assays"])
        d.pop("mols")
        out.append(d)
    return sorted(out, key=lambda x: (-x["n_medium_up"], -x["n"]))
