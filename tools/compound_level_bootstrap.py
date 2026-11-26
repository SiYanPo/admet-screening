# -*- coding: utf-8 -*-
"""逐化合物 bootstrap 验证：把"种子级置换"补成"化合物级 CI"。

为什么做
--------
`PAPER_TABLE2_MAIN_RESULTS.md` 用的精确符号翻转置换，配对单位是 20 个随机种子——
审稿人的第一句就是"这只说明对重采样稳健，不能外推到新化合物"。
本模块用 `out_ext/tdc/gate_scores_*.csv`（逐分子 y_true / model_prob / sim / gate_passed）
做**化合物级**配对 bootstrap，回答一个 narrower 但可外推的问题：

  在同一批化合物上，"按适用性域准入后的预测"与"按相似度取同数量化合物"相比，
  AUC / 错误率差多少？区间是否跨 0？

这不是完整 S1→S4 决策效用（那个需要全部源与代价三元组），
而是 **AD 准入在化合物层的独立验证**；两者必须分开陈述，不得互相替代。

输出：references/COMPOUND_LEVEL_VALIDATION.md + out_sensitivity/compound_level.csv
运行：python tools/compound_level_bootstrap.py [--B 10000]
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys

import numpy as np
from scipy.stats import rankdata

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = "out_ext/tdc/gate_scores_%s.csv"
ENDPOINTS = ("hERG", "DILI", "BBB_Martins")
OUT_MD = os.path.join(ROOT, "references", "COMPOUND_LEVEL_VALIDATION.md")
OUT_CSV = os.path.join(ROOT, "out_sensitivity", "compound_level.csv")
SEED = 20261103


def auc(y, s):
    y = np.asarray(y, dtype=int)
    s = np.asarray(s, dtype=float)
    n1, n0 = int(y.sum()), int((1 - y).sum())
    if n1 == 0 or n0 == 0:
        return np.nan
    r = rankdata(s, method="average")
    return float((r[y == 1].sum() - n1 * (n1 + 1) / 2.0) / (n1 * n0))


def err_rate(y, pred):
    y = np.asarray(y, dtype=int)
    p = np.asarray(pred, dtype=int)
    return float(np.mean(y != p)) if len(y) else np.nan


def load(ep):
    p = os.path.join(ROOT, SRC % ep)
    rows = list(csv.DictReader(io.open(p, encoding="utf-8-sig")))
    y = np.array([int(float(r["y_true"])) for r in rows], dtype=int)
    s = np.array([float(r["model_prob"]) for r in rows], dtype=float)
    pred = np.array([int(float(r["model_pred"])) for r in rows], dtype=int)
    sim = np.array([float(r["sim"]) for r in rows], dtype=float)
    gate = np.array([int(float(r["gate_passed"])) for r in rows], dtype=int)
    return y, s, pred, sim, gate


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--B", type=int, default=10000)
    a = ap.parse_args(argv)
    rng = np.random.default_rng(SEED)
    rows = []

    for ep in ENDPOINTS:
        y, s, pred, sim, gate = load(ep)
        n = len(y)
        adm = np.where(gate == 1)[0]
        k = len(adm)

        # 两个同覆盖对照（k = 准入数）：
        #  (a) 按相似度 top-k —— 实测与 gate_passed 完全等价（同义反复，只作 sanity check）
        #  (b) 按模型概率 top-k —— 这才是 S3「置信度弃权」的对手，非同义反复
        matched_sim = np.argsort(-sim, kind="stable")[:k]
        matched_prob = np.argsort(-s, kind="stable")[:k]

        full_auc, adm_auc = auc(y, s), auc(y[adm], s[adm])
        matched_auc = auc(y[matched_prob], s[matched_prob])
        sim_auc = auc(y[matched_sim], s[matched_sim])
        full_err, adm_err = err_rate(y, pred), err_rate(y[adm], pred[adm])
        matched_err = err_rate(y[matched_prob], pred[matched_prob])

        d_auc, d_err = [], []
        full_aucs, adm_aucs = [], []
        for _ in range(a.B):
            idx = rng.integers(0, n, n)
            yy, ss, pp, mm = y[idx], s[idx], pred[idx], sim[idx]
            aa = idx[gate[idx] == 1]  # 重抽样后仍按 gate 判定
            bm = (
                np.argsort(-ss, kind="stable")[: len(aa)]
                if len(aa)
                else np.array([], dtype=int)
            )
            if len(aa) < 2 or len(bm) < 2:
                continue
            av, bv = auc(yy[aa], ss[aa]), auc(yy[bm], ss[bm])
            if not (np.isnan(av) or np.isnan(bv)):
                d_auc.append(av - bv)
                adm_aucs.append(av)
                full_aucs.append(auc(yy, ss))
            d_err.append(err_rate(yy[aa], pp[aa]) - err_rate(yy[bm], pp[bm]))

        def ci(v):
            return (
                (float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5)))
                if v
                else (np.nan, np.nan)
            )

        rows.append(
            dict(
                endpoint=ep,
                n=n,
                n_admitted=k,
                coverage=k / n,
                full_auc=full_auc,
                admitted_auc=adm_auc,
                matched_auc=matched_auc,
                sim_matched_auc=sim_auc,
                d_auc_vs_matched=adm_auc - matched_auc,
                d_auc_ci_lo=ci(d_auc)[0],
                d_auc_ci_hi=ci(d_auc)[1],
                n_boot=len(d_auc),
                full_err=full_err,
                admitted_err=adm_err,
                matched_err=matched_err,
                d_err_ci_lo=ci(d_err)[0],
                d_err_ci_hi=ci(d_err)[1],
            )
        )

    # ---- Markdown ----
    L = [
        "# 化合物级验证：AD 准入 vs 同覆盖匹配（bootstrap CI）",
        "",
        "> 生成器：`tools/compound_level_bootstrap.py`（B=%d, seed=%d）；"
        % (a.B, SEED),
        "> 数据：`out_ext/tdc/gate_scores_{endpoint}.csv`（逐分子，不是种子聚合）。",
        "> **边界**：本表只验证 **AD 准入**在化合物层的稳定性，不是完整 S1→S4 决策效用；",
        "> 两者量纲不同，禁止混写。",
        "",
        "| 端点 | n | 准入 n(覆盖) | 全集 AUC | 准入 AUC | 相似度top-k(同义反复) | 概率top-k(S3对手) | ΔAUC vs S3 | 95%CI | 判定 |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        verdict = (
            "准入优于匹配"
            if r["d_auc_ci_lo"] > 0
            else "准入劣于匹配" if r["d_auc_ci_hi"] < 0 else "CI 跨 0：不可判"
        )
        L.append(
            "| %s | %d | %d (%.2f) | %.3f | %.3f | %.3f | %.3f | %+.3f | [%+.3f, %+.3f] | %s |"
            % (
                r["endpoint"],
                r["n"],
                r["n_admitted"],
                r["coverage"],
                r["full_auc"],
                r["admitted_auc"],
                r["sim_matched_auc"],
                r["matched_auc"],
                r["d_auc_vs_matched"],
                r["d_auc_ci_lo"],
                r["d_auc_ci_hi"],
                verdict,
            )
        )
    L += [
        "",
        "## 怎么读",
        "",
        "1. **两个同覆盖对照**：按相似度 top-k 与 gate_passed **完全等价**（实测 AUC 逐位相同），",
        "   说明该 AD 门本质就是「取最相似的 k 个」——这是 sanity check，不是对照；",
        "   真正的对手是**按模型概率 top-k**（= S3 置信度弃权），下表 ΔAUC 与 CI 均对它。",
        "2. 置信区间来自**逐化合物**重采样（B=%d），配对重采样同时重算准入集与匹配集。"
        % a.B,
        "3. 若 ΔAUC 的 CI 跨 0，则 AD 准入在该端点上**没有**化合物级证据优势——",
        "   这与 Honest ADMET 的「弃权收益与泛化差距不相关」结论方向一致，必须如实报告。",
        "",
    ]
    io.open(OUT_MD, "w", encoding="utf-8", newline="\n").write("\n".join(L))
    os.makedirs(os.path.dirname(OUT_CSV), exist_ok=True)
    with io.open(OUT_CSV, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print("\n".join(L[8:14]))
    print(
        "\n[compound] -> %s ; %s"
        % (os.path.relpath(OUT_MD, ROOT), os.path.relpath(OUT_CSV, ROOT))
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
