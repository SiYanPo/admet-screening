# -*- coding: utf-8 -*-
"""PBPK 模型资格认定（v4.17）：没有这一步，PBPK 只是"会算"，不是"能用"。

FDA (2020) / EMA (2018) 的 PBPK 指南都要求先给模型的**预期用途（context of use）**
做资格认定，再用它外推。本 skill 此前只有 `pbpk` 的模拟与三项自校验
（质量守恒 / 场景稳健性 / MC 收敛）——那三项保证的是"算得对"，
**不保证"算得准"**。两者是不同的东西，本模块补后者。

指标（全部按观测-预测配对算）：
  fold_error_i = pred_i / obs_i
  AFE   = 10^(mean(log10 fold_error))        >1 系统性高估，<1 系统性低估
  AAFE  = 10^(mean(|log10 fold_error|))      与方向无关的平均倍数偏差
  %2fold = |log10 fold| ≤ log10(2) 的占比
  %3fold 同理

判定（**行业惯例阈值，不是监管强制线**）：
  n_pairs < 5                      → insufficient_n
  每个化合物观测时点数 < 2          → insufficient_timepoints（只对 Cmax 不算资格认定）
  AAFE ≤ 2 且 %2fold ≥ 80%         → qualified_conventional
  其余                              → not_qualified
EMA 2018 要求报告 fold error 但**未规定通过线**；2 倍/80% 是文献与工业界常用工作点，
引用时必须写成"惯例"，不得写成"符合法规要求"。
"""

from __future__ import division

import math

__all__ = [
    "QualificationError",
    "fold_error",
    "afe_aafe",
    "qualify",
    "THRESHOLDS",
    "limits_statement",
]

THRESHOLDS = dict(
    min_pairs=5,
    min_timepoints_per_compound=2,
    aafe_max=2.0,
    pct_2fold_min=0.80,
    source="convention (工业界常用工作点；EMA 2018 未规定通过线)",
)


class QualificationError(ValueError):
    pass


def fold_error(pred, obs):
    if obs is None or obs != obs or obs <= 0 or pred is None or pred != pred:
        return float("nan")
    return float(pred) / float(obs)


def afe_aafe(folds):
    vals = [f for f in folds if f == f and f > 0]
    if not vals:
        return dict(
            n=0,
            afe=float("nan"),
            aafe=float("nan"),
            pct_2fold=float("nan"),
            pct_3fold=float("nan"),
            rmse_log10=float("nan"),
        )
    lg = [math.log10(v) for v in vals]
    n = len(lg)
    mean = sum(lg) / n
    mad = sum(abs(x) for x in lg) / n
    return dict(
        n=n,
        afe=round(10**mean, 3),
        aafe=round(10**mad, 3),
        pct_2fold=round(sum(1 for x in lg if abs(x) <= math.log10(2)) / n, 3),
        pct_3fold=round(sum(1 for x in lg if abs(x) <= math.log10(3)) / n, 3),
        rmse_log10=round(math.sqrt(sum(x * x for x in lg) / n), 3),
    )


