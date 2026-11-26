# -*- coding: utf-8 -*-
"""问题②-a：数据稀疏度惩罚 + 发表偏倚校正探针（L1 层）。

关键纠偏（来自设计文档 2.1）：
真正的坑不是"没有邻居"，而是"邻居都有数据，但都不是目标端点的实测"（C79）。
所以 endpoint_support() 统计的是"有目标端点实测的邻居数"，不是邻居总数。

纯标准库（math），可独立测试。
"""

from __future__ import annotations
import math


def endpoint_support(neighbors, endpoint, *, min_n=5, target_n=30):
    """neighbors: [{"endpoints_available": set/list, ...}, ...]。
    返回该端点的支撑度与惩罚系数。
    """
    support = [n for n in neighbors if endpoint in (n.get("endpoints_available") or ())]
    n = len(support)
    if n < min_n:
        return {
            "endpoint": endpoint,
            "n_support": n,
            "status": "insufficient",
            "penalty": 1.0,  # 完全惩罚
            "verdict_hint": "Exploratory",  # 强制降级探索级
            "action": "证据不足，无法评估；需湿实验或补充该端点实测",
        }
    penalty = min(1.0, target_n / float(n)) if n >= min_n else 1.0
    return {
        "endpoint": endpoint,
        "n_support": n,
        "status": "adequate" if n >= target_n else "thin",
        "penalty": round(penalty, 3),
        "verdict_hint": "Reference" if n >= target_n else "Reference_Thin",
        "action": "" if n >= target_n else "支撑薄弱，参照分位降权使用",
    }


def _mean(xs):
    return sum(xs) / float(len(xs)) if xs else 0.0


def egger_test(effects, precisions):
    """Egger 回归的轻量实现：effect/precision ~ 1/precision 的截距。

    无截距显著性的 p 值（纯标准库，用正态近似）；仅当研究数 ≥ 10 时可靠。
    返回 dict(intercept, slope, se_intercept, z, p, n, reliable)。
    """
    xs, ys = [], []
    for e, p in zip(effects, precisions):
        if p and p > 0:
            xs.append(1.0 / p)
            ys.append(e / p)
    n = len(xs)
    if n < 3:
        return {
            "intercept": None,
            "p": None,
            "n": n,
            "reliable": False,
            "asymmetric": None,
            "note": "研究数 <3，无法做 Egger 回归",
        }
    mx, my = _mean(xs), _mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    slope = sxy / sxx if sxx > 0 else 0.0
    intercept = my - slope * mx
    # 残差标准误
    ssr = sum((y - (intercept + slope * x)) ** 2 for x, y in zip(xs, ys))
    dof = max(1, n - 2)
    s2 = ssr / dof
    se_int = math.sqrt(s2 * (1.0 / n + (mx**2) / sxx)) if sxx > 0 else float("inf")
    z = abs(intercept) / se_int if se_int and se_int > 0 else 0.0
    # 双侧正态 p（近似）
    p = math.erfc(z / math.sqrt(2.0))
    return {
        "intercept": round(intercept, 4),
        "slope": round(slope, 4),
        "se_intercept": round(se_int, 4) if math.isfinite(se_int) else None,
        "z": round(z, 3),
        "p": round(p, 4),
        "n": n,
        "reliable": n >= 10,
        "asymmetric": (p < 0.05) if n >= 10 else None,
        "note": "" if n >= 10 else "研究数 <10：p 值不可靠，仅作提示",
    }


def publication_bias_probe(labels, *, alpha=0.05):
    """labels: [(effect, precision), ...]；偏倚显著则建议参照层不得作为阈值来源。"""
    effects = [x[0] for x in labels]
    precisions = [x[1] for x in labels]
    egg = egger_test(effects, precisions)
    if egg["asymmetric"] is True:
        suggestion = (
            "检测到发表偏倚（Egger p=%.3f<%.2f）：该端点参照分位"
            "不得作为 PASS/FAIL 数值阈值来源，只能作定性背景" % (egg["p"], alpha)
        )
    elif egg["asymmetric"] is False:
        suggestion = (
            "未检测到显著发表偏倚（Egger p=%.3f）；参照层可用但须声明来源" % egg["p"]
        )
    else:
        suggestion = "研究数不足或不适用，无法判定发表偏倚：" + egg["note"]
    return {"egger": egg, "suggestion": suggestion}
