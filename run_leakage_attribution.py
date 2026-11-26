# -*- coding: utf-8 -*-
"""源间误差相关（ρ）的归因：是"方法相似"还是"近邻记忆"？

## 被指控的问题（评审 F3 / L3-3）
三个外部模型（ADMET-AI / ADMETlab3 / ProTox3）的训练集清单都不公开，
所以"三源误差高度相关"到底来自**方法相似**还是**数据重叠**，在结构上无法拆解。
我上一轮只能承认这一点。

## 本脚本做的事：把"无法拆解"降为"可部分拆解"
不依赖外部训练集，改用**内部可测量的代理**：
近邻泄漏。若三源共享误差的出现频率随"测试分子到 fit 集的最大 Tanimoto"
单调上升，则共享误差至少部分由**记忆/近重复**驱动，而非方法相似；
若在高相似与低相似两个子集里 r_error 相近，则共享误差是**内生的**（同源训练 +
方法相似），与近邻泄漏无关。

依据方法：Lo-Hi（NeurIPS 2023 Datasets & Benchmarks）用
"测试分子在训练集中存在 Tanimoto > 0.4 邻居的比例"量化基准泄漏，
并报告 MoleculeNet HIV 56%、TDC CYP2D6_Veith 78%。
本脚本用同一口径，同时给出 ≥0.4 与 ≥0.7 两档。

## 输出
out_ext/tdc/leakage_attribution.json

## 边界（必须一起引用）
- 这只解释**本框架三源**的相关性（它们确实共享 fit 集），
  **不能**直接解释外部三家的相关性；
- `ad_sim` 是"到 fit 集"的最大相似度，不是"到 test 集"，
  所以它度量的是"模型是否见过近邻"，不是"测试集内部重复"。
"""
import argparse
import io
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

NEAR_DUP = 0.4        # Lo-Hi 口径
VERY_CLOSE = 0.7      # 更严格的近重复
WEAK = (0, 1, 2)      # 三源（第 4 列是强基线，不参与）


def _r(a, b):
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    if a.std() < 1e-12 or b.std() < 1e-12:
        return None
    return float(np.corrcoef(a, b)[0, 1])


def group_stats(P, y, mask, label):
    """P: (n, 3) 源概率；y: (n,) 标签；mask: 布尔选择。"""
    if mask.sum() < 20:
        return {"label": label, "n": int(mask.sum()), "insufficient": True}
    Pg, yg = P[mask], y[mask]
    E = Pg - yg[:, None]                      # e_i = p_i - y（与 C6 同口径）
    pairs = {}
    for i in range(E.shape[1]):
        for j in range(i + 1, E.shape[1]):
            pairs["%d-%d" % (i, j)] = (round(_r(E[:, i], E[:, j]), 3)
                                       if _r(E[:, i], E[:, j]) is not None else None)
    rerr = [v for v in pairs.values() if v is not None]
    # 三源同时判错（同向：全判阳性但真阴性 / 全判阴性但真阳性）
    pred = (Pg >= 0.5).astype(int)
    all_same = np.all(pred == pred[:, [0]], axis=1)
    all_wrong = all_same & (pred[:, 0] != yg)
    return {"label": label, "n": int(mask.sum()),
            "r_error_pairs": pairs,
            "r_error_median": round(float(np.median(rerr)), 3) if rerr else None,
            "all_agree_rate": round(float(all_same.mean()), 3),
            "all_agree_and_wrong_rate": round(float(all_wrong.mean()), 3)}


