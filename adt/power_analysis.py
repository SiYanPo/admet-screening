# -*- coding: utf-8 -*-
"""前瞻性样本量/统计功效规划（2026-11-19；技能市场 100 skill 移植）。

## 来源
`@indiv-tanbeiping/quantitative-research-plus`（组2[50]）原文：
"design experiments or surveys with hypothesis testing, plan sample size and
statistical power analysis"。
本 skill 原先只有**事后**标注（source-admit 的 CI、n<30 拒绝报 ρ），
缺"事前该收多少样本"的规划能力——这是 G9 条件②（前瞻验证）的必备前置。

## 实现
纯标准库 `statistics.NormalDist`（无需 scipy）。两样本比例检验的正态近似：
  n_per_group = [z_{1-α/2}·sqrt(2·p̄(1−p̄)) + z_{1−β}·sqrt(p1(1−p1)+p2(1−p2))]² / Δ²
  achieved_power = Φ( (|Δ|√n − z_{1−α/2}·sqrt(2·p̄(1−p̄))) / sqrt(p1(1−p1)+p2(1−p2)) )

## 诚实边界
* 正态近似；小样本/极端比例（p 接近 0/1）时须用精确法（Clopper-Pearson/置换），
  本模块会标 `approximation_caveat`。
* 只做规划，不伪造数据可得性（呼应 Clinical Cohort Protocol Designer 的
  "Do not invent data availability / sample size adequacy"）。
"""

from __future__ import annotations

import math
from statistics import NormalDist

_ND = NormalDist()
Z = _ND.inv_cdf


def _valid_p(p, name="p"):
    if not isinstance(p, (int, float)) or isinstance(p, bool):
        raise ValueError("%s 必须是数值" % name)
    if not (0 < float(p) < 1):
        raise ValueError("%s 必须在 (0,1)，实际 %r" % (name, p))
    return float(p)


def required_n(p1, p2, alpha=0.05, power=0.80, ratio=1.0, rounding="ceil"):
    """两样本比例检验每组所需样本量。

    p1/p2: 两组预期比例；ratio = n2/n1（默认 1 即等组）。
    返回 dict(required_n_per_group, required_n_total, ...)。
    """
    p1, p2 = _valid_p(p1, "p1"), _valid_p(p2, "p2")
    if not (0 < alpha < 1) or not (0 < power < 1):
        raise ValueError("alpha/power 必须在 (0,1)")
    if (
        not isinstance(ratio, (int, float))
        or isinstance(ratio, bool)
        or not math.isfinite(ratio)
    ):
        raise ValueError("ratio 必须是有限数值")
    if ratio <= 0:
        raise ValueError("ratio 必须 > 0")
    if rounding not in ("ceil", "round"):
        raise ValueError("rounding 必须是 'ceil' 或 'round'，实际 %r" % rounding)
    delta = abs(p1 - p2)
    if delta == 0:
        return dict(
            verdict="IMPOSSIBLE",
            reason="p1==p2，效应为 0，无法规划有限样本量",
            human_confirmation_required=True,
        )
    pbar = (p1 + ratio * p2) / (1 + ratio)
    z_a, z_b = Z(1 - alpha / 2), Z(power)
    term1 = z_a * math.sqrt((1 + 1 / ratio) * pbar * (1 - pbar))
    term2 = z_b * math.sqrt(p1 * (1 - p1) + p2 * (1 - p2) / ratio)
    n1 = (term1 + term2) ** 2 / (delta**2)
    n1_i = math.ceil(n1) if rounding == "ceil" else int(round(n1))
    caveat = p1 < 0.05 or p1 > 0.95 or p2 < 0.05 or p2 > 0.95 or n1_i < 30
    return dict(
        verdict="OK",
        p1=p1,
        p2=p2,
        delta=round(delta, 6),
        alpha=alpha,
        target_power=power,
        ratio=ratio,
        required_n_per_group=n1_i,
        required_n_total=n1_i + int(round(ratio * n1_i)),
        raw_n=round(n1, 4),
        approximation_caveat=(
            "正态近似可能不稳（极端比例或小样本），须用精确法复核" if caveat else None
        ),
        human_confirmation_required=True,
        not_a_claim_of="数据实际可得 / 实际已达到该功效",
    )