def qualify(pairs, intended_use="screening_level_exposure", thresholds=None):
    """pairs: list[dict(compound_id, time_h, obs, pred, unit)].

    返回 dict：总体指标 + 逐化合物指标 + verdict + reason + 引用纪律。
    """
    th = dict(THRESHOLDS)
    if thresholds:
        th.update(thresholds)
    if not pairs:
        raise QualificationError("没有任何观测-预测配对")

    units = {(p.get("unit") or "").strip() for p in pairs}
    if len(units) > 1:
        raise QualificationError(
            "观测与预测单位不一致（%s）：PBPK 资格认定必须同量纲，"
            "先换算再评（单位异构是最常见的假结论来源）" % sorted(units)
        )

    per = {}
    for p in pairs:
        cid = p.get("compound_id") or "?"
        try:
            obs = float(p["obs"])
            pred = float(p["pred"])
        except (KeyError, TypeError, ValueError):
            continue
        f = fold_error(pred, obs)
        if f != f or f <= 0:
            continue
        per.setdefault(cid, []).append(
            dict(time_h=p.get("time_h", ""), obs=obs, pred=pred, fold=f)
        )

    if not per:
        raise QualificationError("配对里没有一条 obs/pred 同时为正的记录")

    all_folds = [r["fold"] for rows in per.values() for r in rows]
    overall = afe_aafe(all_folds)
    n_compounds = len(per)
    min_tp = min(len(v) for v in per.values())

    per_rows = []
    for cid, rows in sorted(per.items()):
        m = afe_aafe([r["fold"] for r in rows])
        per_rows.append(
            dict(
                compound_id=cid,
                n_obs=m["n"],
                afe=m["afe"],
                aafe=m["aafe"],
                pct_2fold=m["pct_2fold"],
                worst_fold=round(
                    max(rows, key=lambda r: abs(math.log10(r["fold"])))["fold"], 3
                ),
            )
        )

    if overall["n"] < th["min_pairs"]:
        verdict, reason = "insufficient_n", (
            "配对数 %d < %d：只能报描述统计，不构成资格认定"
            % (overall["n"], th["min_pairs"])
        )
    elif min_tp < th["min_timepoints_per_compound"]:
        verdict, reason = "insufficient_timepoints", (
            "有化合物只有 %d 个时间点：**只对 Cmax 的比对不构成 PBPK 资格认定**"
            "（曲线的形状才是 PBPK 相对房室模型的价值所在）" % min_tp
        )
    elif (
        overall["aafe"] <= th["aafe_max"]
        and overall["pct_2fold"] >= th["pct_2fold_min"]
    ):
        verdict, reason = "qualified_conventional", (
            "AAFE %.2f ≤ %.1f 且 2 倍内 %.0f%% ≥ %.0f%%（惯例工作点）"
            % (
                overall["aafe"],
                th["aafe_max"],
                100 * overall["pct_2fold"],
                100 * th["pct_2fold_min"],
            )
        )
    else:
        verdict, reason = "not_qualified", (
            "AAFE %.2f / 2 倍内 %.0f%% 未达惯例工作点（%.1f / %.0f%%）"
            % (
                overall["aafe"],
                100 * overall["pct_2fold"],
                th["aafe_max"],
                100 * th["pct_2fold_min"],
            )
        )

    return dict(
        intended_use=intended_use,
        n_pairs=overall["n"],
        n_compounds=n_compounds,
        min_timepoints=min_tp,
        afe=overall["afe"],
        aafe=overall["aafe"],
        pct_2fold=overall["pct_2fold"],
        pct_3fold=overall["pct_3fold"],
        rmse_log10=overall["rmse_log10"],
        unit=sorted(units)[0] if units else "",
        verdict=verdict,
        reason=reason,
        thresholds=th,
        per_compound=per_rows,
        allowed_statement=_allowed(verdict, intended_use, overall, th),
        limits=limits_statement(),
    )


def _allowed(verdict, intended_use, overall, th):
    if verdict == "qualified_conventional":
        return (
            "在「%s」这一预期用途下，模型对已有观测的偏差达惯例工作点"
            "（AAFE %.2f，2 倍内 %.0f%%）；**只对同一化学类、同一给药途径、"
            "同一剂量量级**外推，且必须同时报出 n=%d 与逐分子最差倍数"
            % (intended_use, overall["aafe"], 100 * overall["pct_2fold"], overall["n"])
        )
    if verdict.startswith("insufficient"):
        return (
            "数据不足以做 PBPK 资格认定；只能表述为「模型已建立、"
            "未经资格认定」，**不得**用它支撑任何定量外推"
        )
    return (
        "模型未达惯例工作点（AAFE %.2f / 2 倍内 %.0f%%）；"
        "只能作方向与量级判断，不得给出定量暴露外推"
        % (overall["aafe"], 100 * overall["pct_2fold"])
    )


def limits_statement():
    return (
        "AFE/AAFE/2 倍内比例都是**点估计**，n 小时 CI 很宽（本模块未给 bootstrap CI，"
        "n<10 时应视为不稳定）；观测值自身的实验误差（LC-MS/MS 通常 ±15%）已经"
        "占去 2 倍判据的大半，故 2 倍内比例高不等于模型机理正确；"
        "对映体/活性代谢物/肠肝循环未被观测覆盖时，AAFE 会因「配对选择性」而虚高。"
    )
