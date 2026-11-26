# -*- coding: utf-8 -*-
"""统计推断工具（评审 v4.0，P2 / L1-2）：精确二项 CI 与注册门。

依赖 scipy（运行时已具备）；缺少时回退到一个保守的 Wilson 近似，保证可用性。
"""

import math

try:
    from scipy import stats as _stats

    _HAS_SCIPY = True
except Exception:  # pragma: no cover
    _HAS_SCIPY = False


def clopper_pearson_ci(k, n, alpha=0.05):
    """精确 Clopper-Pearson 二项 CI，返回 (lo, hi)，区间端点 ∈[0,1]。

    k = 观测"失败/未通过"数；n = 样本量；alpha = I 类水平（默认 0.05 → 95% CI）。
    当 k=0 时下界为 0；k=n 时上界为 1（单边极限）。
    """
    if n <= 0:
        return (0.0, 1.0)
    if _HAS_SCIPY:
        lo = 0.0 if k == 0 else _stats.beta.ppf(alpha / 2.0, k, n - k + 1)
        hi = 1.0 if k == n else _stats.beta.ppf(1.0 - alpha / 2.0, k + 1, n - k)
        return (float(lo), float(hi))
    # 回退：Wilson 近似（保守度略低，仅用于无 scipy 环境）
    p = k / float(n)
    z = 1.959963984540054
    denom = 1.0 + z * z / n
    center = (p + z * z / (2.0 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4.0 * n * n))) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def registration_gate(observed, n, tol=0.05, alpha=0.05):
    """F1 注册门（评审 v4.0，P2）：判定改为置信区间判据。

    门过线条件：**Clopper-Pearson 95% CI 上界 ≤ tol（默认 5%）**。
    返回必须携带 n / observed_rate / ci_upper，使"点估计过线"升级为"有统计把握地不过线"。
    """
    if n <= 0:
        return dict(
            n=0,
            observed_rate=None,
            ci_lower=0.0,
            ci_upper=1.0,
            passes=False,
            note="n=0",
        )
    lo, hi = clopper_pearson_ci(observed, n, alpha)
    rate = observed / float(n)
    return dict(
        n=n,
        observed_rate=round(rate, 6),
        ci_lower=round(lo, 6),
        ci_upper=round(hi, 6),
        passes=bool(hi <= tol),
        note=(
            ("CI 上界≤%g，有统计把握地不过线" % tol)
            if hi <= tol
            else ("CI 上界=%g>%g，不能宣称通过（需更大 n）" % (hi, tol))
        ),
    )


def gate_pass_probability(
    p_true, n_grid=(20, 50, 100, 200, 1000), tol=0.05, alpha=0.05
):
    """P2 设计端分析：给定真实失败率 p_true，注册门在各 n 下的*通过概率*。

    通过 = 一次 Binomial(n, p_true) 抽样得到的观测 k 满足 clopper_pearson_ci(k,n) 上界 ≤ tol。
    返回 {n: 通过概率}。用于论证"CI 化后通过 5% 门需 n≳60"，以及小源系统性的构成偏差。
    需要 scipy.stats.binom；无 scipy 时返回空字典并标注。
    """
    if not _HAS_SCIPY:
        return {}
    out = {}
    for n in n_grid:
        if n <= 0:
            continue
        prob = 0.0
        for k in range(0, n + 1):
            lo, hi = clopper_pearson_ci(k, n, alpha)
            if hi <= tol:
                prob += _stats.binom.pmf(k, n, p_true)
        out[n] = round(float(prob), 4)
    return out


# ---- R05（评审 C5）：相关检验的功效报告 -------------------------------------
# 评审原话："要求'CI 下界>0'等价于在 α=0.05 水平做相关检验。n=14 时对中等相关
# （ρ≈0.5）的功效不足 50%……一个以严谨统计为卖点的框架，其独立性模块在小样本下近乎失明。"
# 处置：把功效显式算出来并**拒绝静默出权重**（见 independence.assess_pair）。
def correlation_power_report(n, alpha=0.05, power_target=0.8):
    """给定配对数 n，报告可检出下限与若干典型 ρ 的功效。"""
    from adt.independence import correlation_power, min_detectable_rho

    grid = (0.2, 0.3, 0.5, 0.7, 0.9)
    return {
        "n_pairs": n,
        "alpha": alpha,
        "power_target": power_target,
        "min_detectable_rho": (
            None
            if n is None or n <= 3
            else round(min_detectable_rho(n, alpha, power_target), 3)
        ),
        "power_by_rho": {
            str(r): round(correlation_power(n, r, alpha), 3) for r in grid
        },
        "verdict": (
            "insufficient" if n is None or n < 20 else "weak" if n < 60 else "adequate"
        ),
        "note": "Fisher z 双侧检验；n<20 时禁止输出收缩权重（structural: sample_size）",
    }