def run(ep, seeds_idx=None):
    p = "out_blacklist/export_%s.npz" % ep
    if not os.path.exists(p):
        return {"endpoint": ep, "error": "missing %s（先跑 run_evidence_export.py）" % p}
    z = np.load(p, allow_pickle=True)
    y = z["y"].astype(int)
    ad = z["ad_sim"].astype(float)
    P_raw = z["P_raw"]                        # (n_seeds, n_te, K)
    n_seed, n_te, K = P_raw.shape
    seeds = list(range(n_seed)) if seeds_idx is None else seeds_idx

    near = ad >= NEAR_DUP
    close = ad >= VERY_CLOSE
    novel = ad < NEAR_DUP

    per_seed = []
    for s in seeds:
        P = P_raw[s][:, list(WEAK)]
        per_seed.append({
            "seed": s,
            "novel": group_stats(P, y, novel, "novel(T<0.4)"),
            "near_dup": group_stats(P, y, near, "near_dup(T>=0.4)"),
            "close": group_stats(P, y, close, "close(T>=0.7)"),
        })

    def _agg(key, field):
        vals = [r[key].get(field) for r in per_seed
                if not r[key].get("insufficient") and r[key].get(field) is not None]
        return (round(float(np.median(vals)), 3) if vals else None)

    summary = {}
    for key in ("novel", "near_dup", "close"):
        summary[key] = {
            "n_median": int(np.median([r[key]["n"] for r in per_seed])),
            "r_error_median": _agg(key, "r_error_median"),
            "all_agree_rate": _agg(key, "all_agree_rate"),
            "all_agree_and_wrong_rate": _agg(key, "all_agree_and_wrong_rate"),
        }
    delta = None
    if (summary["novel"]["r_error_median"] is not None
            and summary["near_dup"]["r_error_median"] is not None):
        delta = round(summary["near_dup"]["r_error_median"]
                      - summary["novel"]["r_error_median"], 3)

    return {
        "endpoint": ep,
        "n_test": int(n_te), "n_seeds": len(seeds),
        "thresholds": {"near_dup": NEAR_DUP, "very_close": VERY_CLOSE},
        "leakage_rate": {
            "frac_ge_0.4": round(float(near.mean()), 3),
            "frac_ge_0.7": round(float(close.mean()), 3),
            "median_max_train_tanimoto": round(float(np.median(ad)), 3),
        },
        "by_group": summary,
        "r_error_near_dup_minus_novel": delta,
        "interpretation": (
            "若 delta 明显 > 0（近重复组相关更高），说明共享误差部分由记忆驱动，"
            "ρ 的归因偏向'数据重叠'；若 delta ≈ 0，说明共享误差与近邻泄漏无关，"
            "更可能来自同源训练与方法相似。本条只覆盖本框架三源，不覆盖外部三家。"
        ),
        "per_seed": per_seed,
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoints", default="hERG,DILI,BBB_Martins")
    a = ap.parse_args(argv)
    out = {}
    for ep in [x for x in a.endpoints.split(",") if x]:
        print("[leak] %s ..." % ep, flush=True)
        out[ep] = run(ep)
        if "error" in out[ep]:
            print("   ", out[ep]["error"], flush=True)
            continue
        lk = out[ep]["leakage_rate"]
        bg = out[ep]["by_group"]
        print("   近邻泄漏率：T>=0.4 %.3f / T>=0.7 %.3f / 中位最大相似度 %.3f"
              % (lk["frac_ge_0.4"], lk["frac_ge_0.7"],
                 lk["median_max_train_tanimoto"]), flush=True)
        print("   r_error：novel=%s (n=%d)  near_dup=%s (n=%d)  close=%s (n=%d)  Δ=%s"
              % (bg["novel"]["r_error_median"], bg["novel"]["n_median"],
                 bg["near_dup"]["r_error_median"], bg["near_dup"]["n_median"],
                 bg["close"]["r_error_median"], bg["close"]["n_median"],
                 out[ep]["r_error_near_dup_minus_novel"]), flush=True)
    os.makedirs("out_ext/tdc", exist_ok=True)
    p = "out_ext/tdc/leakage_attribution.json"
    with io.open(p, "w", encoding="utf-8") as f:
        f.write(json.dumps(out, ensure_ascii=False, indent=2))
    print("[leak] -> %s" % p)


if __name__ == "__main__":
    main()
