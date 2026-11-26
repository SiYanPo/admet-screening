# -*- coding: utf-8 -*-
"""配对数据的正确等效性检验（C10 / B4 修复，2026-11-04）。

`adt/mmp.py::_tost` 把同一批 MMP 对的**两个比例**当独立样本、用 Wald SE，
忽略配对协方差。本模块提供逐 MMP 对差值的 bootstrap TOST（以及符号检验的
连续性校正版本），供生产结论替换使用。

设计要点（对应报告 B4 与 §5.1「半真」复审）：
- 输入是**逐对差值** `diffs`（长度 = MMP 对数），不是两个比例的计数；
- 等效界 `margin` 必须在看数据前基于最小有意义差异固定并第三方存证，
  见 references/EQUIVALENCE_MARGIN_PREREG.md —— 本模块**不接受事后扫描出的界**；
- 多次 TOST（by_kind / 4 打分器）必须调用方施加 Holm 校正；
- 返回 `inferential_use_allowed`：仅当等效界已预注册冻结且 n_pairs 达功效门槛时
  为 True，否则为 False（防止「修好方差但等效界仍 post-hoc」的半真修复）。
"""

from __future__ import annotations

import math


def paired_tost(
    diffs,
    margin,
    alpha=0.05,
    reps=4000,
    seed=20261104,
    margin_preregistered=False,
    min_pairs=None,
):
    """逐对差值 bootstrap TOST。

    diffs : 每个 MMP 对的 (模型翻转 − 标签翻转) 之类配对差，可含 0/1/连续值
    margin: 等效界（>0）
    返回 dict，含 d / ci90 / equivalent / n_pairs / se_bootstrap / warnings。
    """
    import random

    vals = [float(x) for x in diffs if x is not None]
    n = len(vals)
    out = dict(
        n_pairs=n,
        margin=float(margin),
        alpha=float(alpha),
        method="paired_bootstrap_tost",
        seed=int(seed),
    )
    if n < 2 or margin <= 0:
        out.update(
            equivalent=False,
            inferential_use_allowed=False,
            warnings=["无有效配对差或等效界非正：拒绝下结论"],
        )
        return out
    d = sum(vals) / float(n)
    rng = random.Random(int(seed))
    means = []
    for _ in range(int(reps)):
        means.append(sum(vals[rng.randrange(n)] for _ in range(n)) / float(n))
    means.sort()
    lo = means[int(0.05 * (reps - 1))]  # 90% CI（TOST 用 1-2alpha）
    hi = means[int(0.95 * (reps - 1))]
    se = (sum((m - d) ** 2 for m in means) / float(max(1, reps - 1))) ** 0.5
    equivalent = bool(lo > -margin and hi < margin)
    warnings = []
    if not margin_preregistered:
        warnings.append(
            "等效界未在看数据前冻结并第三方存证：结论仍属 post-hoc（§5.1 B4）"
        )
    if min_pairs is not None and n < min_pairs:
        warnings.append(
            "n_pairs=%d < min_pairs=%d：功效不足，不得判 equivalent" % (n, min_pairs)
        )
        equivalent = False
    out.update(
        d=round(d, 6),
        ci90=[round(lo, 6), round(hi, 6)],
        se_bootstrap=round(se, 6),
        equivalent=equivalent,
        inferential_use_allowed=bool(margin_preregistered and not warnings),
        warnings=warnings,
    )
    return out


def sign_z_continuous(k, n, continuity=True):
    """符号检验 z，带连续性校正；功效门槛必须用 sign_n（非 n_pairs）。"""
    if n <= 0:
        return 0.0
    kk = (k - 0.5) if (continuity and k > n / 2.0) else ((k + 0.5) if continuity else k)
    return (kk - n / 2.0) / math.sqrt(n / 4.0)


def holm(pvals, alpha=0.05):
    """Holm 逐步降 FWER 控制；返回与输入等长的 reject 布尔列表。"""
    m = len(pvals)
    order = sorted(range(m), key=lambda i: pvals[i])
    out = [False] * m
    for rank, i in enumerate(order):
        if pvals[i] <= alpha / float(m - rank):
            out[i] = True
        else:
            break
    return out


# ---------------------------------------------------------------------------
# 同行评审 §6 Phase 2（B20）：DeLong / McNemar 配对检验
# ---------------------------------------------------------------------------
def _norm_sf(z):
    """标准正态上尾概率（erfc 实现，免 scipy）。"""
    return 0.5 * math.erfc(z / math.sqrt(2.0))


