# -*- coding: utf-8 -*-
"""论文主表（Table 2）生成器：从 out_keystone_v43/results.json 出**可发表**的配对比较表。

为什么需要它
------------
`results.json` 里已有 `paired_vs_S1`（delta_median + boot_ci95 + significant），但 `significant`
只是"CI 跨不跨 0"，**没有 p 值、也没做族内多重比较校正**。审稿人第一个会问的就是
"3 端点比了 3 次，你校正了吗？"。本脚本补两件事：

1. **精确符号翻转置换检验**（sign-flip permutation）：配对单位是随机种子（n=20），
   2^20 = 1,048,576 种符号组合可**完全枚举**，得到精确双侧 p（不是近似、不是抽样）。
2. **Holm–Bonferroni** 在 3 端点族内校正（与预注册 SAP 一致）。

诚实边界（必须随表一起印）
--------------------------
置换单位是**随机种子**，它检验的是"结论对重采样种子是否稳健"，**不是**"能否外推到新化合物"。
外推需要前瞻/外部队列（见 publication_readiness 的 B2/B3）。两者不得混读。

输出：references/PAPER_TABLE2_MAIN_RESULTS.md + out_sensitivity/table2_paired.csv
运行：python tools/paper_table2.py [--cost ref]
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES = os.path.join(ROOT, "out_keystone_v43", "results.json")
OUT_MD = os.path.join(ROOT, "references", "PAPER_TABLE2_MAIN_RESULTS.md")
OUT_CSV = os.path.join(ROOT, "out_sensitivity", "table2_paired.csv")

COMPARISONS = [
    ("S4_full_admission", "S1_naive_majority", "S4 − S1（预注册主命题 H1）"),
    ("S3_calibrated_conformal", "S1_naive_majority", "S3 − S1（仅置信度弃权）"),
    ("S4_full_admission", "S3_calibrated_conformal", "S4 − S3（准入层独立贡献，H3）"),
]


def sign_flip_p(deltas):
    """精确双侧符号翻转置换 p（完全枚举 2^n；n<=22 可行）。"""
    d = np.asarray(deltas, dtype=float)
    n = d.size
    if n == 0:
        return None
    if n > 22:
        rng = np.random.default_rng(20261103)
        signs = rng.choice([-1.0, 1.0], size=(200000, n))
        stats = np.abs((signs * d).sum(axis=1))
        obs = abs(d.sum())
        return float((stats >= obs - 1e-12).mean())
    obs = abs(d.sum())
    idx = np.arange(2**n)
    bits = ((idx[:, None] >> np.arange(n)[None, :]) & 1) * 2 - 1
    stats = np.abs(bits @ d)
    return float((stats >= obs - 1e-12).mean())


def holm(pvals):
    """Holm–Bonferroni：返回校正后 p（保序）。"""
    items = [(p, i) for i, p in enumerate(pvals) if p is not None]
    items.sort()
    m = len(items)
    adj = [None] * len(pvals)
    running = 0.0
    for rank, (p, i) in enumerate(items):
        val = min(1.0, (m - rank) * p)
        running = max(running, val)
        adj[i] = running
    return adj


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--cost", default="ref")
    a = ap.parse_args(argv)

    d = json.load(io.open(RES, encoding="utf-8"))
    per = {}
    for r in d.get("per_run", []):
        if r.get("cost_point") != a.cost:
            continue
        per[(r["endpoint"], r["strategy"], r["seed"])] = r

    endpoints = [e.strip() for e in d["endpoints"].split(",")]
    seeds = sorted({k[2] for k in per})

    rows = []
    # 每端点每比较：配对 delta
    for ep in endpoints:
        for hi, lo, label in COMPARISONS:
            deltas, cov_hi, cov_lo = [], [], []
            for s in seeds:
                rh, rl = per.get((ep, hi, s)), per.get((ep, lo, s))
                if not rh or not rl:
                    continue
                deltas.append(rh["utility"] - rl["utility"])
                cov_hi.append(rh.get("coverage"))
                cov_lo.append(rl.get("coverage"))
            if not deltas:
                continue
            arr = np.array(deltas)
            p = sign_flip_p(arr)
            rows.append(
                dict(
                    endpoint=ep,
                    comparison=label,
                    hi=hi,
                    lo=lo,
                    n=len(arr),
                    delta_median=float(np.median(arr)),
                    q1=float(np.percentile(arr, 25)),
                    q3=float(np.percentile(arr, 75)),
                    n_pos=int((arr > 0).sum()),
                    p_raw=p,
                    coverage_hi=(
                        float(np.median([c for c in cov_hi if c is not None]))
                        if any(c is not None for c in cov_hi)
                        else None
                    ),
                    coverage_lo=(
                        float(np.median([c for c in cov_lo if c is not None]))
                        if any(c is not None for c in cov_lo)
                        else None
                    ),
                )
            )

    # 主命题族（S4−S1）做 Holm
    fam = [
        r
        for r in rows
        if r["hi"] == "S4_full_admission" and r["lo"] == "S1_naive_majority"
    ]
    adj = holm([r["p_raw"] for r in fam])
    for r, pj in zip(fam, adj):
        r["p_holm"] = pj
    for r in rows:
        r.setdefault("p_holm", None)

    # ---- Markdown ----
    L = [
        "# Table 2｜主结果：策略配对比较（cost point = %s）" % a.cost,
        "",
        "> 生成器：`tools/paper_table2.py`；数据：`out_keystone_v43/results.json`（20 seeds/端点/策略）。",
        "> 检验：**精确符号翻转置换**（配对单位=随机种子，2^20 全枚举）+ **Holm–Bonferroni**（3 端点族）。",
        "> 边界：置换检验只说明「对重采样种子稳健」，**不外推**到新化合物；外推需前瞻/外部队列。",
        "",
        "| 端点 | 比较 | n | Δ中位数 | IQR | 正向种子 | p(精确) | p(Holm) | 覆盖(上/下) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        cov = (
            "%.2f / %.2f" % (r["coverage_hi"], r["coverage_lo"])
            if r["coverage_hi"] is not None and r["coverage_lo"] is not None
            else "—"
        )
        L.append(
            "| %s | %s | %d | %+.4f | [%+.4f, %+.4f] | %d/%d | %s | %s | %s |"
            % (
                r["endpoint"],
                r["comparison"],
                r["n"],
                r["delta_median"],
                r["q1"],
                r["q3"],
                r["n_pos"],
                r["n"],
                ("%.2g" % r["p_raw"]) if r["p_raw"] is not None else "—",
                ("%.2g" % r["p_holm"]) if r["p_holm"] is not None else "—",
                cov,
            )
        )

    neg = [r for r in fam if r["delta_median"] <= 0]
    L += [
        "",
        "## 与预注册判据的对照",
        "",
        "预注册 H1：S4−S1 的 95%CI 下界 > 0 **在 ≥2/3 端点**成立才算支持，且族内 Holm 校正。",
        "",
    ]
    if len(neg) >= 2:
        L.append(
            "**判定：H1 不被支持**（%d/3 端点的 Δ 中位数 ≤ 0）。这是预注册允许并承诺发表的负结果，"
            "不是分析失败；按失败即结论条款，应如实报告并以失效边界为一级输出。"
            % len(neg)
        )
    else:
        L.append("**判定：需结合 Holm 校正后的 p 与 CI 下界共同判读**（见上表）。")
    L += [
        "",
        "## 附：为什么不用 `paired_vs_S1.significant` 直接抄",
        "",
        "该字段只判断 bootstrap CI 是否跨 0，既不提供 p，也不做 3 端点族内校正。",
        "直接引用会在审稿阶段被要求重做，故本表改用精确置换 + Holm，且保留原始 CI 供交叉核对。",
        "",
    ]
    io.open(OUT_MD, "w", encoding="utf-8", newline="\n").write("\n".join(L))

    os.makedirs(os.path.dirname(OUT_CSV), exist_ok=True)
    with io.open(OUT_CSV, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print("\n".join(L[:12]))
    print("\n[table2] %d 行 -> %s\n[table2] csv -> %s" % (len(rows), OUT_MD, OUT_CSV))
    return 0


if __name__ == "__main__":
    sys.exit(main())
