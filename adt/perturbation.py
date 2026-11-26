# -*- coding: utf-8 -*-
"""工作包 C：结构扰动的传播放大实验（Gate 0 的方法学必要性证明）。

外部评审意见（2026-10-29）：
  Gate 0 目前被表述为"我们做了标准化"，这是工程卫生，不是方法学命题。
  需要回答：在 ADMET 多源预测语境下，结构标准化误差的传播放大效应有多大？
  如果结构噪声导致的源间位移与真实源间分歧同量级，那么"源间分歧"里有一部分
  是结构噪声的伪影，而不是模型不确定性——这就把 Gate 0 从"做了"变成"必须做"。

本模块提供两条路径：
  1) descriptor 模式（离线、无需调用外部源）：
     对每个分子生成 去盐/中和/互变异构/立体翻转/去立体 变体，
     计算 RDKit 描述符位移。用于展示哪些描述符对结构噪声不敏感（E1 级），
     哪些会动——这直接支撑"换结构后哪些端点可复用"的判据。
  2) predictions 模式（需要先对变体跑源，产出长表）：
     输入 schema: compound_id, variant, endpoint, source, value, unit
     计算 Δ = |v_variant - v_original|，与原始多源之间的极差（source spread）
     比较，输出 ratio = Δ_median / spread_median，按端点分组。

诚实边界：
  - descriptor 模式只证明"结构噪声会移动描述符"，不等于"ADMET 预测会移动"；
    后者必须用 predictions 模式实测。
  - 立体翻转/去立体对无手性分子是 no-op，需显式标注 n_stereo_centers。
"""

import math
import os

IN_DOMAIN = {"predicted", "measured", "saturated"}