# ---------------------------------------------------------------------------
# P2.4（2026-11-03 评审）：区间估计补齐
#
# 为什么需要：红线 7 的判据从"点估计与约定值比较"改成"必须给 95% CI"之后，
# 仓库里必须有**能算 CI 的函数**，否则红线会变成"要求一个没人能提供的字段"。
# 本段提供四个：AUC 的 bootstrap CI、比例的 Wilson CI、两比例差的 Newcombe CI、
# 以及**配对**细胞计数的 bootstrap 差值 CI（用于 Ames 双方法层这种同批分子两套判读）。
# ---------------------------------------------------------------------------
import random


def auc_bootstrap_ci(y_true, scores, n_boot=2000, alpha=0.05, seed=20261103):
    """AUC 的 percentile bootstrap 95% CI（固定种子，可复现）。

    为什么用 bootstrap 而不是 DeLong：DeLong 需要 per-sample 分数与真值的完整配对；
    bootstrap 只需要同一份输入，且对非正态、类别不平衡更稳健。代价是慢（n_boot 次重抽）。
    若将来 `gate_audit` 落盘 per-sample 分数，可直接改调本函数。

    返回 dict(auc, lo, hi, n_boot, n, n_pos, n_neg)。
    """
    pairs = [(float(s), int(y)) for s, y in zip(scores, y_true)]
    n = len(pairs)
    n_pos = sum(1 for _, y in pairs if y == 1)
    n_neg = n - n_pos
    if n == 0 or n_pos == 0 or n_neg == 0:
        return dict(
            auc=None,
            lo=None,
            hi=None,
            n=n,
            n_pos=n_pos,
            n_neg=n_neg,
            note="单一类别或空样本：AUC 无定义",
        )

    def _auc(ps):
        pos = [s for s, y in ps if y == 1]
        neg = [s for s, y in ps if y == 0]
        if not pos or not neg:
            return None
        # 秩和等价式：正样本得分高于负样本的比例（平局记 0.5）
        wins = 0.0
        for p in pos:
            for q in neg:
                wins += 1.0 if p > q else (0.5 if p == q else 0.0)
        return wins / (len(pos) * len(neg))

    point = _auc(pairs)
    rng = random.Random(seed)
    vals = []
    for _ in range(int(n_boot)):
        samp = [pairs[rng.randrange(n)] for _ in range(n)]
        v = _auc(samp)
        if v is not None:
            vals.append(v)
    if not vals:
        return dict(
            auc=point,
            lo=None,
            hi=None,
            n=n,
            n_pos=n_pos,
            n_neg=n_neg,
            note="重抽全部退化（样本过小）",
        )
    vals.sort()
    lo = vals[int((alpha / 2) * len(vals))]
    hi = vals[min(len(vals) - 1, int((1 - alpha / 2) * len(vals)))]
    return dict(
        auc=point,
        lo=lo,
        hi=hi,
        n_boot=len(vals),
        n=n,
        n_pos=n_pos,
        n_neg=n_neg,
        method="percentile bootstrap",
    )


def wilson_ci(k, n, alpha=0.05):
    """比例的 Wilson score 区间（小样本优于 Wald）。"""
    if n <= 0:
        return dict(p=None, lo=None, hi=None)
    from math import sqrt

    z = _z(alpha)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    lo = max(0.0, centre - half)
    hi = min(1.0, centre + half)
    # 数值卫生：k=0 / k=n 时 Wilson 端点理论上恰好是 0 / 1，浮点会留下 2.8e-17 这类
    # 残渣。留着它会让 `wilson_ci(0,n)["lo"] == 0.0` 为假，也会在报告里印出
    # "0.00000000000000003"——既难看又让人以为算错。
    if lo < 1e-12:
        lo = 0.0
    if hi > 1.0 - 1e-12:
        hi = 1.0
    return dict(p=p, lo=lo, hi=hi, n=n, k=k)


def _z(alpha):
    """双侧 alpha → z。

    2026-11-03 修 bug：此前是一张 4 值查表 + `table.get(..., 1.9599)` 兜底，
    于是 alpha=0.05/3=0.0167 会**静默退回 1.96**，算出与 95% 完全相同的"校正后区间"——
    一个本该更宽的区间只是看起来没变，等于在校正声明上撒谎。
    现在改为标准库正态分位数（`statistics.NormalDist`），任意 alpha 都精确。
    """
    import statistics

    alpha = min(max(float(alpha), 1e-12), 0.999999)
    return statistics.NormalDist().inv_cdf(1.0 - alpha / 2.0)


