# -*- coding: utf-8 -*-
"""工作包 F：用 conformal 区间给 UNDETERMINED 做独立验证。

评审原话（2026-10-29）：
  "在基准数据集上，对每个源或共识值用 split-conformal 生成区间，然后检查：
   框架标记为 UNDETERMINED 的 化合物×端点，其 conformal 区间宽度是否系统性地
   大于 PASS/FAIL 的 化合物×端点。如果是，就多了一个独立于裁决逻辑的验证。"

本模块只做**验证**，不生成区间（生成用 `adt.conformal`）：
  - 输入：`conformal_intervals.csv`（含 width/flag） + `reliability.csv`（含 verdict）
  - 输出：UNDETERMINED vs PASS/FAIL 的宽度分布、比值、AUC（宽度预测弃权）
  - 纪律：`self_calibrated` / `insufficient` / 空 width 的记录**不参与**比较，
    否则"自我校准的窄区间"会把结论拉向反面。
"""

import csv
import io
import math


def _f(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _median(vals):
    s = sorted(vals)
    n = len(s)
    if n == 0:
        return None
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def _quantile(vals, q):
    s = sorted(vals)
    if not s:
        return None
    i = min(len(s) - 1, max(0, int(round(q * (len(s) - 1)))))
    return s[i]


def _auc(scores, labels):
    """Mann-Whitney AUC：labels=1 表示 UNDETERMINED。"""
    n_p = sum(1 for y in labels if y == 1)
    n_n = len(labels) - n_p
    if n_p == 0 or n_n == 0:
        return None
    order = sorted(range(len(scores)), key=lambda i: scores[i])
    ranks = [0.0] * len(scores)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and scores[order[j + 1]] == scores[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    r_pos = sum(r for r, y in zip(ranks, labels) if y == 1)
    return (r_pos - n_p * (n_p + 1) / 2.0) / (n_p * n_n)


def load(path):
    with io.open(path, encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def assess(conf_rows, rel_rows):
    """返回 (per_verdict, summary)。

    per_verdict: PASS/FAIL/UNDETERMINED 各自的 n / median / IQR
    summary: 两组对比 + AUC + 结论
    """
    rel = {(r.get("compound_id", ""), r.get("endpoint", "")): r for r in rel_rows}
    groups = {"UNDETERMINED": [], "PASS": [], "FAIL": []}
    n_skip = 0
    for c in conf_rows:
        w = _f(c.get("width"))
        flag = (c.get("flag") or "").strip()
        if w is None or w <= 0:
            n_skip += 1
            continue
        if flag in ("self_calibrated", "insufficient", "no_prediction"):
            n_skip += 1
            continue
        key = (c.get("compound_id", ""), c.get("endpoint", ""))
        v = (rel.get(key) or {}).get("verdict", "")
        if v not in groups:
            n_skip += 1
            continue
        groups[v].append(w)

    per = []
    for v in ("PASS", "FAIL", "UNDETERMINED"):
        vals = groups[v]
        per.append(
            dict(
                verdict=v,
                n=len(vals),
                median_width=("" if not vals else round(_median(vals), 4)),
                q1=("" if not vals else round(_quantile(vals, 0.25), 4)),
                q3=("" if not vals else round(_quantile(vals, 0.75), 4)),
                mean_width=("" if not vals else round(sum(vals) / len(vals), 4)),
            )
        )

    und = groups["UNDETERMINED"]
    dec = groups["PASS"] + groups["FAIL"]
    med_u = _median(und) if und else None
    med_d = _median(dec) if dec else None
    ratio = (med_u / med_d) if (med_u is not None and med_d not in (None, 0)) else None
    scores = und + dec
    labels = [1] * len(und) + [0] * len(dec)
    auc = _auc(scores, labels) if scores else None
    if auc is None:
        conclusion = "样本不足（需要同时有 UNDETERMINED 与 PASS/FAIL 且宽度可用）"
    elif auc >= 0.65 and (ratio or 0) >= 1.2:
        conclusion = "支持：UNDETERMINED 的区间系统性更宽（AUC=%.3f, 中位比=%.2f）" % (
            auc,
            ratio,
        )
    elif auc <= 0.35:
        conclusion = "不支持/反向：UNDETERMINED 区间反而更窄（AUC=%.3f）" % auc
    else:
        conclusion = "证据弱：AUC=%.3f，中位比=%s——不能声称区间宽度可替代弃权" % (
            auc,
            ("%.2f" % ratio) if ratio is not None else "NA",
        )
    summary = dict(
        n_total=len(und) + len(dec),
        n_undetermined=len(und),
        n_decided=len(dec),
        n_skipped=n_skip,
        median_width_undetermined=("" if med_u is None else round(med_u, 4)),
        median_width_decided=("" if med_d is None else round(med_d, 4)),
        ratio=("" if ratio is None else round(ratio, 4)),
        auc_width_vs_abstention=("" if auc is None else round(auc, 4)),
        conclusion=conclusion,
    )
    return per, summary


def write(outdir, per, summary):
    import os

    p1 = os.path.join(outdir, "conformal_check.csv")
    with io.open(p1, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(
            fh,
            fieldnames=["verdict", "n", "median_width", "q1", "q3", "mean_width"],
            extrasaction="ignore",
        )
        w.writeheader()
        w.writerows(per)
    p2 = os.path.join(outdir, "conformal_check_summary.csv")
    with io.open(p2, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(summary.keys()))
        w.writeheader()
        w.writerow(summary)
    return p1, p2
