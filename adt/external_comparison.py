# -*- coding: utf-8 -*-
"""统计模块的外部对照（G14 的数据面）。

## 为什么需要这个模块

本仓库连续三轮出现过同一类事故：**selftest 全绿，但实现是错的**。

| 轮次 | 缺陷 | 为什么 selftest 没抓到 |
|---|---|---|
| 1 | t 分布自由度用了 n 而不是 n-2 | selftest 只断言"p 在 (0,1) 内" |
| 1 | Holm 校正按 zip 顺序回填而非原下标 | selftest 只测了已排序的 p |
| 2 | OOT 基线把待检尾部算进基线（SD 膨胀 30×） | selftest 只测了"给了 history"的分支 |

三次的共同结构：**自测与实现出自同一个心智模型，模型错了两边一起错**。唯一能
打破这个闭环的是"另一个来源的实现"——scipy / 教科书闭式 / 仓库内另一处独立实现。

所以本模块不做"再写一遍 selftest"，而是把每个统计量同时算两遍：
  * ours = 仓库里真正被门禁/报告调用的那个函数；
  * ref  = 本文件内**另行写出**的参考实现（用 scipy 或教科书闭式，不 import 被测函数）。
两者逐点比较，记录最大绝对偏差。偏差超过容差 → G14 blocker，`release-check` 不放行。

## 边界（不要高估它）

- 它证明的是"我们的实现在这些固定用例上与参考实现一致"，**不是**"统计假设成立"。
- 它不覆盖数据面（样本是否可交换、标签是否泄漏），那是 G12/EDAG 的事。
- 参考实现若与被测实现同源于同一篇论文的同一条公式，公式层面的误解无法被发现；
  所以 G14 同时要求每个模块有一份**独立审查报告**（人写的、含对抗探针）。
"""

from __future__ import annotations

import math

try:
    from scipy import stats as _sp

    HAS_SCIPY = True
except Exception:  # pragma: no cover - 无 scipy 时相关条目跳过（G14 降为 warn）
    _sp = None
    HAS_SCIPY = False

# 默认容差：浮点闭式对齐，1e-9 已远宽于实际误差（实测 1e-15 量级）
DEFAULT_TOL = 1e-9
# 分类量（判据/拒绝与否）用精确相等，偏差只可能是 0 或 1
CATEGORICAL_TOL = 0.0


# ---------------------------------------------------------------- 参考实现
# 以下函数刻意不 import adt 里的任何被测模块。


def _ref_z(alpha):
    """标准正态上 alpha/2 分位（stdlib，避免依赖 scipy 的 norm）。"""
    from statistics import NormalDist

    return NormalDist().inv_cdf(1.0 - alpha / 2.0)


def ref_clopper_pearson(k, n, alpha=0.05):
    if n <= 0:
        return (0.0, 1.0)
    lo = 0.0 if k == 0 else float(_sp.beta.ppf(alpha / 2.0, k, n - k + 1))
    hi = 1.0 if k == n else float(_sp.beta.ppf(1.0 - alpha / 2.0, k + 1, n - k))
    return (lo, hi)


def ref_wilson(k, n, alpha=0.05):
    if n <= 0:
        return (0.0, 1.0)
    z = _ref_z(alpha)
    p = k / float(n)
    denom = 1.0 + z * z / n
    center = (p + z * z / (2.0 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4.0 * n * n)) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def ref_newcombe(k1, n1, k2, n2, alpha=0.05):
    """Newcombe 混合 score 差分区间（Method 10）。"""
    l1, u1 = ref_wilson(k1, n1, alpha)
    l2, u2 = ref_wilson(k2, n2, alpha)
    p1, p2 = k1 / float(n1), k2 / float(n2)
    d = p1 - p2
    lo = d - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2)
    hi = d + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2)
    return (lo, hi)


def ref_holm_reject(pvals, alpha=0.05):
    """Holm 逐步降：按升序比较 p_(rank) <= alpha/(m-rank)。返回原序布尔表。"""
    m = len(pvals)
    order = sorted(range(m), key=lambda i: pvals[i])
    out = [False] * m
    for rank, i in enumerate(order):
        if pvals[i] <= alpha / float(m - rank):
            out[i] = True
        else:
            break
    return out


def ref_t_p_two_sided(r, n):
    """Pearson r 的双尾 p：t = r*sqrt(df/(1-r^2))，df = n-2，用 scipy 的 t.sf。"""
    if r is None or n < 3 or abs(r) >= 1:
        return None
    df = n - 2
    t = abs(r) * math.sqrt(df / (1.0 - r * r))
    return float(2.0 * _sp.t.sf(t, df))


def ref_oot_prefix(series, n_consecutive=5, k=2.0):
    """OOT 判据的独立复算：基线只取**待检尾部之前**的前缀。"""
    vals = [float(v) for v in series]
    tail = vals[-n_consecutive:]
    prefix = vals[:-n_consecutive]
    if len(prefix) < 2:
        return "INDETERMINATE"
    m = sum(prefix) / len(prefix)
    sd = math.sqrt(sum((x - m) ** 2 for x in prefix) / (len(prefix) - 1))
    if sd == 0:
        return "IN_CONTROL"
    above = all(v > m + k * sd for v in tail)
    below = all(v < m - k * sd for v in tail)
    return "OOT" if (above or below) else "IN_CONTROL"