def achieved_power(p1, p2, n_per_group, alpha=0.05, ratio=1.0):
    """给定每组样本量，计算可达到的功效（与 required_n 互逆自检用）。"""
    p1, p2 = _valid_p(p1, "p1"), _valid_p(p2, "p2")
    if not (0 < alpha < 1):
        raise ValueError("alpha 必须在 (0,1)，实际 %r" % alpha)
    if (
        not isinstance(n_per_group, (int, float))
        or isinstance(n_per_group, bool)
        or not isinstance(ratio, (int, float))
        or isinstance(ratio, bool)
        or not math.isfinite(n_per_group)
        or not math.isfinite(ratio)
    ):
        raise ValueError("n_per_group/ratio 必须是有限数值")
    if n_per_group <= 0 or ratio <= 0:
        raise ValueError("n_per_group/ratio 必须 > 0")
    delta = abs(p1 - p2)
    pbar = (p1 + ratio * p2) / (1 + ratio)
    se0 = math.sqrt((1 + 1 / ratio) * pbar * (1 - pbar))
    se1 = math.sqrt(p1 * (1 - p1) + p2 * (1 - p2) / ratio)
    if se1 == 0:
        return dict(verdict="DEGENERATE", reason="方差为 0")
    z = (delta * math.sqrt(n_per_group) - Z(1 - alpha / 2) * se0) / se1
    pw = _ND.cdf(z)
    return dict(
        verdict="OK",
        achieved_power=round(pw, 6),
        alpha=alpha,
        n_per_group=n_per_group,
        underpowered=(pw < 0.80),
        human_confirmation_required=True,
    )


def underpowered_guard(n, min_n=30, note=""):
    """与现有 n<30 拒绝报 ρ 的纪律对齐（给单点小样本一个明确 verdict）。"""
    return dict(
        verdict=("UNDERPOWERED" if n < min_n else "OK"),
        n=n,
        min_n=min_n,
        reason=(
            "n=%d < %d：不报 ρ/排序结论，只作定性描述" % (n, min_n)
            if n < min_n
            else "样本量达到定性门槛（不代表功效充足）"
        ),
        note=note,
        human_confirmation_required=True,
    )


def selftest():
    rows = []

    def chk(name, cond, detail=""):
        rows.append(dict(name=name, ok=bool(cond), detail=detail))

    r = required_n(0.5, 0.7, alpha=0.05, power=0.80)
    chk(
        "required_n_computes",
        r["verdict"] == "OK" and r["required_n_per_group"] > 0,
        "n=%s" % r.get("required_n_per_group"),
    )
    # 互逆性：用算出的 n 反推功效应 >= 目标（向上取整）
    pw = achieved_power(0.5, 0.7, r["required_n_per_group"])
    chk(
        "inverse_consistency",
        pw["achieved_power"] >= 0.80,
        "power=%s" % pw["achieved_power"],
    )
    # 更大效应 → 更少样本
    r2 = required_n(0.5, 0.9)
    chk(
        "larger_effect_fewer_n",
        r2["required_n_per_group"] < r["required_n_per_group"],
        "%s < %s" % (r2["required_n_per_group"], r["required_n_per_group"]),
    )
    # 更高功效 → 更多样本
    r3 = required_n(0.5, 0.7, power=0.95)
    chk(
        "higher_power_more_n",
        r3["required_n_per_group"] > r["required_n_per_group"],
        "%s > %s" % (r3["required_n_per_group"], r["required_n_per_group"]),
    )
    chk("zero_effect_impossible", required_n(0.6, 0.6)["verdict"] == "IMPOSSIBLE", "")
    try:
        _valid_p(1.0)
        chk("invalid_p_rejected", False, "")
    except ValueError:
        chk("invalid_p_rejected", True, "")
    chk("small_n_guard", underpowered_guard(12)["verdict"] == "UNDERPOWERED", "")
    return all(x["ok"] for x in rows), rows


if __name__ == "__main__":
    import argparse, json

    ap = argparse.ArgumentParser(prog="power-analysis")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        ok, rows = selftest()
        for r in rows:
            print(
                "[%s] %s %s"
                % ("OK" if r["ok"] else "FAIL", r["name"], r["detail"][:60])
            )
        print("[power-analysis] %s" % ("PASS" if ok else "FAIL"))
        raise SystemExit(0 if ok else 4)
