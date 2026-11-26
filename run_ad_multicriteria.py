# -*- coding: utf-8 -*-
"""多判据适用域（AD）判别力对比 —— 黑榜 3 后半。

被指控的问题：
  上一轮的"AD 门无判别力"只测了一种判据（`max Tanimoto to train ≥ 0.35`）。
  评审 R2-1 要的是"多判据 AD"，我当时的答辩是"结论只覆盖当前默认门"，
  等于承认结论的适用范围很窄。本轮把其余判据补齐并横向比较。

四种判据（都是"分数越高 = 越在域内"）：
  1. knn_tanimoto   : 到 fit 集的最大 Morgan-Tanimoto 相似度（当前默认门）
  2. conformal_p    : 归纳式 conformal p-value
                      alpha = 1 - maxTanimoto(query, fit)
                      p = (1 + #{i∈cal : alpha_i ≥ alpha_query}) / (n_cal + 1)
                      依据：Conformal prediction 的 p-value 本身可作为 AD 度量
                      （Norinder et al., J Pharm Sci 2020, 109:1519；
                        Chem Res Toxicol 2022 doi:10.1021/acs.chemrestox.2c00267
                        用 p1,p0<0.2 直接标 out-of-domain）
  3. desc_dist      : 9 维物化描述符 z 空间到最近 fit 分子的欧氏距离，取负号
  4. consensus      : 三者归一化秩的最小值（Hanser 式"逐级关卡"，
                      三步 applicability → reliability → decidability 的第一关）

评价方式（这才是评审要的问法）：
  把每种 AD 判据当作"该分子会不会被模型做对"的分类器，算 **AUC(correct ~ score)**。
  AUC 0.5 = 门没有信息量；≥0.65 才可称"有判别力"（与 gate_audit.GATE_AUC_FLOOR 同口径）。
  同时对"按该判据丢弃最差的 20%"计算域内/域外准确率差，给配对 bootstrap CI。

输出：out_ext/tdc/ad_multicriteria.json
"""
import argparse
import io
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rdkit import RDLogger                                        # noqa: E402
from sklearn.metrics import roc_auc_score                         # noqa: E402
from sklearn.neighbors import NearestNeighbors                    # noqa: E402
from sklearn.preprocessing import StandardScaler                  # noqa: E402

import run_keystone as KS                                        # noqa: E402

RDLogger.DisableLog("rdApp.*")

GATE_FLOOR = 0.65


def _auc(score, correct, rng, n_boot=1000):
    """AUC + bootstrap 95%CI；correct 单类别时返回 None。"""
    correct = np.asarray(correct, dtype=int)
    if correct.min() == correct.max():
        return None, None
    point = float(roc_auc_score(correct, score))
    n = len(correct)
    boot = []
    for _ in range(n_boot):
        idx = rng.integers(0, n, n)
        c = correct[idx]
        if c.min() == c.max():
            continue
        boot.append(roc_auc_score(c, np.asarray(score)[idx]))
    if not boot:
        return round(point, 3), None
    lo, hi = np.percentile(boot, [2.5, 97.5])
    return round(point, 3), [round(float(lo), 3), round(float(hi), 3)]


def _rank01(x):
    """转成 [0,1] 的分位秩（越高越在域内）。"""
    from scipy.stats import rankdata
    r = rankdata(x)
    return (r - 0.5) / len(x)


def _drop20(score, correct, frac=0.2):
    """按判据丢弃分数最低的 frac 部分，返回域内/域外准确率。"""
    n = len(score)
    k = max(1, int(round(frac * n)))
    order = np.argsort(score)
    out_idx = order[:k]
    in_idx = order[k:]
    acc_in = float(np.mean(correct[in_idx])) if len(in_idx) else None
    acc_out = float(np.mean(correct[out_idx])) if len(out_idx) else None
    return acc_in, acc_out, int(k)