def mcnemar(b, c, *, alpha=0.05, exact=True):
    """配对二分类的 McNemar 检验：b=甲对乙错，c=乙对甲错。

    报告 §6 Phase 2 要求配对比较用 McNemar + Holm。exact=True 用二项精确
    检验（discordant 小样本正确），否则用卡方近似 + 连续性校正。
    返回 dict(p, significant, b, c, n_discordant, method)。
    """
    n = b + c
    if n == 0:
        return dict(
            p=1.0,
            significant=False,
            b=b,
            c=c,
            n_discordant=0,
            method="mcnemar_exact" if exact else "mcnemar_chi2",
            note="无不一致对，无法区分两模型",
        )
    if exact:
        k = min(b, c)
        # 双侧精确二项：P(X<=k) under Bin(n, 0.5)
        p = sum(math.comb(n, i) for i in range(k + 1)) / (2.0**n)
        p = min(1.0, 2.0 * p)
        method = "mcnemar_exact"
    else:
        chi2 = ((abs(b - c) - 1) ** 2) / float(n) if n else 0.0
        p = 2.0 * _norm_sf(math.sqrt(chi2)) if chi2 > 0 else 1.0
        method = "mcnemar_chi2_cc"
    return dict(
        p=round(p, 6), significant=p < alpha, b=b, c=c, n_discordant=n, method=method
    )


def delong(scores_a, scores_b, labels):
    """两个相关 ROC 曲线 AUROC 差异的 DeLong 检验（结构分量法，免 scipy）。

    DeLong et al. 1988：对每个样本算结构分量
      V10_i = (1/n_n) Σ_j ψ(X_i,Y_j)   （正类样本 i）
      V01_j = (1/n_p) Σ_i ψ(X_i,Y_j)   （负类样本 j）
    其中 ψ(X,Y)=I(X>Y)+0.5·I(X=Y)。两曲线差的方差 =
      Var(dV10)/n_p + Var(dV01)/n_n（样本方差，无偏）。
    Z=(AUC_a−AUC_b)/sqrt(Var) 近似 N(0,1)。

    O(n_p·n_n) 直接算 ψ——对基准比较规模（数千）足够，且避免 midrank 公式易错。
    大样本（>5000/组）建议改 rank 优化或 bootstrap CI 交叉核对。
    """
    labels = list(labels)
    sa, sb = list(scores_a), list(scores_b)
    n_p = sum(1 for y in labels if y == 1)
    n_n = len(labels) - n_p
    if n_p == 0 or n_n == 0 or len(sa) != len(labels) or len(sb) != len(labels):
        return dict(
            auc_a=None,
            auc_b=None,
            delta=None,
            z=None,
            p=1.0,
            significant=False,
            method="delong",
            note="输入无效或单类别，无法检验",
        )

    pos = [i for i, y in enumerate(labels) if y == 1]
    neg = [i for i, y in enumerate(labels) if y == 0]

    def _psi(x, y):
        return 1.0 if x > y else (0.5 if x == y else 0.0)

    def _auc_and_v(scores):
        auc = sum(_psi(scores[i], scores[j]) for i in pos for j in neg) / (n_p * n_n)
        v10 = [sum(_psi(scores[i], scores[j]) for j in neg) / n_n for i in pos]
        v01 = [sum(_psi(scores[i], scores[j]) for i in pos) / n_p for j in neg]
        return auc, v10, v01

    auc_a, v10a, v01a = _auc_and_v(sa)
    auc_b, v10b, v01b = _auc_and_v(sb)
    d10 = [x - y for x, y in zip(v10a, v10b)]
    d01 = [x - y for x, y in zip(v01a, v01b)]

    def _svar(v):
        if len(v) < 2:
            return 0.0
        m = sum(v) / len(v)
        return sum((x - m) ** 2 for x in v) / (len(v) - 1)

    var = _svar(d10) / n_p + _svar(d01) / n_n
    delta = auc_a - auc_b
    degenerate = var <= 0 and delta != 0
    z = (delta / math.sqrt(var)) if var > 0 else (0.0 if delta == 0 else math.inf)
    p = 2.0 * _norm_sf(abs(z)) if math.isfinite(z) else 0.0
    # 方差退化（完美分离 / 一方常数）时 DeLong 的 p 不可信——标出来，
    # 强制要求 bootstrap CI 交叉核对，不把 p=0 当"证实显著"。
    if degenerate:
        note = (
            "结构分量方差为 0（完美分离或某方打分恒定），DeLong 正态近似退化，"
            "p=0 不可单独采信；必须用 bootstrap CI 交叉核对"
        )
    else:
        note = "大样本正态近似；O(n_p·n_n) 结构分量，小样本建议 bootstrap CI 交叉核对"
    return dict(
        auc_a=round(auc_a, 6),
        auc_b=round(auc_b, 6),
        delta=round(delta, 6),
        z=(round(z, 4) if math.isfinite(z) else None),
        p=(None if degenerate else round(p, 6)),
        significant=(False if degenerate else p < 0.05),
        degenerate=degenerate,
        method="delong",
        note=note,
    )