# ---------------------------------------------------------------- 用例与驱动

_CLOPPER = [(0, 20), (5, 20), (109, 132), (1, 10), (132, 132), (17, 40)]
_WILSON = [(0, 20), (5, 20), (109, 132), (1, 10), (132, 132), (17, 40)]
_NEWCOMBE = [(109, 132, 97, 132), (5, 20, 3, 20), (0, 20, 20, 20)]
_HOLM = [
    [0.0267, 0.7554, 1.0],
    [0.01, 0.02, 0.03, 0.04, 0.05],
    [0.5],
    [0.049, 0.049, 0.049],
    [0.001, 0.9, 0.9, 0.9],
]
_T = [(0.8, 5), (0.3, 30), (-0.95, 10), (0.0, 12), (0.99, 500)]
_OOT = [
    [
        10.0,
        10.1,
        9.9,
        10.2,
        9.8,
        10.0,
        10.1,
        9.9,
        10.0,
        10.2,  # 基线 ~10
        13.0,
        13.2,
        13.1,
        13.3,
        12.9,
    ],  # 尾部整体上移
    [
        10.0,
        10.1,
        9.9,
        10.2,
        9.8,
        10.0,
        10.1,
        9.9,
        10.0,
        10.2,
        10.1,
        9.9,
        10.0,
        10.2,
        10.05,
    ],  # 尾部与基线同分布
    [
        5.0,
        5.05,
        4.95,
        5.02,
        4.98,
        5.01,
        4.99,
        5.0,
        5.03,
        4.97,
        3.0,
        3.02,
        3.01,
        2.99,
        3.03,
    ],  # 尾部整体下移
]


def _entry(
    module, statistic, reference, deviation, tolerance, n_points, note="", skipped=None
):
    return {
        "module": module,
        "statistic": statistic,
        "reference": reference,
        "n_points": n_points,
        "max_abs_deviation": deviation,
        "tolerance": tolerance,
        "skipped": skipped,
        "passed": bool(
            skipped is None and deviation is not None and deviation <= tolerance + 1e-15
        ),
        "note": note,
    }