def run_endpoint(ep, seeds, cache, rng):
    (mols_tr, y_tr), (mols_te, y_te) = KS.load_endpoint(ep, cache)
    rng_split = np.random.default_rng(0)
    idx = rng_split.permutation(len(mols_tr))
    cut = int(0.8 * len(mols_tr))
    fit_idx, cal_idx = idx[:cut], idx[cut:]
    mols_fit = [mols_tr[i] for i in fit_idx]
    y_fit = y_tr[fit_idx]
    mols_cal = [mols_tr[i] for i in cal_idx]

    per_seed = []
    for seed in seeds:
        models, sc = KS.fit_sources(mols_fit, y_fit, seed)
        p_te = KS.predict_sources(models, sc, mols_te)
        P = np.vstack([p_te[k] for k in p_te]).T
        mean_p = P.mean(axis=1)
        pred = (mean_p >= 0.5).astype(int)
        correct = (pred == y_te).astype(int)

        # 判据 1：kNN Tanimoto
        sim_te = KS.knn_ad(mols_fit, mols_te)
        sim_cal = KS.knn_ad(mols_fit, mols_cal)

        # 判据 2：conformal p-value（非一致性 = 1 - 到 fit 的最大相似度）
        alpha_cal = 1.0 - sim_cal
        alpha_te = 1.0 - sim_te
        pval = np.array([(1.0 + float(np.sum(alpha_cal >= a_))) / (len(alpha_cal) + 1.0)
                         for a_ in alpha_te])

        # 判据 3：描述符空间最近邻距离（取负）
        D_fit = np.array([KS.desc_vec(m) for m in mols_fit])
        z = StandardScaler().fit(D_fit)
        D_fit_z = z.transform(D_fit)
        D_te_z = z.transform(np.array([KS.desc_vec(m) for m in mols_te]))
        nn = NearestNeighbors(n_neighbors=1).fit(D_fit_z)
        dist, _ = nn.kneighbors(D_te_z)
        neg_dist = -dist[:, 0]

        # 判据 4：consensus（三者秩的最小值）
        cons = np.minimum(np.minimum(_rank01(sim_te), _rank01(pval)),
                          _rank01(neg_dist))

        crit = {"knn_tanimoto": sim_te, "conformal_p": pval,
                "desc_dist": neg_dist, "consensus": cons}
        row = {"seed": seed, "n_test": int(len(y_te)),
               "base_accuracy": round(float(np.mean(correct)), 3),
               "criteria": {}}
        for name, score in crit.items():
            auc, ci = _auc(score, correct, rng)
            acc_in, acc_out, k = _drop20(score, correct)
            row["criteria"][name] = {
                "auc": auc, "auc_ci95": ci,
                "acc_in_top80": round(acc_in, 3) if acc_in is not None else None,
                "acc_out_bottom20": round(acc_out, 3) if acc_out is not None else None,
                "gap_in_minus_out": (round(acc_in - acc_out, 3)
                                     if (acc_in is not None and acc_out is not None)
                                     else None),
                "n_dropped": k,
                "verdict": ("discriminative" if (auc or 0) >= GATE_FLOOR
                            else "uninformative"),
            }
        per_seed.append(row)

    agg = {}
    for name in ("knn_tanimoto", "conformal_p", "desc_dist", "consensus"):
        aucs = [r["criteria"][name]["auc"] for r in per_seed
                if r["criteria"][name]["auc"] is not None]
        gaps = [r["criteria"][name]["gap_in_minus_out"] for r in per_seed
                if r["criteria"][name]["gap_in_minus_out"] is not None]
        agg[name] = {
            "auc_median": round(float(np.median(aucs)), 3) if aucs else None,
            "auc_iqr": ([round(float(np.percentile(aucs, 25)), 3),
                         round(float(np.percentile(aucs, 75)), 3)] if aucs else None),
            "gap_median": round(float(np.median(gaps)), 3) if gaps else None,
            "n_seeds": len(aucs),
            "verdict": ("discriminative" if aucs and np.median(aucs) >= GATE_FLOOR
                        else "uninformative"),
        }
    return {"endpoint": ep, "n_train": len(mols_tr), "n_test": len(mols_te),
            "per_seed": per_seed, "summary": agg}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoints", default="hERG,DILI,BBB_Martins")
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--cache", default="out_ext/tdc_cache")
    a = ap.parse_args(argv)
    rng = np.random.default_rng(0)
    out = {}
    for ep in [x for x in a.endpoints.split(",") if x]:
        print("[ad-multi] %s ..." % ep, flush=True)
        out[ep] = run_endpoint(ep, list(range(a.seeds)), a.cache, rng)
        for k, v in out[ep]["summary"].items():
            print("   %-14s AUC=%-6s IQR=%-16s gap=%-7s %s"
                  % (k, v["auc_median"], v["auc_iqr"], v["gap_median"], v["verdict"]),
                  flush=True)
    os.makedirs("out_ext/tdc", exist_ok=True)
    p = "out_ext/tdc/ad_multicriteria.json"
    with io.open(p, "w", encoding="utf-8") as f:
        f.write(json.dumps({"seeds": a.seeds, "gate_floor": GATE_FLOOR,
                            "results": out}, ensure_ascii=False, indent=2))
    print("[ad-multi] -> %s" % p)


if __name__ == "__main__":
    main()
