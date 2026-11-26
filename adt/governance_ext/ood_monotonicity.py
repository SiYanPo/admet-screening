# -*- coding: utf-8 -*-
"""贯穿性元断言：OOD 偏移强度递增时的行为单调性。

监管真正关心的不是"已知测试集全绿"，而是：
随着测试集远离锚点/训练分布，系统是否**逐步变得更谨慎**，
而不是继续自信、也不是突然全面沉默。

本模块沿相似度分层（近→远）计算：
  - UNDETERMINED 触发率
  - T0 降级率
  - 平均 UQ std / coverage（若有）
并要求：
  1. 远端 UNDETERMINED/T0 率 >= 预设下限（不能沉默）；
  2. 随距离增加，触发率非下降（允许 tolerance 抖动）；
  3. 远端相对近端必须显著上升（不能平坦无响应）；
  4. coverage 若提供，随距离非上升。
任一不满足 → ci_gate 失败。
"""

from __future__ import annotations

from . import uncertainty_quantification as uq


def _rate(rows):
    n = len(rows)
    if not n:
        return None
    return sum(1 for r in rows if r) / n


def build_ood_curve(buckets, *, reference, endpoint="dili", **gate_kwargs):
    """buckets: [{"name":"near","distance":0.1,"records":[...]}]，records 含 smiles/value。"""
    curve = []
    for b in sorted(buckets, key=lambda x: float(x.get("distance", 0))):
        rows = []
        for rec in b.get("records", []):
            out = uq.uq_gate(rec, reference=reference, endpoint=endpoint, **gate_kwargs)
            rows.append(out)
        curve.append(
            {
                "bucket": b.get("name"),
                "distance": float(b.get("distance", 0)),
                "n": len(rows),
                "undetermined_rate": _rate(
                    [r.get("verdict") == "UNDETERMINED" for r in rows]
                ),
                "t0_rate": _rate([str(r.get("tier_ceiling")) == "T0" for r in rows]),
                "mean_std": (
                    sum(
                        float(r["uq"]["std"])
                        for r in rows
                        if r.get("uq", {}).get("std") is not None
                    )
                    / max(
                        1,
                        sum(1 for r in rows if r.get("uq", {}).get("std") is not None),
                    )
                ),
                "mean_coverage": (
                    sum(
                        float(r["uq"]["coverage"])
                        for r in rows
                        if r.get("uq", {}).get("coverage") is not None
                    )
                    / max(
                        1,
                        sum(
                            1
                            for r in rows
                            if r.get("uq", {}).get("coverage") is not None
                        ),
                    )
                ),
            }
        )
    return curve


def ood_monotonicity_gate(
    curve, *, min_far_rate=0.50, min_increase=0.20, tolerance=0.10
):
    """检查"越远越谨慎"的单调响应；沉默/平坦/倒退都失败。"""
    reasons, violations = [], []
    if len(curve) < 2:
        return {
            "ok": False,
            "reasons": ["至少需要两个偏移分层"],
            "violations": [],
            "curve": curve,
        }
    for metric, direction in (("undetermined_rate", "up"), ("t0_rate", "up")):
        vals = [b.get(metric) for b in curve]
        if any(v is None for v in vals):
            reasons.append("%s 存在空分层" % metric)
            continue
        for i in range(1, len(vals)):
            if direction == "up" and vals[i] + tolerance < vals[i - 1]:
                violations.append(
                    {
                        "metric": metric,
                        "index": i,
                        "prev": vals[i - 1],
                        "now": vals[i],
                        "type": "NON_MONOTONIC_DROP",
                    }
                )
    far = curve[-1]
    near = curve[0]
    for metric in ("undetermined_rate", "t0_rate"):
        if far.get(metric) is None:
            continue
        if far[metric] < min_far_rate:
            reasons.append(
                "远端 %s %.3f < 下限 %.3f（系统在最远处保持沉默）"
                % (metric, far[metric], min_far_rate)
            )
        if far[metric] - near.get(metric, 0) < min_increase:
            reasons.append(
                "远端 %s 相对近端上升 %.3f < %.3f（响应过于平坦）"
                % (metric, far[metric] - near.get(metric, 0), min_increase)
            )
    covs = [b.get("mean_coverage") for b in curve]
    if all(c is not None for c in covs):
        for i in range(1, len(covs)):
            if covs[i] > covs[i - 1] + tolerance:
                violations.append(
                    {
                        "metric": "mean_coverage",
                        "index": i,
                        "prev": covs[i - 1],
                        "now": covs[i],
                        "type": "COVERAGE_INCREASES_WITH_DISTANCE",
                    }
                )
    if violations:
        reasons.extend(
            "%s 在分层 %d 违反单调性: %s -> %s"
            % (v["metric"], v["index"], v["prev"], v["now"])
            for v in violations
        )
    return {
        "ok": not reasons,
        "reasons": reasons,
        "violations": violations,
        "curve": curve,
        "note": "只验证响应形状，不证明远域绝对正确；远端必须显著更谨慎",
    }