def newcombe_diff_ci(k1, n1, k2, n2, alpha=0.05):
    """两独立比例之差的 Newcombe hybrid score 区间。

    **注意**：若两臂是同一批分子（配对），本区间会偏保守（忽略配对相关性）；
    有配对细胞计数时应改调 `paired_bootstrap_diff_ci`。
    """
    a, b = wilson_ci(k1, n1, alpha), wilson_ci(k2, n2, alpha)
    if a["p"] is None or b["p"] is None:
        return dict(diff=None, lo=None, hi=None)
    d = a["p"] - b["p"]
    lo = d - ((a["p"] - a["lo"]) ** 2 + (b["hi"] - b["p"]) ** 2) ** 0.5
    hi = d + ((a["hi"] - a["p"]) ** 2 + (b["p"] - b["lo"]) ** 2) ** 0.5
    return dict(diff=d, lo=lo, hi=hi, method="Newcombe hybrid score (independent)")


def paired_bootstrap_diff_ci(cells, stat_fn, n_boot=10000, alpha=0.05, seed=20261103):
    """配对细胞计数的 bootstrap：cells = [(w, payload), ...]，w 为该细胞分子数。

    用途（Ames 双方法层）：同一批分子有"只看统计模型"与"统计+专家规则"两套判读，
    要估 release_error_rate 的差值 CI。我们没有逐分子记录，但有**细胞计数**：
        两法都放行 & 真致突变 : 40
        两法都放行 & 非突变   : 186
        仅统计法放行 & 真突变 : 116
        仅统计法放行 & 非突变 : 239
    按分子多项式重抽（每轮抽 n 个分子，按其细胞归属计数），再重算两臂比率与差值。
    这是**配对**bootstrap，优于把两臂当独立比例的 Newcombe 区间。

    返回 dict(diff, lo, hi, n, n_boot, point_arms=[a,b])。
    """
    rng = random.Random(seed)
    total = sum(w for w, _ in cells)
    if total == 0:
        return dict(diff=None, lo=None, hi=None, n=0)
    weights = [w for w, _ in cells]

    def _one(counts):
        payloads = [p for _, p in cells]
        return stat_fn(list(zip(counts, payloads)))

    point_counts = list(weights)
    point = _one(point_counts)
    vals = []
    for _ in range(int(n_boot)):
        counts = [0] * len(cells)
        for _i in range(total):
            r = rng.random() * total
            acc = 0.0
            for j, w in enumerate(weights):
                acc += w
                if r <= acc:
                    counts[j] += 1
                    break
            else:
                counts[-1] += 1
        try:
            v = _one(counts)
        except ZeroDivisionError:
            continue
        if v is not None:
            vals.append(v)
    if not vals:
        return dict(diff=point, lo=None, hi=None, n=total, n_boot=0)
    vals.sort()
    return dict(
        diff=point,
        lo=vals[int((alpha / 2) * len(vals))],
        hi=vals[min(len(vals) - 1, int((1 - alpha / 2) * len(vals)))],
        n=total,
        n_boot=len(vals),
        method="paired cell bootstrap",
    )


def holm(pvals, alpha=0.05):
    """Holm–Bonferroni 逐步法（控制族错误率 FWER）。

    为什么必须有它：本包会同时报告多个端点的 p 值（hERG / DILI / BBB_Martins），
    然后在正文里说"门在某些端点上有效"。**一旦这句话是"某些"，检验就不再是
    单次检验，而是 3 次检验里挑最好的一次报出来**——这正是多重比较。
    不校正就报 0.0267，等于把"3 次机会"当"1 次机会"卖。

    返回 list[dict]，按**原始 p 值升序**排列，字段：
      idx  原序列下标；p 原始 p；adj 校正后 p（与同族比较，单调不减）；
      reject 是否在 alpha 下显著；note 说明。

    用法：
        r = holm([0.0267, 0.7554, 1.0], alpha=0.05)
        # r[0] -> idx=0, p=0.0267, adj=0.0801, reject=False
    """
    items = [
        {"idx": i, "p": (float(p) if p is not None else None)}
        for i, p in enumerate(pvals)
    ]
    valid = [it for it in items if it["p"] is not None]
    m = len(valid)
    valid.sort(key=lambda it: it["p"])
    running = 0.0
    for rank, it in enumerate(valid):
        adj = it["p"] * (m - rank)
        running = max(running, adj)  # Holm 的单调化：adj 不得下降
        it["adj"] = round(min(1.0, running), 6)
        it["reject"] = bool(it["adj"] <= alpha)
        it["rank"] = rank + 1
        it["note"] = "m=%d 次比较中的第 %d 小 p；adj = max(前一步, p×(m-rank+1))" % (
            m,
            rank + 1,
        )
    for it in items:
        if it["p"] is None:
            it["adj"] = None
            it["reject"] = False
            it["note"] = "p 缺失，不参与校正"
    return {
        "alpha": alpha,
        "m": m,
        "family": valid,
        "familywise_any_reject": any(it["reject"] for it in valid),
        "sentence": (
            "m=%d 次比较，Holm 校正后%s达到 alpha=%.2f"
            % (m, "有" if any(it["reject"] for it in valid) else "**无一项**", alpha)
        ),
    }