def _f(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _rdkit():
    from rdkit import Chem
    from rdkit.Chem import Descriptors, rdMolDescriptors
    from rdkit.Chem.MolStandardize import rdMolStandardize

    return Chem, Descriptors, rdMolDescriptors, rdMolStandardize


def _salt_remover():
    """RDKit 2026.09：SaltRemover 在 rdkit.Chem.SaltRemover，不在 rdMolStandardize。"""
    try:
        from rdkit.Chem import SaltRemover as SRmod

        return SRmod.SaltRemover()
    except Exception:
        from rdkit.Chem.MolStandardize import rdMolStandardize as MS

        return MS.SaltRemover()


def _stereo_count(mol):
    n_chiral = sum(
        1 for a in mol.GetAtoms() if a.GetChiralTag() not in (Chem_CHI_UNSPECIFIED,)
    )
    n_bond = sum(1 for b in mol.GetBonds() if b.GetStereo() not in (Chem_STEREO_NONE,))
    return n_chiral + n_bond


try:
    from rdkit import Chem as _Chem

    Chem_CHI_UNSPECIFIED = _Chem.ChiralType.CHI_UNSPECIFIED
    Chem_STEREO_NONE = _Chem.BondStereo.STEREONONE
except Exception:  # pragma: no cover
    Chem_CHI_UNSPECIFIED = None
    Chem_STEREO_NONE = None


def _largest_fragment(mol):
    from rdkit import Chem

    frags = Chem.GetMolFrags(mol, asMols=True, sanitizeFrags=True)
    if not frags:
        return mol
    return max(frags, key=lambda m: m.GetNumHeavyAtoms())


def variants(smiles):
    """生成结构变体；返回 dict(name -> (smiles, note))。失败返回空 dict。"""
    try:
        Chem, _D, _R, MS = _rdkit()
    except Exception as e:  # pragma: no cover
        return {"_error": ("", "rdkit 不可用：%s" % e)}
    mol = Chem.MolFromSmiles(smiles or "")
    if mol is None:
        return {"_error": ("", "SMILES 无法解析")}
    out = {}

    def _smi(m):
        try:
            return Chem.MolToSmiles(m, isomericSmiles=True)
        except Exception:
            return ""

    out["original"] = (_smi(mol), "输入结构")
    parent = _strip_salts(mol)

    # 去盐（取最大有机片段）
    try:
        out["desalted"] = (
            _smi(parent),
            "去盐" if _smi(parent) != _smi(mol) else "无盐（no-op）",
        )
    except Exception as e:
        out["desalted"] = ("", "去盐失败：%s" % e)

    # 中和（在去盐后的母体上做）
    try:
        neutral = MS.Uncharger().uncharge(parent)
        out["neutralized"] = (
            _smi(neutral),
            "电荷中和" if _smi(neutral) != _smi(parent) else "无电荷（no-op）",
        )
    except Exception as e:
        out["neutralized"] = ("", "中和失败：%s" % e)

    # 互变异构（canonical，在母体上做）
    try:
        before_st = _stereo_count(parent)
        te = MS.TautomerEnumerator()
        taut = te.Canonicalize(parent)
        s_taut = _smi(taut)
        # 必须看**SMILES 往返后**的立体数：Mol 对象可能保留已失效的 stereo 标记，
        # 但下游源拿到的是 SMILES——以 SMILES 为准才能抓到 C4 式丢失。
        rt = Chem.MolFromSmiles(s_taut) if s_taut else None
        after_st = _stereo_count(rt) if rt is not None else 0
        note = "互变异构规范化"
        # 2026-11-19（pred-shift 实跑暴露）：`Canonicalize` 返回的是**规范互变体**，
        # 分子本来就是规范形式时它原样返回 —— 于是 "tautomer" 变体在 6/6 个面板
        # 分子上与母体 SMILES 完全相同，整批变体成了 no-op，位移恒为 0。
        # 这里补一次"真的换一个互变体"：从枚举集合里取第一个与母体不同的。
        if s_taut == _smi(parent):
            try:
                for cand in te.Enumerate(parent):
                    cs = _smi(cand)
                    if cs and cs != _smi(parent):
                        s_taut = cs
                        note = "互变异构体（枚举取得，非规范态）"
                        rt2 = Chem.MolFromSmiles(cs)
                        after_st = _stereo_count(rt2) if rt2 is not None else after_st
                        break
            except Exception:
                pass
        if after_st < before_st:
            note += "（⚠ 丢失 %d 个立体标记，C4；predictions 模式不得直接用）" % (
                before_st - after_st
            )
        out["tautomer"] = (
            s_taut,
            note if s_taut != _smi(parent) else "无互变（no-op）",
        )
    except Exception as e:
        out["tautomer"] = ("", "互变异构失败：%s" % e)

    # 立体翻转（所有手性中心 + 双键 E/Z，在母体上做）
    try:
        flipped = Chem.Mol(parent)
        Chem.AssignStereochemistry(flipped, cleanIt=True, force=True)
        n_centers = 0
        for atom in flipped.GetAtoms():
            tag = atom.GetChiralTag()
            if tag == Chem.ChiralType.CHI_TETRAHEDRAL_CW:
                atom.SetChiralTag(Chem.ChiralType.CHI_TETRAHEDRAL_CCW)
                n_centers += 1
            elif tag == Chem.ChiralType.CHI_TETRAHEDRAL_CCW:
                atom.SetChiralTag(Chem.ChiralType.CHI_TETRAHEDRAL_CW)
                n_centers += 1
        for bond in flipped.GetBonds():
            st = bond.GetStereo()
            if st == Chem.BondStereo.STEREOE:
                bond.SetStereo(Chem.BondStereo.STEREOZ)
            elif st == Chem.BondStereo.STEREOZ:
                bond.SetStereo(Chem.BondStereo.STEREOE)
        out["stereo_flipped"] = (
            _smi(flipped),
            "翻转 %d 个立体中心" % n_centers if n_centers else "无立体中心（no-op）",
        )
    except Exception as e:
        out["stereo_flipped"] = ("", "立体翻转失败：%s" % e)

    # 去立体
    try:
        nostereo = Chem.Mol(parent)
        Chem.RemoveStereochemistry(nostereo)
        out["stereo_removed"] = (
            _smi(nostereo),
            "去立体" if _smi(nostereo) != _smi(mol) else "无立体（no-op）",
        )
    except Exception as e:
        out["stereo_removed"] = ("", "去立体失败：%s" % e)
    return out


def descriptor_vector(smiles):
    """RDKit 描述符向量（纯 2D，可复用级）。"""
    try:
        Chem, D, R, _MS = _rdkit()
    except Exception:
        return {}
    m = Chem.MolFromSmiles(smiles or "")
    if m is None:
        return {}
    return dict(
        mw=round(D.MolWt(m), 3),
        tpsa=round(D.TPSA(m), 3),
        clogp=round(D.MolLogP(m), 3),
        hbd=int(R.CalcNumHBD(m)),
        hba=int(R.CalcNumHBA(m)),
        rotb=int(R.CalcNumRotatableBonds(m)),
        rings=int(R.CalcNumRings(m)),
        fsp3=round(R.CalcFractionCSP3(m), 4),
        heavy=int(m.GetNumHeavyAtoms()),
    )


def _strip_salts(mol):
    """取最大有机片段（去掉 Na+/Cl- 等单原子反离子）。

    RDKit 的 SaltRemover 对"醋酸钠"会返回零原子分子（把整个盐当 salt 剥掉），
    因此这里不用它，改为按重原子数取最大片段（>=2 重原子优先）。
    """
    from rdkit import Chem

    frags = Chem.GetMolFrags(mol, asMols=True, sanitizeFrags=True)
    if len(frags) <= 1:
        return mol  # 单片段：直接用原 mol，避免 GetMolFrags 丢立体（C4 同类）
    if not frags:
        return mol
    organic = [f for f in frags if f.GetNumHeavyAtoms() >= 2]
    pool = organic or frags
    return max(pool, key=lambda m: m.GetNumHeavyAtoms())


def _rel_delta(orig, new):
    if orig is None or new is None:
        return None
    if abs(orig) < 1e-9:
        # 零基线：0->0 记为 0（invariant），0->非0 相对变化无定义（只报绝对 delta）
        return 0.0 if abs(new - orig) < 1e-12 else None
    return abs(new - orig) / abs(orig)


def analyze_descriptors(compounds, use_calc=False):
    """compounds: list[dict(compound_id, input_smiles|calc_smiles|smiles)]。

    默认用 **input_smiles（原始输入）**：扰动实验要量化"标准化本身"改变了什么。
    若用 calc_smiles（已去盐/中和/互变），变体会大量 no-op，实验失去意义。
    use_calc=True 时才用 calc_smiles（用于检查"标准化后是否还有残余噪声"）。
    """
    rows = []
    for c in compounds:
        cid = c.get("compound_id", "")
        if use_calc:
            smi = c.get("calc_smiles") or c.get("smiles") or c.get("input_smiles") or ""
        else:
            smi = c.get("input_smiles") or c.get("calc_smiles") or c.get("smiles") or ""
        vs = variants(smi)
        base = descriptor_vector(smi)
        if not base:
            rows.append(
                dict(
                    compound_id=cid,
                    variant="_error",
                    descriptor="",
                    value="",
                    delta="",
                    rel_delta="",
                    note="SMILES 解析失败",
                )
            )
            continue
        for vname, (vsmi, note) in vs.items():
            if vname.startswith("_"):
                rows.append(
                    dict(
                        compound_id=cid,
                        variant="error",
                        descriptor="",
                        value="",
                        delta="",
                        rel_delta="",
                        note=note,
                    )
                )
                continue
            dv = descriptor_vector(vsmi) if vsmi else {}
            if not dv:
                rows.append(
                    dict(
                        compound_id=cid,
                        variant=vname,
                        descriptor="",
                        value="",
                        delta="",
                        rel_delta="",
                        note=note or "变体为空，无法算描述符",
                    )
                )
                continue
            for k, v0 in base.items():
                v1 = dv.get(k)
                if v1 is None:
                    continue
                d = v1 - v0
                rows.append(
                    dict(
                        compound_id=cid,
                        variant=vname,
                        descriptor=k,
                        value=v1,
                        delta=round(d, 4),
                        rel_delta=(
                            ""
                            if _rel_delta(v0, v1) is None
                            else round(_rel_delta(v0, v1), 4)
                        ),
                        note=note,
                    )
                )
    # 聚合（只用非 original/no-op 行？保留全部，但 agg 排除 original）
    agg = {}
    for r in rows:
        k = r.get("descriptor")
        if not k or r.get("variant") in ("original", "error", "_error"):
            continue
        if r.get("rel_delta") in ("", None):
            continue
        agg.setdefault(k, []).append(float(r["rel_delta"]))
    out = []
    for k, vals in sorted(agg.items()):
        out.append(
            dict(
                descriptor=k,
                n=len(vals),
                mean_rel_delta=round(sum(vals) / len(vals), 4),
                max_rel_delta=round(max(vals), 4),
                invariant=("Y" if max(vals) < 1e-6 else "N"),
            )
        )
    return rows, out


def _median(vals):
    s = sorted(vals)
    n = len(s)
    if n == 0:
        return None
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def analyze_predictions(long_rows):
    """long_rows: dict(compound_id, variant, endpoint, source, value, unit)。

    计算每个 (cid, variant, endpoint, source) 相对 original 的 Δ；
    以及 original 条件下同一 (cid, endpoint) 跨源极差（source spread）。
    输出 per-endpoint: median_delta, median_spread, ratio, n。
    """
    table = {}
    for r in long_rows:
        v = _f(r.get("value"))
        if v is None:
            continue
        key = (
            r.get("compound_id", ""),
            r.get("variant", "original"),
            r.get("endpoint", ""),
            r.get("source", ""),
        )
        table[key] = v
    # 每个 (cid, ep, source) 的 original 值
    orig = {(c, ep, s): v for (c, var, ep, s), v in table.items() if var == "original"}
    # 跨源极差（original）
    spreads = {}
    for (c, ep, s), v in orig.items():
        spreads.setdefault((c, ep), []).append(v)
    spread_by_ep = {}
    for (c, ep), vals in spreads.items():
        if len(vals) >= 2:
            spread_by_ep.setdefault(ep, []).append(max(vals) - min(vals))
    # 变体位移
    delta_by_ep = {}
    for (c, var, ep, s), v in table.items():
        if var == "original":
            continue
        base = orig.get((c, ep, s))
        if base is None:
            continue
        delta_by_ep.setdefault(ep, []).append(abs(v - base))
    out = []
    for ep in sorted(set(delta_by_ep) | set(spread_by_ep)):
        ds = delta_by_ep.get(ep, [])
        ss = spread_by_ep.get(ep, [])
        md = _median(ds)
        ms = _median(ss)
        ratio = (md / ms) if (md is not None and ms not in (None, 0)) else None
        out.append(
            dict(
                endpoint=ep,
                n_delta=len(ds),
                n_spread=len(ss),
                median_delta=("" if md is None else round(md, 4)),
                median_spread=("" if ms is None else round(ms, 4)),
                ratio_structure_to_source=("" if ratio is None else round(ratio, 4)),
                interpretation=(
                    "结构噪声与源间分歧同量级：源间分歧含结构伪影"
                    if ratio is not None and ratio >= 0.5
                    else "结构噪声小于源间分歧" if ratio is not None else "数据不足"
                ),
            )
        )
    return out


def write(outdir, desc_rows, desc_agg, pred_agg=None):
    import csv
    import io

    p1 = os.path.join(outdir, "perturbation_descriptors.csv")
    cols1 = [
        "compound_id",
        "variant",
        "descriptor",
        "value",
        "delta",
        "rel_delta",
        "note",
    ]
    with io.open(p1, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols1, extrasaction="ignore")
        w.writeheader()
        w.writerows(desc_rows)
    p2 = os.path.join(outdir, "perturbation_summary.csv")
    cols2 = ["descriptor", "n", "mean_rel_delta", "max_rel_delta", "invariant"]
    with io.open(p2, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols2, extrasaction="ignore")
        w.writeheader()
        w.writerows(desc_agg)
    p3 = ""
    if pred_agg is not None:
        p3 = os.path.join(outdir, "perturbation_predictions.csv")
        cols3 = [
            "endpoint",
            "n_delta",
            "n_spread",
            "median_delta",
            "median_spread",
            "ratio_structure_to_source",
            "interpretation",
        ]
        with io.open(p3, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols3, extrasaction="ignore")
            w.writeheader()
            w.writerows(pred_agg)
    return p1, p2, p3
