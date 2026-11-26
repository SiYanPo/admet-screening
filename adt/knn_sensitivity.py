# -*- coding: utf-8 -*-
"""kNN/Tanimoto 阈值网格敏感性（2026-11-18）—— 关闭 RISK_COVERAGE_PROTOCOL §3 欠账。

## 为什么不是 SALib（方法学判断，写清楚）
协议写"SALib 全局敏感性"。但 SALib 的 Sobol 指数量化的是**多输入方差分解**；
本问题是**单个阈值旋钮**的一维扫描（0.35 饱和判别 / 0.7 污染筛查各自独立），
单输入做 Sobol = 退化成"方差占比 1"，不提供超出网格扫描的信息，且 SALib 未随
核心依赖分发（为 1 个退化指标引入新依赖不划算，见用户规则"简单优先"）。
故本模块做一维网格扫描 + 翻转/新增/丢失统计——这是单旋钮敏感性的正确工具；
若将来阈值变为 2+ 个联合旋钮，再补 SALib。

## 数据
用真实 `out_ext/tdc/gate_scores_{hERG,DILI,BBB_Martins}.csv`（逐分子 y_true/sim/gate_passed），
不合成数据。阈值定义"域内"= sim >= t；比较域内判定相对基线阈值的变化。

运行：python -m adt.knn_sensitivity --outdir out_sensitivity
"""

from __future__ import annotations

import csv
import io
import json
import os

from . import resref

GRIDS = {
    "saturation": {
        "threshold": 0.35,
        "grid": [0.25, 0.30, 0.35, 0.40, 0.45, 0.50],
        "meaning": "饱和判别阈值",
    },
    "contamination": {
        "threshold": 0.70,
        "grid": [0.60, 0.65, 0.70, 0.75, 0.80, 0.90],
        "meaning": "污染筛查阈值",
    },
}
ENDPOINTS = ("hERG", "DILI", "BBB_Martins")
SCORES = "out_ext/tdc/gate_scores_%s.csv"


def _load(endpoint, root):
    p = os.path.join(root, SCORES % endpoint)
    if not os.path.isfile(p):
        return []
    rows = []
    with io.open(p, encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            try:
                rows.append(
                    dict(
                        sim=float(r["sim"]),
                        y=int(float(r["y_true"])),
                        gate=int(float(r["gate_passed"])),
                    )
                )
            except (ValueError, KeyError, TypeError):
                continue
    return rows


def _verdict(rows, t):
    """把 sim>=t 作为域内子集，在该子集上算 gate 准确率（gate==y 的比例）。"""
    sub = [r for r in rows if r["sim"] >= t]
    if not sub:
        return dict(n=0, accuracy=None, n_pass=0, n_kill=0)
    correct = sum(1 for r in sub if r["gate"] == r["y"])
    return dict(
        n=len(sub),
        accuracy=round(correct / len(sub), 4),
        n_pass=sum(r["gate"] == 1 for r in sub),
        n_kill=sum(r["gate"] == 0 for r in sub),
    )


def analyze(root="."):
    out = {
        "schema": "adt-knn-sensitivity/1.0",
        "method": "1D grid sweep (single knob)",
        "reason_not_salib": "single threshold knob -> Sobol degenerates; grid sweep is correct tool",
        "grids": GRIDS,
        "by_endpoint": {},
    }
    for ep in ENDPOINTS:
        rows = _load(ep, root)
        if not rows:
            out["by_endpoint"][ep] = {"error": "no scores file"}
            continue
        per = {}
        for gname, gspec in GRIDS.items():
            base_t = gspec["threshold"]
            base = _verdict(rows, base_t)
            variants = []
            for t in gspec["grid"]:
                v = _verdict(rows, t)
                v["threshold"] = t
                v["n_new_decided"] = (
                    max(0, v["n"] - base["n"]) if v["accuracy"] is not None else 0
                )
                v["n_lost_decided"] = (
                    max(0, base["n"] - v["n"]) if v["accuracy"] is not None else 0
                )
                v["acc_delta_vs_base"] = (
                    round(v["accuracy"] - base["accuracy"], 4)
                    if v["accuracy"] is not None and base["accuracy"] is not None
                    else None
                )
                variants.append(v)
            accs = [
                v["acc_delta_vs_base"]
                for v in variants
                if v["acc_delta_vs_base"] is not None
            ]
            per[gname] = dict(
                base_threshold=base_t,
                base=base,
                variants=variants,
                max_abs_acc_delta=round(max((abs(a) for a in accs), default=0.0), 4),
                verdict=(
                    "threshold_critical"
                    if (accs and max(abs(a) for a in accs) > 0.10)
                    else "stable_under_grid"
                ),
            )
        out["by_endpoint"][ep] = per
    return out


def selftest():
    """用合成的最小数据验证：阈值升高 -> 域内样本单调不增。"""
    rows = [
        dict(sim=s, y=i % 2, gate=i % 2)
        for i, s in enumerate([0.1, 0.3, 0.5, 0.7, 0.9])
    ]
    ns = [_verdict(rows, t)["n"] for t in [0.2, 0.4, 0.6, 0.8]]
    ok = all(a >= b for a, b in zip(ns, ns[1:]))
    return ok, ns


def main(argv=None):
    import argparse

    ap = argparse.ArgumentParser(prog="knn-sensitivity")
    ap.add_argument("--outdir", default="out_sensitivity")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        ok, ns = selftest()
        print(
            "[knn-sensitivity] selftest %s n_by_threshold=%s"
            % ("PASS" if ok else "FAIL", ns)
        )
        return 0 if ok else 4
    rep = analyze()
    os.makedirs(a.outdir, exist_ok=True)
    p = os.path.join(a.outdir, "knn_threshold_sensitivity.json")
    with io.open(p, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(rep, ensure_ascii=False, indent=2) + "\n")
    print("[knn-sensitivity] -> %s" % p)
    for ep, per in rep["by_endpoint"].items():
        for gn, g in per.items():
            if "verdict" in g:
                print(
                    "  %-12s %-14s max|Δacc|=%s  %s"
                    % (ep, gn, g["max_abs_acc_delta"], g["verdict"])
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