def run(alpha=0.05):
    """跑全部对照，返回 {entries, skipped, all_passed, n_points}。

    不写盘、不依赖外部数据：纯函数，可在门禁里每个 release 跑一次。
    """
    from . import stats_ci, evidence_streams, deviation, paired_stats

    entries = []

    # 1) Clopper-Pearson
    if not HAS_SCIPY:
        entries.append(
            _entry(
                "stats_ci.clopper_pearson_ci",
                "二项精确区间端点",
                "scipy.stats.beta.ppf",
                None,
                DEFAULT_TOL,
                len(_CLOPPER),
                skipped="无 scipy：参考实现不可用",
            )
        )
    else:
        dev = 0.0
        for k, n in _CLOPPER:
            ours = stats_ci.clopper_pearson_ci(k, n, alpha)
            ref = ref_clopper_pearson(k, n, alpha)
            dev = max(dev, abs(ours[0] - ref[0]), abs(ours[1] - ref[1]))
        entries.append(
            _entry(
                "stats_ci.clopper_pearson_ci",
                "二项精确区间端点",
                "scipy.stats.beta.ppf",
                dev,
                DEFAULT_TOL,
                len(_CLOPPER),
            )
        )

    # 2) Wilson
    dev = 0.0
    for k, n in _WILSON:
        ours = stats_ci.wilson_ci(k, n, alpha)  # dict: lo/hi/p/n/k
        ref = ref_wilson(k, n, alpha)
        dev = max(dev, abs(ours["lo"] - ref[0]), abs(ours["hi"] - ref[1]))
    entries.append(
        _entry(
            "stats_ci.wilson_ci",
            "Wilson score 区间端点",
            "闭式 + 正态分位",
            dev,
            DEFAULT_TOL,
            len(_WILSON),
        )
    )

    # 3) Newcombe 差分
    dev = 0.0
    for k1, n1, k2, n2 in _NEWCOMBE:
        ours = stats_ci.newcombe_diff_ci(k1, n1, k2, n2, alpha)  # dict: diff/lo/hi
        ref = ref_newcombe(k1, n1, k2, n2, alpha)
        dev = max(dev, abs(ours["lo"] - ref[0]), abs(ours["hi"] - ref[1]))
    entries.append(
        _entry(
            "stats_ci.newcombe_diff_ci",
            "两比例差分区间",
            "Newcombe Method 10（独立复写）",
            dev,
            DEFAULT_TOL,
            len(_NEWCOMBE),
        )
    )

    # 4) Holm：两个入口（stats_ci 返回 dict，paired_stats 返回布尔表）都要与参考一致
    dev = 0.0
    for pvals in _HOLM:
        ref = ref_holm_reject(pvals, alpha)
        got_b = paired_stats.holm(pvals, alpha)
        # stats_ci.holm 的 family 已按 p 升序重排，需按 idx 还原原序
        restored = [None] * len(pvals)
        for it in stats_ci.holm(pvals, alpha)["family"]:
            restored[it["idx"]] = it["reject"]
        for a, b, r in zip(restored, got_b, ref):
            dev = max(
                dev,
                0.0 if bool(a) == bool(r) else 1.0,
                0.0 if bool(b) == bool(r) else 1.0,
            )
    entries.append(
        _entry(
            "stats_ci.holm / paired_stats.holm",
            "FWER 逐步校正的拒绝集",
            "教科书逐步降（独立复写）",
            dev,
            CATEGORICAL_TOL,
            len(_HOLM),
            note="两处实现必须同时与参考一致；一侧错也会被这条抓到",
        )
    )

    # 5) t 近似双尾 p（上一轮 df 错配事故的永久哨兵）
    if not HAS_SCIPY:
        entries.append(
            _entry(
                "evidence_streams._p_two_sided",
                "相关系数双尾 p",
                "scipy.stats.t.sf",
                None,
                DEFAULT_TOL,
                len(_T),
                skipped="无 scipy：参考实现不可用",
            )
        )
    else:
        dev = 0.0
        for r, n in _T:
            ours = evidence_streams._p_two_sided(r, n)
            ref = ref_t_p_two_sided(r, n)
            dev = max(dev, abs(ours - ref))
        entries.append(
            _entry(
                "evidence_streams._p_two_sided",
                "相关系数双尾 p",
                "scipy.stats.t.sf（df=n-2）",
                dev,
                DEFAULT_TOL,
                len(_T),
            )
        )

    # 6) OOT 基线（上一轮 SD 膨胀 30× 事故的永久哨兵）：分类量，必须逐例同判
    dev = 0.0
    for series in _OOT:
        ours = deviation.detect(series, n_consecutive=5, oot_k=2.0)["verdict"]
        ref = ref_oot_prefix(series, n_consecutive=5, k=2.0)
        dev = max(dev, 0.0 if ours == ref else 1.0)
    entries.append(
        _entry(
            "deviation.detect(OOT)",
            "连续 n 点偏离基线 k·SD 的判定",
            "独立复算前缀基线（不含待检尾部）",
            dev,
            CATEGORICAL_TOL,
            len(_OOT),
            note="不给 history 时必须用前缀；含尾部会把 SD 撑大而漏报",
        )
    )

    n_points = sum(e["n_points"] for e in entries)
    return {
        "alpha": alpha,
        "entries": entries,
        "n_points": n_points,
        "has_scipy": HAS_SCIPY,
        "skipped": [e["module"] for e in entries if e["skipped"]],
        "all_passed": all(e["passed"] for e in entries),
    }


def selftest():
    """返回 (ok, 明细行)。任何一条偏差超容差即 False。"""
    r = run()
    rows = []
    for e in r["entries"]:
        rows.append(
            {
                "name": e["module"],
                "ok": e["passed"],
                "detail": (
                    ("skipped: %s" % e["skipped"])
                    if e["skipped"]
                    else "max|Δ|=%.3g ≤ tol %.0e（%d 点）"
                    % (e["max_abs_deviation"], e["tolerance"], e["n_points"])
                ),
            }
        )
    return r["all_passed"], rows


# ---------------------------------------------------------------------------
# 同行评审 §5 对照缺口（B11）：external_comparison 的对照范围声明
# ---------------------------------------------------------------------------
def scope_declaration():
    """明确 external_comparison 对照的是统计实现，不是模型性能。

    报告 §5："external_comparison 只对照统计实现，不对照模型性能"——这是事实，
    但旧材料可能把它当"已做外部基准"引用。本声明把边界固化成可引用产物：
    真正对照模型性能的是 benchmark / ablate / prospect 命令（需真值）。
    """
    return {
        "compares": "statistical_implementation_equivalence",
        "reference_examples": [
            "scipy.stats.beta.ppf (Clopper-Pearson)",
            "Wilson / Newcombe / Holm / t-test / OOT 参考实现",
        ],
        "does_not_compare": "model_predictive_performance",
        "performance_comparison_commands": ["benchmark", "ablate", "prospect"],
        "performance_requires": "external truth labels (--truth / real_truth_legs)",
        "statement": (
            "external_comparison 的 G14 对照只证明本仓库统计实现与参考实现数值一致，"
            "不构成'模型在外部数据上优于 baseline'的证据。性能主张须引用 benchmark/"
            "ablate/prospect 在真值上的实测结果，并带分割与置信区间。"
        ),
    }


if __name__ == "__main__":  # pragma: no cover
    ok, rows = selftest()
    for r in rows:
        print(
            ("  ok  " if r["ok"] else "  FAIL") + " %-42s %s" % (r["name"], r["detail"])
        )
    print("ALL OK" if ok else "FAILED")
    raise SystemExit(0 if ok else 1)
