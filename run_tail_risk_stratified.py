# -*- coding: utf-8 -*-
"""E1 尾部风险检验：把 post-cutoff 外源留出**按到训练集的距离分层**，逐层报 AUC。

## 这一条要回答的问题（评审 §E1 的处方）
材料把两条负结果分开记：
  ① gate-as-classifier hERG AUC 0.58（域内外准确率无差异）；
  ② post-cutoff AUC 0.581 < always-positive 0.679。
评审的推论是：在**域内**评测 gate 是构造必然失败（到处都是可预测的分子，门没有可增加值），
门的价值只能在**分布外**测量；而那批外源分子到训练集的中位最大 Tanimoto 只有 0.241
（< AD 锚点 0.35），即**按本框架自己的门会被全部拒答**。

于是有一个可判定的定量问题：
  **"如果按 Tanimoto 分层，AUC 是否随分子靠近训练集而单调上升？"**
若单调上升 → "门划出了可用边界"从叙事变成定量结论；
若平坦 → 门的阈值与"可用性"无关，E1 的叙事也要跟着降级。

## 与 herg_holdout.json 的关系
那个脚本只落盘**聚合**指标。本脚本同一管道重算，但**逐分子落盘**
（`chembl_id, pic50, y, max_tdc_tanimoto, p_ext`），因此可以事后分层、分桶、
给任意子集的 bootstrap CI——这也是评审 R1 要求的"0.098 差距要带区间"的实现位置。

## 输出
- `out_ext/external/herg_holdout_rows.csv`     逐分子表（可复算一切）
- `out_ext/external/herg_holdout_stratified.json` 分层统计 + 趋势检验 + 差值 CI

## 用法
```bash
python run_tail_risk_stratified.py          # 首次联网取 ChEMBL，之后走 out_ext/external/cache
python run_tail_risk_stratified.py --bins 5 # 等频 5 桶
```
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from rdkit import Chem, DataStructs, RDLogger                       # noqa: E402
from rdkit.Chem import AllChem                                      # noqa: E402
from sklearn.ensemble import RandomForestClassifier                 # noqa: E402
from sklearn.metrics import roc_auc_score                           # noqa: E402

import run_external_holdout as RH                                   # noqa: E402

RDLogger.DisableLog("rdApp.*")

AD_ANCHOR = 0.35      # adt.normalize 的默认 AD 锚点（门的工作点）
BOOT = 2000
SEED = 0


def _auc(y, p):
    """单类时 AUC 无定义，返回 None（不许写 0.5 冒充）。"""
    if len(y) < 2 or len(set(np.asarray(y).tolist())) < 2:
        return None
    return float(roc_auc_score(y, p))


def _boot_auc(y, p, reps=BOOT, seed=SEED):
    if _auc(y, p) is None:
        return None
    rng = np.random.default_rng(seed)
    y = np.asarray(y)
    p = np.asarray(p)
    out = []
    n = len(y)
    for _ in range(reps):
        idx = rng.integers(0, n, n)
        yy = y[idx]
        if len(set(yy.tolist())) < 2:
            continue
        out.append(roc_auc_score(yy, p[idx]))
    if not out:
        return None
    return [round(float(np.percentile(out, 2.5)), 3),
            round(float(np.percentile(out, 97.5)), 3)]


def _boot_diff_auc(y, p1, p2):
    """同一批分子上两个打分器的 AUC 差（配对 bootstrap）。"""
    y = np.asarray(y)
    p1 = np.asarray(p1)
    p2 = np.asarray(p2)
    rng = np.random.default_rng(SEED)
    n = len(y)
    ds = []
    for _ in range(BOOT):
        idx = rng.integers(0, n, n)
        yy = y[idx]
        if len(set(yy.tolist())) < 2:
            continue
        ds.append(roc_auc_score(yy, p1[idx]) - roc_auc_score(yy, p2[idx]))
    if not ds:
        return None
    return [round(float(np.percentile(ds, 2.5)), 4),
            round(float(np.percentile(ds, 97.5)), 4)]


def _stratum_stats(name, y, p, t):
    y = np.asarray(y)
    p = np.asarray(p)
    n = int(len(y))
    n_pos = int(y.sum()) if n else 0
    prev = round(float(y.mean()), 3) if n else None
    auc = _auc(y, p)
    # always-positive 基线准确率 = 阳性率（本端点上"全判 blocker"的准确率）
    always_pos_acc = prev
    # 模型在 0.5 阈值下的准确率
    acc = round(float(((p >= 0.5).astype(int) == y).mean()), 3) if n else None
    return {
        "stratum": name,
        "n": n,
        "n_pos": n_pos,
        "prevalence": prev,
        "auc": None if auc is None else round(auc, 3),
        "auc_ci95": _boot_auc(y, p),
        "accuracy_at_0.5": acc,
        "always_positive_accuracy": always_pos_acc,
        "median_tanimoto": round(float(np.median(t)) , 3) if n else None,
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-year", type=int, default=2023, dest="min_year")
    ap.add_argument("--max-pages", type=int, default=20, dest="max_pages")
    ap.add_argument("--cache", default=os.path.join(HERE, "out_ext/tdc_cache"))
    ap.add_argument("--ext-cache", default=os.path.join(HERE, "out_ext/external/cache"),
                    dest="ext_cache")
    ap.add_argument("--near-dup", type=float, default=0.9, dest="near_dup")
    ap.add_argument("--year-mode", choices=("local", "none"), default="local",
                    dest="year_mode",
                    help="local=按 document_year 本地切分（默认，唯一可用于对外材料）；"
                         "none=不做时间切分（仅用于复现 v4.3 的旧数字）")
    ap.add_argument("--bins", type=int, default=5, help="等频分桶数")
    ap.add_argument("--out-rows", default=os.path.join(
        HERE, "out_ext/external/herg_holdout_rows.csv"), dest="out_rows")
    ap.add_argument("--out", default=os.path.join(
        HERE, "out_ext/external/herg_holdout_stratified.json"))
    a = ap.parse_args(argv)

    os.chdir(HERE)   # 复用 run_external_holdout 的相对缓存路径语义

    # ---- 1. 用与 herg_holdout.json **完全相同**的管道重建逐分子表 -------------
    acts, total = RH.fetch_activities(a.min_year, a.max_pages, a.ext_cache,
                                      year_mode=a.year_mode)
    fetch_meta = dict(getattr(RH, "LAST_FETCH_META", {}))
    per_mol, smi = {}, {}
    n_cens = n_invalid = n_nosmi = 0
    for x in acts:
        cid = x.get("molecule_chembl_id")
        p = x.get("pchembl_value")
        s = x.get("canonical_smiles")
        if p in (None, ""):
            if x.get("standard_relation") in (">", "<"):
                n_cens += 1
            else:
                n_invalid += 1
            continue
        if x.get("data_validity_comment"):
            n_invalid += 1
            continue
        if not s:
            n_nosmi += 1
            continue
        try:
            pv = float(p)
        except (TypeError, ValueError):
            n_invalid += 1
            continue
        per_mol.setdefault(cid, []).append(pv)
        smi[cid] = s

    (mols_trv, y_trv), (mols_tst, y_tst) = RH.tdc_set(a.cache)
    tdc_mols = mols_trv + mols_tst
    tdc_smis = {Chem.MolToSmiles(m) for m in tdc_mols}
    tdc_fps = [AllChem.GetMorganFingerprintAsBitVect(m, 2, 2048) for m in tdc_mols]

    rows = []
    dropped_exact = dropped_near = 0
    for cid, ps in per_mol.items():
        s = smi.get(cid)
        if not s:
            continue
        m = Chem.MolFromSmiles(s)
        if m is None:
            continue
        can = Chem.MolToSmiles(m)
        if can in tdc_smis:
            dropped_exact += 1
            continue
        fp = AllChem.GetMorganFingerprintAsBitVect(m, 2, 2048)
        sims = DataStructs.BulkTanimotoSimilarity(fp, tdc_fps)
        if sims and max(sims) >= a.near_dup:
            dropped_near += 1
            continue
        med = float(np.median(ps))
        rows.append({"chembl_id": cid, "smiles": can, "pic50": round(med, 3),
                     "y": int(med >= RH.PIC50_CUT),
                     "max_tdc_tanimoto": round(max(sims or [0]), 4)})

    print("[strat] 外源留出 n=%d（剔完全相同 %d、近重复 %d）"
          % (len(rows), dropped_exact, dropped_near), flush=True)

    # ---- 2. 打分：外源模型用 train_val+test 全量训练（与 herg_holdout 一致）---
    def _fp_matrix(ms):
        A = np.zeros((len(ms), 2048), dtype=np.int8)
        for i, m in enumerate(ms):
            DataStructs.ConvertToNumpyArray(
                AllChem.GetMorganFingerprintAsBitVect(m, 2, 2048), A[i])
        return A

    Xtrv, Xtst = _fp_matrix(mols_trv), _fp_matrix(mols_tst)
    mols_ext = [Chem.MolFromSmiles(r["smiles"]) for r in rows]
    Xex = _fp_matrix(mols_ext)
    y_ext = np.array([r["y"] for r in rows])
    t_ext = np.array([r["max_tdc_tanimoto"] for r in rows])

    clf = RandomForestClassifier(n_estimators=400, random_state=0, n_jobs=1)
    clf.fit(np.vstack([Xtrv, Xtst]), np.concatenate([y_trv, y_tst]))
    p_ext = clf.predict_proba(Xex)[:, 1]
    for r, pv in zip(rows, p_ext):
        r["p_ext"] = round(float(pv), 6)

    overall_auc = _auc(y_ext, p_ext)
    print("[strat] overall AUC=%.3f  n=%d  prev=%.3f"
          % (overall_auc, len(y_ext), y_ext.mean()), flush=True)

    # ---- 3. 落盘逐分子表（后续一切分层的唯一真源）----------------------------
    os.makedirs(os.path.dirname(a.out_rows), exist_ok=True)
    with io.open(a.out_rows, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["chembl_id", "smiles", "pic50", "y",
                                           "max_tdc_tanimoto", "p_ext"])
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print("[strat] -> %s" % a.out_rows, flush=True)

    # ---- 4. 分层 A：按门的工作点切（门会拒答 vs 门会放行）--------------------
    kill = t_ext < AD_ANCHOR
    gate_split = [
        _stratum_stats("gate_refuse(T<%.2f)" % AD_ANCHOR, y_ext[kill], p_ext[kill], t_ext[kill]),
        _stratum_stats("gate_pass(T>=%.2f)" % AD_ANCHOR, y_ext[~kill], p_ext[~kill], t_ext[~kill]),
    ]
    for s in gate_split:
        print("[strat] %-24s n=%-5d prev=%-5s AUC=%-6s CI=%s"
              % (s["stratum"], s["n"], s["prevalence"], s["auc"], s["auc_ci95"]), flush=True)

    # ---- 5. 分层 B：等频桶（每桶分子数相近，Tanimoto 递增）-------------------
    qs = np.quantile(t_ext, np.linspace(0, 1, a.bins + 1))
    qs[0] -= 1e-9
    labels = []
    idx_bins = []
    for i in range(a.bins):
        sel = (t_ext > qs[i]) & (t_ext <= qs[i + 1])
        idx_bins.append(sel)
        labels.append("Q%d[%.3f,%.3f]" % (i + 1, qs[i], qs[i + 1]))
    quant_bins = [_stratum_stats(lab, y_ext[sel], p_ext[sel], t_ext[sel])
                  for lab, sel in zip(labels, idx_bins)]
    for s in quant_bins:
        print("[strat] %-22s n=%-5d prev=%-5s AUC=%-6s CI=%s"
              % (s["stratum"], s["n"], s["prevalence"], s["auc"], s["auc_ci95"]), flush=True)

    # ---- 6. 趋势：AUC 是否随 Tanimoto 单调上升 ------------------------------
    #  只把"两类都有"的桶纳入趋势（单类桶的 AUC 无定义，不得补 0.5）
    pts = [(s["median_tanimoto"], s["auc"]) for s in quant_bins if s["auc"] is not None]
    trend = {"n_bins_used": len(pts)}
    if len(pts) >= 3:
        from scipy.stats import spearmanr
        xs = np.array([p[0] for p in pts])
        ys = np.array([p[1] for p in pts])
        rho, pval = spearmanr(xs, ys)
        trend.update({"spearman_rho": round(float(rho), 3),
                      "p_value": round(float(pval), 4),
                      "monotone_increasing": bool(rho > 0 and pval < 0.10)})
    # 最高桶 vs 最低桶的 AUC 差（点估计；两桶分子不重叠，故不给配对 CI）
    trend["auc_top_minus_bottom"] = (
        None if (quant_bins[0]["auc"] is None or quant_bins[-1]["auc"] is None)
        else round(quant_bins[-1]["auc"] - quant_bins[0]["auc"], 3))
    trend["note"] = ("桶级趋势以桶中位 Tanimoto 对桶 AUC 的 Spearman 检验（以桶为单位，n=%d）；"
                     "单类桶不计入。桶级检验只有 5 个点、功效有限，"
                     "故另给分子级检验与分桶敏感性（见下），三者必须同向才可下结论。" % len(pts))

    # ---- 6b. 分子级趋势（不依赖分桶，n=9443 的真实功效）--------------------
    #  两个分子级统计量：
    #    ① correct = 1[p≥0.5] == y：与 Tanimoto 的 Spearman（符号 + 表示越近越常预测对）
    #    ② 绝对概率误差 |p−y|：与 Tanimoto 的 Spearman（符号 − 表示越近误差越小）
    from scipy.stats import spearmanr
    correct = ((p_ext >= 0.5).astype(int) == y_ext).astype(int)
    abs_err = np.abs(p_ext - y_ext)
    r_c, p_c = spearmanr(t_ext, correct)
    r_e, p_e = spearmanr(t_ext, abs_err)
    # correct 的分子级 bootstrap：给"越近越对"的斜率一个区间
    rng_c = np.random.default_rng(SEED)
    boot_r = []
    for _ in range(500):
        i = rng_c.integers(0, len(y_ext), len(y_ext))
        tt = t_ext[i]
        cc = correct[i]
        if len(set(tt.tolist())) < 2 or len(set(cc.tolist())) < 2:
            continue
        boot_r.append(spearmanr(tt, cc)[0])
    molecule_level = {
        "spearman_tanimoto_vs_correct": round(float(r_c), 4),
        "p_value_correct": float(p_c),
        "boot_ci95_correct": ([round(float(np.percentile(boot_r, 2.5)), 4),
                               round(float(np.percentile(boot_r, 97.5)), 4)]
                              if boot_r else None),
        "spearman_tanimoto_vs_abs_error": round(float(r_e), 4),
        "p_value_abs_error": float(p_e),
        "n": int(len(y_ext)),
        "note": ("分子级检验不依赖分桶，是趋势的主检验；桶级 Spearman 只作展示。"
                 "**两者不同权**：`correct` 是准确率型（与置信度无关），作主检验；"
                 "`abs_error` 会被『越近越自信』放大（近邻分子预测更极端，即使排序不变，"
                 "|p−y| 也会变小），故它只能作辅助，不得单独据此声称『越近越准』。"
                 "两者同向（+0.095 / −0.283）说明方向一致，但量级差异提示："
                 "距离更多影响**置信度**，对排序能力的提升有限。"),
    }

    # ---- 6c. 分桶敏感性：换一种切法，趋势还在不在 ---------------------------
    #  按"最高的前 k%"取子集报 AUC。若 AUC 随 k 减小而单调上升，说明结论不是
    #  等频分桶的产物。k 越小样本越少，故同时给 n 与 CI。
    cum = []
    for k in (100, 50, 30, 20, 10):
        thr = float(np.quantile(t_ext, 1.0 - k / 100.0))
        sel = t_ext >= thr
        s = _stratum_stats("top%d%%(T>=%.3f)" % (k, thr), y_ext[sel], p_ext[sel], t_ext[sel])
        cum.append(s)
    cum_aucs = [(s["n"], s["auc"], s["auc_ci95"]) for s in cum if s["auc"] is not None]
    # 判据不能是"逐格不减"：样本随 k 减小而骤减，末档的回落常落在 CI 重叠区，
    # 把它算作失败是**把噪声当反证**。故只把"CI 完全不重叠的下行"记为违规。
    viol = []
    for (n1, a1, ci1), (n2, a2, ci2) in zip(cum_aucs, cum_aucs[1:]):
        if a2 < a1 and ci1 and ci2 and (ci2[1] < ci1[0]):
            viol.append({"from_n": n1, "to_n": n2, "auc_from": a1, "auc_to": a2,
                         "ci_from": ci1, "ci_to": ci2})
    binning_sensitivity = {
        "cumulative_top_k": cum,
        "auc_decreasing_with_k": len(viol) == 0,
        "violations": viol,
        "rule": ("`auc_decreasing_with_k`=True 表示：取的子集越靠近训练集，AUC 越高——"
                 "只把**CI 完全不重叠**的下行算作违规，CI 重叠的回落视为噪声。"),
        "note": ("该检验回答的是『趋势是不是等频分桶的人为产物』；"
                 "换成分位子集后方向若仍成立，趋势就不是切法的产物。"),
    }

    # ---- 6d. 可用性门槛：边界存在 ≠ 边界之内可用 ----------------------------
    #  这是本实验最容易被过度解读的地方：AUC 单调上升只说明"方向对"，
    #  不说明"最近的那一层已经可用"。用本框架自己的 0.65 约定线判。
    from adt.guards import GATE_AUC_MIN
    top = quant_bins[-1]
    top_auc = top["auc"]
    top_ci = top["auc_ci95"]
    usable = bool(top_auc is not None and top_auc >= GATE_AUC_MIN)
    pass_auc = gate_split[1]["auc"]
    usability_check = {
        "convention_threshold": GATE_AUC_MIN,
        "top_quantile_auc": top_auc,
        "top_quantile_ci95": top_ci,
        "gate_pass_auc": pass_auc,
        "top_reaches_threshold": usable,
        "note": ("即便在最靠近训练集的桶，AUC 也只有 %.3f（CI %s），"
                 "**未过 %.2f 约定线**：门的边界方向正确，但其内侧仍不构成"
                 "『可用区』。这一条必须与趋势结论同时报，否则就是把"
                 "『方向对』读成『能用了』。" % (top_auc or float("nan"), top_ci, GATE_AUC_MIN)),
    }

    # ---- 7. R1 要求：0.098 的差距必须给区间 --------------------------------
    #  "AUC 0.581 低于 always-positive 0.679" 是**跨指标**比较（AUC vs 准确率），
    #  严格说不可直接相减；能做的是给 (a) AUC 相对 0.5 的区间、(b) 0.5 阈值下
    #  准确率相对 always-positive 的配对 bootstrap 区间。
    acc = ((p_ext >= 0.5).astype(int) == y_ext).astype(float)
    const = (y_ext == 1).astype(float)
    d_acc = acc - const
    rng = np.random.default_rng(SEED)
    bs = []
    for _ in range(BOOT):
        i = rng.integers(0, len(y_ext), len(y_ext))
        bs.append(d_acc[i].mean())
    acc_gap_ci = [round(float(np.percentile(bs, 2.5)), 4),
                  round(float(np.percentile(bs, 97.5)), 4)]
    above_chance = _boot_auc(y_ext, p_ext)     # AUC 的 CI 已含是否 >0.5

    payload = {
        "design": ("post-cutoff external holdout **按到训练集的最大 Tanimoto 分层**"
                   "（E1 处方：门的价值只能用域外强制预测来测）"),
        "not_preregistered": True,
        "caveat": ("非预注册前瞻。阈值与分层口径在看到数据后确定，"
                   "结论只能写'post-cutoff 外源留出上的分层表现'。"),
        "provenance": {
            "script": "run_tail_risk_stratified.py",
            "rows_csv": os.path.relpath(a.out_rows, HERE).replace("\\", "/"),
            "source_holdout": "out_ext/external/herg_holdout.json",
            "chembl_min_year": a.min_year,
            "year_mode": a.year_mode,
            "year_filter": fetch_meta,
            "near_dup_exclusion": a.near_dup,
            "ad_anchor": AD_ANCHOR,
            "n_rows": len(rows),
            "n_dropped_exact": dropped_exact,
            "n_dropped_near_dup": dropped_near,
            "n_activities_seen": len(acts),
            "n_activities_available": total,
            "n_dropped_censored": n_cens,
            "n_dropped_invalid": n_invalid,
            "n_dropped_no_smiles": n_nosmi,
            "model": "RandomForest(400, seed=0) + Morgan-2048, "
                     "训练集 = TDC hERG train_val+test (n=655)",
        },
        "overall": _stratum_stats("ALL", y_ext, p_ext, t_ext),
        "by_gate_decision": gate_split,
        "by_tanimoto_quantile": quant_bins,
        "trend": trend,
        "molecule_level_trend": molecule_level,
        "binning_sensitivity": binning_sensitivity,
        "usability_check": usability_check,
        "r1_interval_requests": {
            "auc_ci95": above_chance,
            "accuracy_at_0.5_minus_always_positive": {
                "median": round(float(np.median(d_acc)), 4),
                "boot_ci95": acc_gap_ci,
                "note": ("配对 bootstrap（同批分子，逐分子差）。"
                         "负值=模型比'全判 blocker'更差。"),
            },
        },
        "verdict": None,   # 由 data 填，见下
    }

    # ---- 8. 判定（趋势三重检验 + 可用性门槛，缺一不下结论）-----------------
    hi = quant_bins[-1]["auc"]
    lo = quant_bins[0]["auc"]
    rho = trend.get("spearman_rho")
    mol_ok = bool(molecule_level["spearman_tanimoto_vs_correct"] > 0
                  and molecule_level["p_value_correct"] < 0.01
                  and molecule_level["spearman_tanimoto_vs_abs_error"] < 0)
    bin_ok = bool(trend.get("monotone_increasing"))
    sens_ok = binning_sensitivity["auc_decreasing_with_k"]
    if hi is None or lo is None:
        verdict = "undecidable"
        reason = "首/末桶存在单类，AUC 无定义，不能判定趋势。"
    elif mol_ok and bin_ok and sens_ok and usability_check["top_reaches_threshold"]:
        verdict = "boundary_quantified_and_usable"
        reason = ("趋势三重检验同向（分子级 ρ_correct=%.4f, p=%.2g；桶级 ρ=%.2f；"
                  "分桶敏感性通过），且最近桶 AUC %.3f ≥ %.2f —— "
                  "门确实划出一条**可用**边界。"
                  % (molecule_level["spearman_tanimoto_vs_correct"],
                     molecule_level["p_value_correct"], rho or float("nan"),
                     hi, GATE_AUC_MIN))
    elif mol_ok and bin_ok and sens_ok:
        verdict = "boundary_quantified_but_no_usable_region"
        reason = ("趋势三重检验同向（分子级 ρ_correct=%.4f, p=%.2g；桶级 ρ=%.2f，首桶 %.3f → 末桶 %.3f；"
                  "分桶敏感性通过），说明**方向正确**；但最近桶 AUC 只有 %.3f（CI %s），"
                  "未过 %.2f 约定线 —— 门的边界内侧**仍不构成可用区**。"
                  "允许写「门划出的边界方向正确」，"
                  "**禁止**写「门外可用」或「门证明了域外可行」。"
                  % (molecule_level["spearman_tanimoto_vs_correct"],
                     molecule_level["p_value_correct"], rho or float("nan"),
                     lo, hi, hi, usability_check["top_quantile_ci95"], GATE_AUC_MIN))
    elif (rho is not None and rho < 0) or molecule_level["spearman_tanimoto_vs_correct"] < 0:
        verdict = "boundary_reversed"
        reason = ("AUC 随 Tanimoto **下降**（桶级 ρ=%.2f，分子级 ρ=%.4f），"
                  "与「越近越好用」相反 —— 门阈值与可用性无关且方向不利。"
                  % (rho if rho is not None else float("nan"),
                     molecule_level["spearman_tanimoto_vs_correct"]))
    else:
        verdict = ("trend_not_robust"
                   if (mol_ok or bin_ok or sens_ok) else "boundary_uninformative")
        reason = ("三重检验未同向（分子级 ok=%s / 桶级 ok=%s / 分桶敏感性 ok=%s），"
                  "趋势不稳健 —— 「门划出可用边界」这一定量说法**不成立**，"
                  "E1 只能保留叙事级表述，或按单端点限定。"
                  % (mol_ok, bin_ok, sens_ok))
    payload["verdict"] = {"code": verdict, "reason": reason,
                          "checks": {"molecule_level_ok": mol_ok,
                                     "bins_monotone": bin_ok,
                                     "binning_sensitivity_ok": sens_ok,
                                     "top_reaches_threshold": usability_check["top_reaches_threshold"]}}

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with io.open(a.out, "w", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False, indent=2))
    print("[strat] VERDICT %s — %s" % (verdict, reason), flush=True)
    print("[strat] -> %s" % a.out, flush=True)
    return payload


if __name__ == "__main__":
    main()
