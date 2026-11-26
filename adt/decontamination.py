# -*- coding: utf-8 -*-
"""工作包 F6：训练/测试污染去重（评审 C6 / P6 落地）。

评审核心批评：材料报"预测级训练污染 36.65% 且全部端点 MAE(污染) < MAE(干净)"，
但未给出**去污染后的两版对照**——只说"污染了"，没证明"去掉后结论是否还成立"。

本模块提供可复现的去污染机制：
  - remove_similar：贪心近重复剔除（Tanimoto ≥ 阈值 即视为同一化学个体，留一弃余）
  - decontamination_report：在 0.6 / 0.7 / 0.8 三档阈值上报告保留/剔除数，
    供"去污染敏感性"分析（结论是否对阈值选择稳健）

诚实边界：
  - 仅做结构近重复剔除，不做"同骨架/同专利族"语义去重（后者需额外知识库）。
  - 阈值 0.7 为评审推荐档；0.6 偏松、0.8 偏严，三档并列以暴露结论对阈值的敏感度。
  - 真实结论（去污染后 PASS 失败率 / stacking 性能两版对照）需真实前瞻数据闭环，
    本模块只提供机制与敏感性报告，不臆造数值。
"""

from __future__ import annotations

import math

try:
    from rdkit import Chem
    from rdkit.Chem import AllChem, DataStructs

    _HAS_RD = True
except Exception:  # pragma: no cover - rdkit 缺失时给出可读错误
    _HAS_RD = False


def _fp(smiles):
    m = Chem.MolFromSmiles(smiles)
    if m is None:
        return None
    return AllChem.GetMorganFingerprintAsBitVect(m, 2, nBits=2048)


def remove_similar(smiles_list, threshold=0.7, radius=2, n_bits=2048):
    """贪心近重复剔除：按顺序保留首个，凡与已保留集中任一分子的 Tanimoto ≥ threshold 即剔除。

    返回 dict：kept(列表) / dropped(列表 of (smiles, kept_partner, tanimoto))。
    顺序敏感（保留先出现者）；如需确定性，调用方先排序。
    """
    if not _HAS_RD:
        raise RuntimeError("RDKit 不可用，无法计算 Tanimoto 去污染")
    kept, dropped = [], []
    kept_fp = []
    for smi in smiles_list:
        fp = _fp(smi)
        if fp is None:
            dropped.append((smi, None, None))  # 无法解析
            continue
        hit = None
        best = 0.0
        for kfp, ksmi in zip(kept_fp, kept):
            t = DataStructs.TanimotoSimilarity(fp, kfp)
            if t > best:
                best, hit = t, ksmi
        if hit is not None and best >= threshold:
            dropped.append((smi, hit, round(best, 4)))
        else:
            kept.append(smi)
            kept_fp.append(fp)
    return dict(
        kept=kept,
        dropped=dropped,
        threshold=threshold,
        n_total=len(smiles_list),
        n_kept=len(kept),
        n_dropped=len(dropped),
    )


def decontamination_report(smiles_list, gears=(0.6, 0.7, 0.8)):
    """三档阈值敏感性（评审 P6 要求）：返回每档的保留/剔除数与剔除率。"""
    rows = []
    for g in gears:
        r = remove_similar(smiles_list, threshold=g)
        n = r["n_total"]
        rate = (r["n_dropped"] / float(n)) if n else 0.0
        rows.append(
            dict(
                threshold=g,
                n_total=n,
                n_kept=r["n_kept"],
                n_dropped=r["n_dropped"],
                drop_rate=round(rate, 4),
            )
        )
    return rows


def compare_two_version_metrics(
    clean_rows, contaminated_rows, metric_name="pass_fail_rate", lower_better=True
):
    """去污染两版对照（评审 C6 验收）：clean=去污染后，contaminated=含污染。

    仅做差异罗列 + 方向提示；真实数值由调用方以真实前瞻数据喂入，本函数不编造。
    """
    out = []
    for c in clean_rows:
        cont = contaminated_rows.get(c.get("endpoint") or c.get("key"))
        if cont is None:
            out.append(
                dict(
                    key=c.get("endpoint") or c.get("key"),
                    clean=c.get(metric_name),
                    contaminated=None,
                    delta=None,
                )
            )
            continue
        clean_v = c.get(metric_name)
        cont_v = cont.get(metric_name)
        delta = None
        if isinstance(clean_v, (int, float)) and isinstance(cont_v, (int, float)):
            delta = round(cont_v - clean_v, 4)
        out.append(
            dict(
                key=c.get("endpoint") or c.get("key"),
                clean=clean_v,
                contaminated=cont_v,
                delta=delta,
                direction=(
                    "污染使指标变差"
                    if (delta and ((delta > 0) == lower_better))
                    else "—"
                ),
            )
        )
    return out
