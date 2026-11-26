# -*- coding: utf-8 -*-
"""H2 代价扫描表 + 两张投稿级图（失效边界热图 / 风险-覆盖轨迹）。

产出
----
1. `references/PAPER_TABLE_H2_COST_SWEEP.md` + `out_sensitivity/table_h2_cost_sweep.csv`
   —— 9 个代价点 × 3 端点 × 3 个比较（S4−S1 / S3−S1 / S4−S3），带**精确符号翻转 p**。
2. `figures/fig1_failure_boundary.png` —— 端点 × 代价点 的 Δu(S4−S1) 热图，格内标数值与显著性。
3. `figures/fig2_risk_coverage.png` —— 三端点上 S1/S3/S4 在代价扫描下的 覆盖率-风险 轨迹。

为什么这样画（不是审美问题）
--------------------------
- 审稿人对"又一个框架示意图"免疫，对**"哪里会坏、坏多少"**的定量图有反应 → 图 1 用发散热图，
  正值（准入更好）与负值（准入更差）同色标、同量纲，一眼看出符号翻转发生在哪个代价区间。
- 风险-覆盖图用**代价扫描的作业点连线**，而不是凭空插值：每个点都是真实跑出来的
  (coverage, risk_decided)，连线只表示"同一策略在不同代价下的移动方向"。

边界声明（必须随图）
-------------------
置换单位是随机种子（n=20），只说明"对重采样稳健"，**不外推**到新化合物。
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
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

from paper_table2 import sign_flip_p  # noqa: E402  同一个检验实现，避免两套口径

RES = os.path.join(ROOT, "out_keystone_v43", "results.json")
OUT_MD = os.path.join(ROOT, "references", "PAPER_TABLE_H2_COST_SWEEP.md")
OUT_CSV = os.path.join(ROOT, "out_sensitivity", "table_h2_cost_sweep.csv")
FIGDIR = os.path.join(ROOT, "figures")

COST_ORDER = [
    "false_pass=2.0",
    "false_pass=5.0",
    "false_pass=10.0",
    "abstain=0.05",
    "abstain=0.10",
    "abstain=0.20",
    "abstain=0.50",
    "abstain=1.00",
    "ref",
]
COST_LABEL = {
    "false_pass=2.0": "cPASS=2",
    "false_pass=5.0": "cPASS=5",
    "false_pass=10.0": "cPASS=10",
    "abstain=0.05": "cABS=0.05",
    "abstain=0.10": "cABS=0.10",
    "abstain=0.20": "cABS=0.20",
    "abstain=0.50": "cABS=0.50",
    "abstain=1.00": "cABS=1.00",
    "ref": "ref (5,1,0.5)",
}
COMPS = [
    ("S4_full_admission", "S1_naive_majority", "S4−S1"),
    ("S3_calibrated_conformal", "S1_naive_majority", "S3−S1"),
    ("S4_full_admission", "S3_calibrated_conformal", "S4−S3"),
]


def load():
    d = json.load(io.open(RES, encoding="utf-8"))
    per = {}
    for r in d.get("per_run", []):
        per[(r["endpoint"], r["strategy"], r["cost_point"], r["seed"])] = r
    eps = [e.strip() for e in d["endpoints"].split(",")]
    seeds = sorted({r["seed"] for r in d["per_run"]})
    return d, per, eps, seeds


def build_rows(per, eps, seeds):
    rows = []
    for ep in eps:
        for cp in COST_ORDER:
            for hi, lo, label in COMPS:
                ds, cov_hi, cov_lo = [], [], []
                for s in seeds:
                    a, b = per.get((ep, hi, cp, s)), per.get((ep, lo, cp, s))
                    if not a or not b:
                        continue
                    ds.append(a["utility"] - b["utility"])
                    cov_hi.append(a.get("coverage"))
                    cov_lo.append(b.get("coverage"))
                if not ds:
                    continue
                arr = np.array(ds)
                rows.append(
                    dict(
                        endpoint=ep,
                        cost_point=cp,
                        cost_label=COST_LABEL[cp],
                        comparison=label,
                        n=len(arr),
                        delta_median=float(np.median(arr)),
                        q1=float(np.percentile(arr, 25)),
                        q3=float(np.percentile(arr, 75)),
                        n_pos=int((arr > 0).sum()),
                        p=sign_flip_p(arr),
                        coverage_hi=float(
                            np.median([c for c in cov_hi if c is not None])
                        ),
                        coverage_lo=float(
                            np.median([c for c in cov_lo if c is not None])
                        ),
                    )
                )
    return rows


def to_md(rows):
    L = [
        "# Table H2｜代价扫描：9 个代价点 × 3 端点 × 3 个比较",
        "",
        "> 生成器：`tools/paper_figures.py`；数据：`out_keystone_v43/results.json`（20 seeds/cell）。",
        "> 检验：精确符号翻转置换（2^20 全枚举）；`***` p<0.001，`**` p<0.01，`*` p<0.05，`n.s.` 不显著。",
        "> 边界：单位是随机种子，不外推到新化合物。",
        "",
    ]
    for label in [c[2] for c in COMPS]:
        L += [
            "## %s" % label,
            "",
            "| 端点 | " + " | ".join(COST_LABEL[c] for c in COST_ORDER) + " |",
            "|---" * (len(COST_ORDER) + 1) + "|",
        ]
        for ep in ("hERG", "DILI", "BBB_Martins"):
            cells = []
            for cp in COST_ORDER:
                r = next(
                    (
                        x
                        for x in rows
                        if x["endpoint"] == ep
                        and x["cost_point"] == cp
                        and x["comparison"] == label
                    ),
                    None,
                )
                if not r:
                    cells.append("—")
                    continue
                star = (
                    "***"
                    if r["p"] < 0.001
                    else "**" if r["p"] < 0.01 else "*" if r["p"] < 0.05 else "n.s."
                )
                cells.append("%+.3f %s" % (r["delta_median"], star))
            L.append("| %s | %s |" % (ep, " | ".join(cells)))
        L.append("")
    L += [
        "## 读法",
        "",
        "1. **cPASS 区（左三列）**：假阳性代价升高 → 弃权更划算，所有策略都在移动；符号看是否翻正。",
        "2. **cABS 区（中五列）**：弃权变贵 → 覆盖上升、风险上升；这一段才是 H2 说的「代价区间」。",
        "3. `ref` 与 H1 主表同一点，用于核对两表一致（应逐位相同）。",
        "",
    ]
    return "\n".join(L)


def make_figures(rows, per, eps, seeds):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import TwoSlopeNorm

    os.makedirs(FIGDIR, exist_ok=True)
    plt.rcParams.update(
        {
            "font.size": 9,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "figure.dpi": 600,
        }
    )

    # ---- Fig 1: failure boundary heatmap ----
    M = np.full((len(eps), len(COST_ORDER)), np.nan)
    P = np.full((len(eps), len(COST_ORDER)), np.nan)
    for i, ep in enumerate(eps):
        for j, cp in enumerate(COST_ORDER):
            r = next(
                (
                    x
                    for x in rows
                    if x["endpoint"] == ep
                    and x["cost_point"] == cp
                    and x["comparison"] == "S4−S1"
                ),
                None,
            )
            if r:
                M[i, j] = r["delta_median"]
                P[i, j] = r["p"]
    vmax = np.nanmax(np.abs(M))
    fig, ax = plt.subplots(figsize=(7.2, 2.6))
    im = ax.imshow(
        M,
        cmap="RdBu_r",
        norm=TwoSlopeNorm(vmin=-vmax, vcenter=0, vmax=vmax),
        aspect="auto",
    )
    ax.set_xticks(range(len(COST_ORDER)))
    ax.set_xticklabels(
        [COST_LABEL[c] for c in COST_ORDER], rotation=40, ha="right", fontsize=7.5
    )
    ax.set_yticks(range(len(eps)))
    ax.set_yticklabels(eps)
    for i in range(len(eps)):
        for j in range(len(COST_ORDER)):
            if np.isnan(M[i, j]):
                continue
            star = (
                "***"
                if P[i, j] < 0.001
                else "**" if P[i, j] < 0.01 else "*" if P[i, j] < 0.05 else ""
            )
            ax.text(
                j,
                i,
                "%+.2f%s" % (M[i, j], star),
                ha="center",
                va="center",
                fontsize=7.5,
                color="black",
            )
    ax.axvline(2.5, color="0.3", lw=0.8, ls="--")
    ax.axvline(7.5, color="0.3", lw=0.8, ls="--")
    ax.set_title(
        "Failure boundary: Δu(S4 − S1) across cost configurations", fontsize=9.5
    )
    fig.colorbar(im, ax=ax, shrink=0.85, label="Δu (utility difference)")
    fig.text(
        0.01,
        -0.02,
        "Red = admission better; blue = admission worse. "
        "*** p<0.001 (exact sign-flip permutation, 20 paired seeds).",
        fontsize=6.5,
        color="0.35",
    )
    fig.tight_layout()
    f1 = os.path.join(FIGDIR, "fig1_failure_boundary.png")
    fig.savefig(f1, dpi=600, bbox_inches="tight")
    plt.close(fig)

    # ---- Fig 2: 代价响应曲线（上：Δu vs cABS；下：coverage vs cABS）----
    # 说明：不画经典 risk–coverage 曲线，因为只有 9 个代价点、且多数代价点给出**同一个**
    # 覆盖率（效用最优的弃权阈值只有少数几档），连起来会得到一张"看似只有 3 个点"的假曲线。
    # 换成代价响应图：横轴是代价本身，能直接把"符号在哪翻"画出来。
    abs_pts = [c for c in COST_ORDER if c.startswith("abstain=")]
    xs = [float(c.split("=")[1]) for c in abs_pts]

    def series(ep, hi, lo):
        ys = []
        for cp in abs_pts:
            r = next(
                (
                    x
                    for x in rows
                    if x["endpoint"] == ep
                    and x["cost_point"] == cp
                    and x["comparison"]
                    == (
                        "S4−S1"
                        if (hi, lo) == ("S4_full_admission", "S1_naive_majority")
                        else "S4−S3"
                    )
                ),
                None,
            )
            ys.append(r["delta_median"] if r else np.nan)
        return np.array(ys)

    fig, axes = plt.subplots(
        2, len(eps), figsize=(9.4, 5.0), gridspec_kw={"height_ratios": [1.15, 1]}
    )
    for k, ep in enumerate(eps):
        ax = axes[0, k]
        ax.axhline(0, color="0.4", lw=0.8)
        ax.plot(
            xs,
            series(ep, "S4_full_admission", "S1_naive_majority"),
            marker="o",
            ms=4,
            lw=1.4,
            color="#c62828",
            label="S4−S1",
        )
        ax.plot(
            xs,
            series(ep, "S4_full_admission", "S3_calibrated_conformal"),
            marker="s",
            ms=4,
            lw=1.4,
            color="#1565c0",
            label="S4−S3",
        )
        ax.set_xscale("log")
        ax.set_title(ep, fontsize=9)
        ax.grid(alpha=0.25, lw=0.5)
        if k == 0:
            ax.set_ylabel("Δu (median)")
            ax.legend(fontsize=7, frameon=False)
        ax.set_xlabel("c_abstain (log)")

        ax2 = axes[1, k]
        for strat, col, mk in (
            ("S1_naive_majority", "#1f4e79", "o"),
            ("S3_calibrated_conformal", "#2e7d32", "s"),
            ("S4_full_admission", "#c62828", "^"),
        ):
            cov = [
                float(
                    np.median(
                        [
                            per[(ep, strat, cp, s)]["coverage"]
                            for s in seeds
                            if (ep, strat, cp, s) in per
                        ]
                    )
                )
                for cp in abs_pts
            ]
            ax2.plot(
                xs, cov, marker=mk, ms=4, lw=1.3, color=col, label=strat.split("_")[0]
            )
        ax2.set_xscale("log")
        ax2.grid(alpha=0.25, lw=0.5)
        ax2.set_xlabel("c_abstain (log)")
        if k == 0:
            ax2.set_ylabel("coverage")
            ax2.legend(fontsize=6.5, frameon=False, ncol=3, loc="lower left")
    fig.suptitle(
        "Cost response: utility difference and coverage vs abstention cost "
        "(median over 20 seeds)",
        fontsize=9.5,
    )
    fig.tight_layout()
    f2 = os.path.join(FIGDIR, "fig2_cost_response.png")
    fig.savefig(f2, dpi=600, bbox_inches="tight")
    plt.close(fig)
    return f1, f2


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.parse_args(argv)
    d, per, eps, seeds = load()
    rows = build_rows(per, eps, seeds)
    io.open(OUT_MD, "w", encoding="utf-8", newline="\n").write(to_md(rows))
    os.makedirs(os.path.dirname(OUT_CSV), exist_ok=True)
    with io.open(OUT_CSV, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        for r in rows:
            w.writerow(r)
    f1, f2 = make_figures(rows, per, eps, seeds)
    print("[h2] %d 行 -> %s" % (len(rows), os.path.relpath(OUT_MD, ROOT)))
    print("[h2] csv -> %s" % os.path.relpath(OUT_CSV, ROOT))
    print(
        "[h2] fig1 -> %s\n[h2] fig2 -> %s"
        % (os.path.relpath(f1, ROOT), os.path.relpath(f2, ROOT))
    )

    # 与主表自洽核对：ref 行必须与 PAPER_TABLE2 一致
    ref = [r for r in rows if r["cost_point"] == "ref" and r["comparison"] == "S4−S1"]
    for r in sorted(ref, key=lambda x: x["endpoint"]):
        print(
            "   [ref-check] %-12s Δ=%+.4f n_pos=%d/%d p=%.2g"
            % (r["endpoint"], r["delta_median"], r["n_pos"], r["n"], r["p"])
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
