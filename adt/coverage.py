# -*- coding: utf-8 -*-
"""端点级覆盖率矩阵（v2.3）。

**为什么需要它**：本项目的核心结论之一是"vNN 在 14 个糖苷上 10/15 端点全
NoPrediction"——但在 v2.2 之前，这个结论只能靠人工数宽表，报告里无法自动引用。
本模块把"源 × 端点"的可判比例做成表，使以下三类判断可自动化：

  1) **源不可用**：某源在某端点覆盖率 = 0 → 该端点下该源只能弃权（不是"阴性"）；
  2) **源整体不可用**：源的平均覆盖率 < 0.30（G6）→ 整源降为背景；
  3) **端点饱和**：某端点在**所有源**上覆盖率都低 → 该端点在本化学类不可判。

与 `saturate`（端点值有没有区分度）互补：那个看**值**的分布，这个看**有没有值**。
"""

import csv
import io
import os
from collections import defaultdict

PRED_FLAGS = {"predicted", "manual"}
MIN_COVERAGE = 0.30  # G6：整源平均覆盖率低于此值 → 背景


def build(rows, min_coverage=MIN_COVERAGE, min_n_pred=3):
    """返回 (matrix_rows, summary)。

    matrix_rows: 每个 (source, endpoint) 一行。
    summary: {"by_source": {...}, "zero_endpoints": [...], "by_endpoint": {...}}
    """
    g = defaultdict(lambda: dict(n=0, pred=0, ood=0, meas=0, err=0, sat=0))
    for r in rows:
        src = r.get("source", "")
        ep = r.get("endpoint", "")
        flag = r.get("domain_flag", "")
        k = (src, ep)
        g[k]["n"] += 1
        if flag in PRED_FLAGS:
            g[k]["pred"] += 1
        elif flag == "out_of_domain":
            g[k]["ood"] += 1
        elif flag == "measured":
            g[k]["meas"] += 1
        elif flag == "error":
            g[k]["err"] += 1
        elif flag == "saturated":
            g[k]["sat"] += 1

    out = []
    for (src, ep), d in sorted(g.items()):
        usable = d["pred"] + d["meas"]
        cov = usable / d["n"] if d["n"] else 0.0
        if d["n"] == 0:
            flag = "no_data"
        elif usable == 0:
            flag = "no_prediction"  # 全部 NoPrediction/error —— 只能弃权
        elif cov < min_coverage or usable < min_n_pred:
            flag = "insufficient_coverage"  # 有值但太少
        else:
            flag = "usable"
        note = "%d 行：可判 %d / 域外 %d / 实测 %d / 错误 %d" % (
            d["n"],
            usable,
            d["ood"],
            d["meas"],
            d["err"],
        )
        if flag == "no_prediction":
            note += "；该源在此端点对本批**无任何可判值**——不得读作阴性"
        out.append(
            dict(
                source=src,
                endpoint=ep,
                n=d["n"],
                n_usable=usable,
                n_out_of_domain=d["ood"],
                n_measured=d["meas"],
                coverage=round(cov, 3),
                flag=flag,
                note=note,
            )
        )

    by_source = defaultdict(list)
    for r in out:
        by_source[r["source"]].append(r)
    summary = dict(by_source={}, zero_endpoints=[], by_endpoint={})
    for src, rs in by_source.items():
        n = sum(r["n"] for r in rs)
        u = sum(r["n_usable"] for r in rs)
        summary["by_source"][src] = dict(
            coverage=round(u / n, 3) if n else 0.0,
            n_endpoints=len(rs),
            n_usable_endpoints=sum(1 for r in rs if r["flag"] == "usable"),
            n_zero_endpoints=sum(1 for r in rs if r["flag"] == "no_prediction"),
            verdict=("background_only" if n and u / n < min_coverage else "usable"),
        )
    by_ep = defaultdict(list)
    for r in out:
        by_ep[r["endpoint"]].append(r)
    for ep, rs in by_ep.items():
        tot = sum(r["n"] for r in rs)
        u = sum(r["n_usable"] for r in rs)
        summary["by_endpoint"][ep] = round(u / tot, 3) if tot else 0.0
        if tot and u == 0:
            summary["zero_endpoints"].append(ep)
    return out, summary


def write(path, rows):
    cols = [
        "source",
        "endpoint",
        "n",
        "n_usable",
        "n_out_of_domain",
        "n_measured",
        "coverage",
        "flag",
        "note",
    ]
    with io.open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return len(rows)
