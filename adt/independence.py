# -*- coding: utf-8 -*-
"""工作包 A：把"两票半"从工程断言变成可检验的独立性假设 + 校准计票。

背景（外部评审意见，2026-10-29）：
  `require_sources=2` 原先是一个无参数断言。审稿人会问：为什么是 2？
  两票一致时的错误率是多少？同组两源真的独立吗？
  OneADMET（JMC 2026）已指出"多平台 ≠ 多来源"——很多 Web 服务反复使用
  Tox21/TDC/2000–2015 经典数据集，相近结论不等于多份独立证据。

本模块提供三件事，全部**只做度量与报告，不改动裁决结论**（避免静默改变历史结果）：
  1) pairwise_stats     同组/跨组源对的 Spearman ρ、平均绝对差、分歧率
  2) group_summary      组内冗余度 -> 组权重（ρ>0.9 降为半票，0.7–0.9 线性降权）
  3) vote_calibration   "k 票阳性 -> 错误率 u(k)"经验校准表
     （**文献归属 2026-11-03 查 Clark 2014 原文后修正**：
      `u=(err+0.5)/(n+1)` 是 Jeffreys/Laplace 伪计数平滑（Jeffreys 1946；Agresti & Coull 1998），
      为公式的**真实起源**。Clark 2014（Clark RD et al., J Cheminform 2014;6:34,
      doi:10.1186/1758-2946-6-34）在其「按票数校准分类不确定性」协议第 7 步明确使用
      「prediction tally +1 / error count +0.5」的连续性修正，即本式——故 Clark 2014
      是 ADMET/QSAR 投票不确定性语境下该平滑的**合法次级引用**（已查原文 PDF 核实）。
      但 Clark 2014 的主方法是 beta-binomial 拟合 u(k)=ER·f(k)/g(k)，本包**未实现**该拟合，
      只用了更简单的伪计数经验率；不得声称「实现了 Clark 2014 方法」（那才是引用 laundering）。）
      （Jeffreys 平滑；仅在同批有实测真值时可用，且须标注 in-sample）

设计纪律：
  - 相关性/校准只在**同一端点内**计算，绝不跨端点混合（量纲不同）。
  - 样本不足（n<3 对 / 某 k 的 n<5）显式标 insufficient，不硬给数。
  - 任何降权都写进独立产物，不偷偷改 reliability.csv 的 verdict。
"""

import math

try:
    import numpy as np  # noqa: F401  (仅用于可选加速；核心实现是纯 Python)
except Exception:  # pragma: no cover
    np = None

IN_DOMAIN = {"predicted", "measured", "saturated"}
UNIT_PROB = {"probability", "fraction"}
UNIT_CLASS = {"class", "class_0_1", "binary"}


def _f(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _unit_kind(unit):
    u = (unit or "").strip().lower()
    if u in UNIT_PROB:
        return "prob"
    if u in UNIT_CLASS:
        return "class"
    return "other"


def _rank(vals):
    """平均秩（处理并列），1-based。"""
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    ranks = [0.0] * len(vals)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
            j += 1
        avg = (i + 1 + j + 1) / 2.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman(x, y):
    """Spearman ρ（平均秩 + Pearson）。n<3 或零方差返回 None。"""
    n = len(x)
    if n < 3 or len(y) != n:
        return None
    rx, ry = _rank(x), _rank(y)
    mx = sum(rx) / n
    my = sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    dx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    dy = math.sqrt(sum((b - my) ** 2 for b in ry))
    if dx < 1e-12 or dy < 1e-12:
        return None
    r = num / (dx * dy)
    return max(-1.0, min(1.0, r))


def fleiss_kappa(ratings):
    """Fleiss' κ（二分类，多评分者）。

    ratings: list[list[int]]，每个 item 一行，元素为 0/1；None 表示该评分者缺席。
    返回 dict(kappa, p_bar, p_e, n_items, n_raters)，样本不足返回 kappa=None。
    """
    rows = []
    for r in ratings:
        vals = [v for v in r if v is not None]
        if len(vals) >= 2:
            rows.append(vals)
    if len(rows) < 2:
        return dict(
            kappa=None,
            p_bar=None,
            p_e=None,
            n_items=len(rows),
            n_raters=0,
            note="insufficient_items",
        )
    # 统一评分者数：Fleiss 要求每 item 评分者数相同；取最小值并截断
    n = min(len(r) for r in rows)
    rows = [r[:n] for r in rows]
    N = len(rows)
    p_bar = 0.0
    for r in rows:
        c1 = sum(1 for v in r if v == 1)
        c0 = n - c1
        p_bar += (c1 * c1 + c0 * c0 - n) / float(n * (n - 1))
    p_bar /= N
    p1 = sum(sum(1 for v in r if v == 1) for r in rows) / float(N * n)
    p0 = 1.0 - p1
    p_e = p1 * p1 + p0 * p0
    if abs(1.0 - p_e) < 1e-12:
        return dict(
            kappa=None,
            p_bar=p_bar,
            p_e=p_e,
            n_items=N,
            n_raters=n,
            note="degenerate_p_e",
        )
    return dict(
        kappa=(p_bar - p_e) / (1.0 - p_e),
        p_bar=p_bar,
        p_e=p_e,
        n_items=N,
        n_raters=n,
        note="",
    )


def _group_by(measurements, keyfunc):
    d = {}
    for r in measurements:
        d.setdefault(keyfunc(r), []).append(r)
    return d


def pairwise_stats(measurements, groups=None, min_pairs=3):
    """每个 (endpoint, 源A, 源B) 的配对统计。

    只比较**同一分子同一端点**都给出域内数值的两源。输出一行一条：
    endpoint, source_a, source_b, same_group, n, spearman, mean_abs_diff,
    max_abs_diff, disagree_rate, sufficient
    """
    groups = groups or {}
    by_ep = _group_by(measurements, lambda r: r.get("endpoint", ""))
    out = []
    for ep, rows in sorted(by_ep.items()):
        by_cid = _group_by(rows, lambda r: r.get("compound_id", ""))
        # {cid: {source: (value, unit_kind)}}
        table = {}
        srcs = set()
        for cid, rs in by_cid.items():
            d = {}
            for r in rs:
                if r.get("domain_flag") not in IN_DOMAIN:
                    continue
                v = _f(r.get("value"))
                if v is None:
                    continue
                k = _unit_kind(r.get("unit"))
                if k == "other":
                    continue
                d[r.get("source", "")] = (v, k, r.get("unit"))
                srcs.add(r.get("source", ""))
            if d:
                table[cid] = d
        sl = sorted(srcs)
        for i in range(len(sl)):
            for j in range(i + 1, len(sl)):
                a, b = sl[i], sl[j]
                pairs, kinds = [], set()
                n_mismatch = 0
                n_converted = 0
                n_semantic = 0
                for cid, d in table.items():
                    if a in d and b in d:
                        va, ka, ua = d[a]
                        vb, kb, ub = d[b]
                        if ka != kb:
                            # R22：先尝试真实换算，不能换算才计数（并按原因分类）
                            va2, vb2, status, _note = U.try_pair(va, ua, vb, ub)
                            if status == "converted":
                                pairs.append((va2, vb2))
                                kinds.add("converted")
                                n_converted += 1
                                continue
                            if status == "semantic":
                                n_semantic += 1
                            n_mismatch += 1
                            continue
                        pairs.append((va, vb))
                        kinds.add(ka)
                n = len(pairs)
                if n == 0 and n_mismatch == 0:
                    continue
                if n == 0:
                    # 只有单位异构、没有可配对值：显式记录，避免"看起来没配对"
                    out.append(
                        dict(
                            endpoint=ep,
                            source_a=a,
                            source_b=b,
                            same_group=bool(
                                groups.get(a) and groups.get(a) == groups.get(b)
                            ),
                            group=(
                                (groups.get(a) or "")
                                if (groups.get(a) and groups.get(a) == groups.get(b))
                                else ""
                            ),
                            n=0,
                            n_unit_mismatch=n_mismatch,
                            spearman="",
                            mean_abs_diff="",
                            max_abs_diff="",
                            disagree_rate="",
                            sufficient="N",
                            sign_conflict="",
                            note="单位异构，无法配对（不得强行换算）",
                        )
                    )
                    continue
                xs = [p[0] for p in pairs]
                ys = [p[1] for p in pairs]
                diffs = [abs(x - y) for x, y in pairs]
                # 分歧阈值：概率 0.30（与 reliability.PROB_SPREAD_MAX 同口径）
                thr = 0.30
                disagree = sum(1 for d0 in diffs if d0 > thr) / float(n)
                rho = spearman(xs, ys) if n >= min_pairs else None
                sign_conflict = "Y" if (rho is not None and rho < -0.30) else "N"
                same = bool(groups.get(a) and groups.get(a) == groups.get(b))
                out.append(
                    dict(
                        endpoint=ep,
                        source_a=a,
                        source_b=b,
                        same_group=same,
                        group=(groups.get(a) or "") if same else "",
                        n=n,
                        n_unit_mismatch=n_mismatch,
                        spearman=("" if rho is None else round(rho, 4)),
                        mean_abs_diff=round(sum(diffs) / n, 4),
                        max_abs_diff=round(max(diffs), 4),
                        disagree_rate=round(disagree, 4),
                        sufficient=("Y" if n >= min_pairs else "N"),
                        sign_conflict=sign_conflict,
                        n_unit_converted=n_converted,
                        n_semantic_mismatch=n_semantic,
                        note=(
                            "单位可换算 %d 对（已换算后配对）；语义异构 %d 对跳过"
                            "（class vs probability，C78）；"
                            % (n_converted, n_semantic)
                            if n_mismatch
                            else ""
                        ),
                    )
                )
    return out


def group_summary(
    pair_rows, groups=None, rho_redundant=0.90, rho_partial=0.70, min_weight=0.50
):
    """按 independence_group 汇总组内冗余度并给出组权重。

    权重映射（**校准选择，必须在报告里同时给出 ρ 原值**）：
      max|ρ| <= 0.70           -> 1.00（视为独立）
      0.70 < max|ρ| < 0.90     -> 1.00 → 0.50 线性
      max|ρ| >= 0.90           -> 0.50（半票；"多平台≈多来源"的降权）
    无配对数据 -> 1.00 + evidence=no_pairwise_data（保守不降权，但显式标注）。
    """
    groups = groups or {}
    by_group = {}
    for p in pair_rows:
        if not p.get("same_group"):
            continue
        g = p.get("group") or ""
        if not g:
            continue
        by_group.setdefault(g, []).append(p)

    out = []
    for g, ps in sorted(by_group.items()):
        abs_rhos = [
            abs(float(p["spearman"])) for p in ps if p.get("spearman") not in ("", None)
        ]
        pos_rhos = [
            float(p["spearman"])
            for p in ps
            if p.get("spearman") not in ("", None) and float(p["spearman"]) > 0
        ]
        n_pairs = len(ps)
        n_ep = len({p["endpoint"] for p in ps})
        n_sign = sum(1 for p in ps if p.get("sign_conflict") == "Y")
        n_mis = sum(int(p.get("n_unit_mismatch") or 0) for p in ps)
        if not abs_rhos:
            weight, evidence = 1.0, "no_rho_data"
            max_abs = mean_abs = max_pos = None
        else:
            max_abs = max(abs_rhos)
            mean_abs = sum(abs_rhos) / len(abs_rhos)
            # 冗余只看**正相关**：负相关是方向/语义冲突，不应被当作"同组冗余"降权
            max_pos = max(pos_rhos) if pos_rhos else 0.0
            if max_pos >= rho_redundant:
                weight, evidence = min_weight, "redundant(max_pos_rho>=0.90)"
            elif max_pos > rho_partial:
                weight = 1.0 - (1.0 - min_weight) * (
                    (max_pos - rho_partial) / (rho_redundant - rho_partial)
                )
                evidence = "partially_redundant"
            else:
                weight, evidence = 1.0, "independent(max_pos_rho<=0.70)"
        if n_sign:
            evidence = "sign_conflict(%d); %s" % (n_sign, evidence)
        # R03–R06：把组内源数 k、有效票、权重区间、功效一起报出来（不再只给一个 group_weight）
        srcs = set()
        for p in ps:
            srcs.add(p.get("source_a"))
            srcs.add(p.get("source_b"))
        k = len([s for s in srcs if s])
        rho_ref = max_pos if max_pos is not None else 0.0
        ap = assess_pair(n_pairs, rho_ref, None, None, k=max(k, 2))
        out.append(
            dict(
                group=g,
                n_pairs=n_pairs,
                n_endpoints=n_ep,
                max_abs_rho=("" if max_abs is None else round(max_abs, 4)),
                mean_abs_rho=("" if mean_abs is None else round(mean_abs, 4)),
                max_pos_rho=("" if max_pos is None else round(max_pos, 4)),
                n_sign_conflicts=n_sign,
                n_unit_mismatch=n_mis,
                group_weight=round(weight, 4),
                evidence=evidence,
                # R06：功效不足时**不得**应用收缩权重（评审 R1-1），故另给"实际生效权重"
                group_weight_effective=(
                    1.0 if ap["status"] == "insufficient_power" else round(weight, 4)
                ),
                weight_gate=(
                    "blocked" if ap["status"] == "insufficient_power" else "applied"
                ),
                n_sources=k,
                n_eff=round(n_eff_equicorrelated(max(k, 2), rho_ref), 3),
                n_eff_ratio=round(weight, 4),
                independence_status=ap["status"],
                weight_ci95=ap["weight_ci95"],
                power_at_rho="%s"
                % ap.get("power_at_observed_rho", ap.get("power_at_rho_0.5")),
                min_detectable_rho=ap.get("min_detectable_rho"),
            )
        )
    return out


from adt import units as U  # R22：单位换算层


# ---- P1（评审 v4.0，C1/C10 致命修复）：n_eff 收缩 + ρ<0 冲突分流 ----
# 双通道（评审原话）：
#   通道一（截断）：n_eff(ρ) = 1 / (1 + max(ρ, 0))，且 **仅当 Fisher z 95%CI 下界 > 0** 时才收缩。
#   通道二（分流）：ρ 的 CI 下界 < 0（或点估计 < 0）→ 触发冲突分流 source_conflict，
#       默认 UNDETERMINED，归因第七类，建议第三源/实测仲裁；CI 含 0 → 按 ρ=0 计不收缩。
# 旧版（v3.6.2）缺少此处逻辑：group_summary 的 group_weight 仅做 0.5–1.0 的冗余降权，
# 未对 ρ<0 做任何处理，导致"负相关被当作低冗余"而放大等效票数（C1 的根因）。
def rho_contraction_weight(rho, ci_lo=None, ci_hi=None, k=2):
    """返回 (weight, status, note)。weight = n_eff/k。

    **R03 修正（评审 C3）**：旧版写死 ``n_eff = 1/(1+max(ρ,0))``，只对 k=2 成立，
    且完全丢弃组内源数 k（同一组 2 源与 8 源得到相同"有效票"）。现改为等相关标准形：

        n_eff = k / (1 + (k−1)·max(ρ,0))     ⇒  weight = 1 / (1 + (k−1)·max(ρ,0))

    当 k=2 时退化为 1/(1+ρ)，与历史结果**逐位一致**（向后兼容）。
    k=1 时 weight 恒为 1（单源无冗余）；k→∞ 且 ρ>0 时 weight→0（组内全冗余）。

    status ∈ {contracted, independent, source_conflict, inconclusive, insufficient_power}
    - rho < 0                                            -> source_conflict（不收缩，触发第七类归因）
    - ci_hi < 0（CI 整体为负）                            -> source_conflict
    - ci_lo <= 0 <= ci_hi（CI 含 0，方向不确定）          -> independent，weight=1.0（按 ρ=0 计，不收缩）
    - ci_lo > 0（方向确定为正）或 无 CI 且 rho>=0         -> contracted
    - k<1                                                -> inconclusive（非法组大小）
    """
    if rho is None:
        return 1.0, "inconclusive", "no_rho_data"
    if k is None or k < 1:
        return 1.0, "inconclusive", "k<1: 组大小非法"
    if rho < 0:
        return (
            1.0,
            "source_conflict",
            "rho<0: 方向/语义冲突，不收缩，触发 source_conflict",
        )
    if ci_lo is not None and ci_hi is not None:
        if ci_hi < 0:
            return 1.0, "source_conflict", "ci_entirely_negative: 视为方向冲突"
        if ci_lo <= 0 <= ci_hi:
            return 1.0, "independent", "ci_includes_0: 按 rho=0 计，不收缩"
        # 落入此处即 ci_lo > 0，方向确定为正
    r = max(float(rho), 0.0)
    w = 1.0 / (1.0 + (k - 1) * r)
    return round(w, 4), "contracted", "n_eff=k/(1+(k-1)max(rho,0)); k=%d" % k


def n_eff_equicorrelated(k, rho):
    """等相关系数下的有效样本量（标准形）：k / (1 + (k−1)ρ)。"""
    if k < 1:
        return 0.0
    r = max(float(rho), 0.0)
    return k / (1.0 + (k - 1) * r)


def n_eff_from_corr_matrix(R):
    """相关矩阵下"均值型"有效样本量：**n_eff = k² / (1ᵀR1)**。

    **重要技术说明（R03 的数学结论）**：评审 A3 建议的
    ``n_eff = (Σλ_i)²/Σλ_i²`` **与它自己给出的等相关标准形不自洽**——
    对等相关矩阵代入可得 ``k/(1+(k−1)ρ²)``，而标准形是 ``k/(1+(k−1)ρ)``，
    两者仅在 ρ∈{0,1} 重合。正确的矩阵推广来自"均值的方差"：
        Var(mean) = 1ᵀR1 / k²  ⇒  n_eff = 1/Var = k² / (1ᵀR1)
    等相关时代入 1ᵀR1 = k(1+(k−1)ρ)，即得 ``k/(1+(k−1)ρ)`` ✓ 完全一致。
    故本函数采用 1ᵀR1 形式；``n_eff_kish_eigen`` 另行保留，但**不得**用于计票权重
    （它度量的是"有效维度/多样性"，不是"均值的有效样本量"）。
    """
    import numpy as np

    R = np.asarray(R, dtype=float)
    if R.ndim != 2 or R.shape[0] != R.shape[1]:
        raise ValueError("R 必须是方阵")
    k = R.shape[0]
    tot = float(R.sum())
    if tot <= 0:
        return float(k)
    return float(k * k / tot)


def n_eff_kish_eigen(R):
    """(Σλ)²/Σλ² —— 有效维度（diversity），**不是**计票有效票数。"""
    import numpy as np

    R = np.asarray(R, dtype=float)
    lam = np.clip(np.linalg.eigvalsh(R), 1e-12, None)
    return float((lam.sum() ** 2) / (lam**2).sum())


def weight_ci(k, rho, ci_lo, ci_hi):
    """R04：把 ρ 的 95%CI 传播到权重，返回 (w_median, w_lo, w_hi)。

    权重对 ρ 单调递减，故区间端点可直接映射（免重抽样）：
    w_hi 用 ci_lo 算，w_lo 用 ci_hi 算。ρ 为负时按 0 截断。
    """

    def _w(r):
        return 1.0 / (1.0 + (k - 1) * max(float(r), 0.0))

    if ci_lo is None or ci_hi is None:
        w = _w(rho)
        return round(w, 4), round(w, 4), round(w, 4)
    return (round(_w(rho), 4), round(_w(ci_hi), 4), round(_w(ci_lo), 4))


def rho_posterior_weights(
    k, rho, n_pairs, n_draws=4000, alpha=0.05, seed=0, prior_sd=0.5
):
    """R04/B1：由 Fisher z 近似 + 弱信息先验抽样 ρ，返回权重后验摘要。

    先验取 z ~ N(0, prior_sd)，似然 z ~ N(z_hat, 1/(n−3))。n≤3 时退化为先验。
    """
    import numpy as np

    rng = np.random.default_rng(seed)
    r = min(max(float(rho), -0.9999), 0.9999)
    z_hat = 0.5 * np.log((1 + r) / (1 - r))
    if n_pairs is None or n_pairs <= 3:
        z_post = rng.normal(0.0, prior_sd, n_draws)
    else:
        se = 1.0 / np.sqrt(n_pairs - 3.0)
        prec = 1.0 / se**2 + 1.0 / prior_sd**2
        mu = (z_hat / se**2) / prec
        sd = np.sqrt(1.0 / prec)
        z_post = rng.normal(mu, sd, n_draws)
    rho_post = np.tanh(z_post)
    w = 1.0 / (1.0 + (k - 1) * np.clip(rho_post, 0, None))
    lo, hi = np.percentile(w, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return {
        "k": k,
        "rho_point": round(r, 4),
        "n_pairs": n_pairs,
        "w_median": round(float(np.median(w)), 4),
        "w_ci95": [round(float(lo), 4), round(float(hi), 4)],
        "p_weight_below_half": round(float((w < 0.5).mean()), 3),
        "p_contracted": round(float((rho_post > 0).mean()), 3),
        "note": "Fisher z + N(0,%.1f) 先验；n≤3 时退化为先验" % prior_sd,
    }


def correlation_power(n, rho, alpha=0.05):
    """R05：Fisher z 双侧检验的功效。"""
    import numpy as np

    try:
        from scipy.stats import norm
    except Exception:  # 退化为正态近似

        class norm(object):
            @staticmethod
            def cdf(x):
                return 0.5 * (1.0 + np.math.erf(x / np.sqrt(2.0)))

    if n is None or n <= 3:
        return 0.0
    r = min(max(abs(float(rho)), 1e-9), 0.9999)
    z = 0.5 * np.log((1 + r) / (1 - r))
    lam = z * np.sqrt(n - 3.0)
    zcrit = norm.ppf(1 - alpha / 2.0)
    return float(norm.cdf(lam - zcrit) + norm.cdf(-lam - zcrit))


def min_detectable_rho(n, alpha=0.05, power=0.8):
    """R05：给定 n 与目标功效，可检出的最小 |ρ|（Fisher z）。"""
    import numpy as np

    try:
        from scipy.stats import norm
    except Exception:
        raise RuntimeError("需要 scipy.stats.norm")
    if n is None or n <= 3:
        return None
    z = (norm.ppf(1 - alpha / 2.0) + norm.ppf(power)) / np.sqrt(n - 3.0)
    return float(np.tanh(z))


MIN_PAIRS_FOR_INDEPENDENCE = 20


def assess_pair(
    n_pairs, rho, ci_lo=None, ci_hi=None, k=2, alpha=0.05, power_target=0.8
):
    """R03+R04+R05+R06 的统一入口：一次给出权重、权重 CI、功效、是否允许判定。

    规则（评审 R1-1 原话："n<20 时直接禁用独立性判定并返回'结构性原因：样本量'"）：
      - n_pairs < MIN_PAIRS_FOR_INDEPENDENCE → status=insufficient_power，weight=1.0，
        **禁止静默输出收缩权重**，归因写 `structural: sample_size`。
      - 否则按 rho_contraction_weight + weight_ci + 功效报告。
    """
    out = {"k": k, "n_pairs": n_pairs, "rho": rho, "alpha": alpha}
    if n_pairs is None or n_pairs < MIN_PAIRS_FOR_INDEPENDENCE:
        pw = correlation_power(n_pairs, 0.5, alpha) if n_pairs else 0.0
        out.update(
            {
                "status": "insufficient_power",
                "weight": 1.0,
                "weight_ci95": [1.0, 1.0],
                "power_at_rho_0.5": round(pw, 3),
                "reason": "structural: sample_size（n=%s < %d）"
                % (n_pairs, MIN_PAIRS_FOR_INDEPENDENCE),
                "min_detectable_rho": (
                    None
                    if not n_pairs
                    else round(min_detectable_rho(n_pairs, alpha, power_target) or 0, 3)
                ),
            }
        )
        return out
    w, status, note = rho_contraction_weight(rho, ci_lo, ci_hi, k=k)
    lo, hi = weight_ci(k, rho, ci_lo, ci_hi)[1:]
    pw = correlation_power(n_pairs, rho if rho else 0.5, alpha)
    out.update(
        {
            "status": status,
            "weight": w,
            "weight_ci95": [lo, hi],
            "power_at_observed_rho": round(pw, 3),
            "min_detectable_rho": round(
                min_detectable_rho(n_pairs, alpha, power_target) or 0, 3
            ),
            "note": note,
            "robustness": (
                "robust"
                if (hi - lo) <= 0.15
                else "marginal" if (hi - lo) <= 0.35 else "unstable"
            ),
        }
    )
    return out


def bayes_contraction(
    corr_matrix, n_obs, votes=None, n_draws=2000, seed=0, shrink="lw"
):
    """R07/B1：相关性矩阵贝叶斯收缩 → n_eff 后验 → 裁决稳健概率。

    参数
      corr_matrix : k×k 相关矩阵（组内源两两相关）
      n_obs       : 计算该矩阵所用的配对数（决定 Fisher z 的抽样误差）
      votes       : 长度 k 的投票向量（+1 阳 / −1 阴 / 0 弃权）；None 则只报 n_eff
      shrink      : "lw"=向单位阵收缩 δ=min(1,k/n)（文档化的保守启发式），
                    None/0=不收缩

    返回：n_eff 后验摘要 + （若给 votes）三态裁决的蒙特卡洛稳健概率。
    """
    import numpy as np

    R = np.asarray(corr_matrix, dtype=float)
    k = R.shape[0]
    if k < 1:
        raise ValueError("k>=1")
    n = max(int(n_obs or 0), 4)
    delta = 0.0
    if shrink == "lw":
        delta = float(min(1.0, k / float(n)))
    R_s = (1 - delta) * R + delta * np.eye(k)

    # 逐对 Fisher z 抽样（保守：仅用下三角 k(k-1)/2 对，对角线保持 1）
    rng = np.random.default_rng(seed)
    se = 1.0 / np.sqrt(max(n - 3, 1))
    draws = np.empty((n_draws, k), dtype=float)
    neff = np.empty(n_draws, dtype=float)
    for d in range(n_draws):
        Rd = np.eye(k)
        for i in range(k):
            for j in range(i + 1, k):
                r = float(np.clip(R_s[i, j], -0.999, 0.999))
                z = 0.5 * np.log((1 + r) / (1 - r)) + rng.normal(0, se)
                val = float(np.tanh(z))
                Rd[i, j] = Rd[j, i] = val
        # 最近 PSD 投影（特征值截断）
        w, V = np.linalg.eigh(Rd)
        w = np.clip(w, 1e-8, None)
        Rd = V @ np.diag(w) @ V.T
        draws[d] = w
        neff[d] = k * k / max(float(Rd.sum()), 1e-9)

    out = {
        "k": k,
        "n_obs": n,
        "shrink_delta": round(delta, 3),
        "n_eff_median": round(float(np.median(neff)), 3),
        "n_eff_ci95": [
            round(float(np.percentile(neff, 2.5)), 3),
            round(float(np.percentile(neff, 97.5)), 3),
        ],
        "note": "Fisher z 抽样 + 特征值 PSD 投影；δ 为向单位阵收缩量",
    }
    if votes is None:
        return out
    v = np.asarray(votes, dtype=float)
    if len(v) != k:
        raise ValueError("votes 长度须为 k")
    # 每个 draw：按"局部等相关"给源权重 w_i = 1/(1+(k−1)·r̄_i)，r̄_i 为该源与其余源的平均相关
    verdicts = []
    R_base = np.asarray(corr_matrix, dtype=float)
    _w, V = np.linalg.eigh((1 - delta) * R_base + delta * np.eye(k))
    for d in range(n_draws):
        # 用抽样特征值重建自洽相关矩阵（对角置 1）
        recon = V @ np.diag(draws[d]) @ V.T
        np.fill_diagonal(recon, 1.0)
        local = np.clip((recon.sum(axis=1) - 1.0) / max(k - 1, 1), 0, None)
        wts = 1.0 / (1.0 + (k - 1) * local)
        wts = wts / wts.sum()
        s = float((wts * v).sum())
        verdicts.append(1 if s > 0.05 else (-1 if s < -0.05 else 0))
    verdicts = np.array(verdicts)
    out["verdict_prob"] = {
        "FAIL": round(float((verdicts == 1).mean()), 3),
        "PASS": round(float((verdicts == -1).mean()), 3),
        "UNDETERMINED": round(float((verdicts == 0).mean()), 3),
    }
    top = max(out["verdict_prob"], key=out["verdict_prob"].get)
    out["verdict_point"] = top
    out["verdict_stability"] = (
        "stable"
        if out["verdict_prob"][top] >= 0.8
        else "marginal" if out["verdict_prob"][top] >= 0.6 else "unstable"
    )
    return out


# 第七类归因（P1 分流通道）：与 reliability.py 的 reason 字段对齐
SOURCE_CONFLICT_REASON = "source_conflict"


def effective_votes(measurements, groups=None, group_weights=None):
    """每个 (compound_id, endpoint) 的"整数票" vs "加权有效票"。

    pseudo_consensus=True 表示：整数独立组 >=2，但加权有效票 <1.5——
    即"看起来两票，实际不足一票半"。这是评审意见要求暴露的假确定性风险。
    """
    groups = groups or {}
    # R06：优先使用"生效权重"（功效不足时 group_weight_effective=1.0，不做收缩）
    gw = {
        r["group"]: float(r.get("group_weight_effective", r["group_weight"]))
        for r in (group_weights or [])
    }
    by_key = _group_by(
        measurements, lambda r: (r.get("compound_id", ""), r.get("endpoint", ""))
    )
    out = []
    for (cid, ep), rows in sorted(by_key.items()):
        present = set()
        for r in rows:
            if r.get("domain_flag") not in IN_DOMAIN:
                continue
            if _f(r.get("value")) is None:
                continue
            present.add(groups.get(r.get("source", ""), r.get("source", "")) or "")
        n_indep = len(present)
        eff = sum(gw.get(g, 1.0) for g in present)
        out.append(
            dict(
                compound_id=cid,
                endpoint=ep,
                n_indep_groups=n_indep,
                effective_votes=round(eff, 4),
                pseudo_consensus=("Y" if (n_indep >= 2 and eff < 1.5) else "N"),
                groups=";".join(sorted(present)),
            )
        )
    return out


# ---- 校准计票（Jeffreys/Laplace 伪计数；Clark 2014 协议 step 7 含同式 +0.5/+1 连续性修正，合法次级引用） ----


def _truth_binary(row, rules):
    """把 truth 行转成 0(阴性) / 1(阳性) / None。

    优先 truth_class；否则用 rules 阈值判 truth_value。
    """
    tc = (row.get("truth_class") or "").strip().upper()
    if tc in ("PASS", "0", "NEG", "NEGATIVE", "FALSE"):
        return 0
    if tc in ("FAIL", "1", "POS", "POSITIVE", "TRUE"):
        return 1
    v = _f(row.get("truth_value"))
    if v is None:
        return None
    ep = row.get("endpoint", "")
    try:
        from .reliability import _match_rule

        rule = _match_rule(ep, rules or {}) or {}
    except Exception:  # pragma: no cover
        rule = (rules or {}).get(ep) or {}
    shape = rule.get("shape", "down")
    p, f = rule.get("pass"), rule.get("fail")
    if shape == "down":
        if p is not None and v <= p:
            return 0
        if f is not None and v > f:
            return 1
    elif shape == "up":
        if p is not None and v >= p:
            return 0
        if f is not None and v < f:
            return 1
    elif shape == "step":
        if f is not None:
            return 1 if v > f else 0
    return None


def summarize_vote(k, n):
    """多数票：1 阳性 / 0 阴性 / None 平局。"""
    if n <= 0:
        return None
    if 2 * k > n:
        return 1
    if 2 * k < n:
        return 0
    return None


def vote_calibration(measurements, truth_rows, rules=None, min_per_k=5):
    """经验校准：给定"k 票阳性 / n 源"，估计裁决错误率 u(k)。

    做法（Jeffreys/Laplace 伪计数平滑；Clark 2014 协议 step 7 含同式 +0.5/+1 连续性修正，合法次级引用）：
      - 只在同一端点内配对（truth 与预测同 cid+ep）
      - 阳性定义：概率端点 p>=0.5；类别端点 v>=0.5；真值按 truth_class/阈值
      - 对每个 k：n_k = 样本数，err_k = 多数票与真值不符数（平局不计）
      - u(k) = (err_k + 0.5) / (n_k + 1.0)   （Jeffreys 平滑）
      - vote_confidence = 1 - u(k)
    返回 per-k 表；n_k < min_per_k 标 insufficient（不用于门控）。
    """
    rules = rules or {}
    truth = {}
    for t in truth_rows:
        y = _truth_binary(t, rules)
        if y is None:
            continue
        truth[(t.get("compound_id", ""), t.get("endpoint", ""))] = (y, t)
    by_key = _group_by(
        measurements, lambda r: (r.get("compound_id", ""), r.get("endpoint", ""))
    )
    buckets = {}
    for key, y, tr in [(k, v[0], v[1]) for k, v in truth.items()]:
        rows = by_key.get(key) or []
        votes = []
        for r in rows:
            if r.get("domain_flag") not in IN_DOMAIN:
                continue
            v = _f(r.get("value"))
            if v is None:
                continue
            kind = _unit_kind(r.get("unit"))
            if kind == "prob":
                votes.append(1 if v >= 0.5 else 0)
            elif kind == "class":
                votes.append(1 if v >= 0.5 else 0)
        n = len(votes)
        if n < 1:
            continue
        kpos = sum(votes)
        maj = summarize_vote(kpos, n)
        b = buckets.setdefault(
            (key[1], kpos, n),
            dict(endpoint=key[1], k=kpos, n_raters=n, n=0, n_err=0, n_tie=0),
        )
        b["n"] += 1
        if maj is None:
            b["n_tie"] += 1
        elif maj != y:
            b["n_err"] += 1
    out = []
    for (ep, kpos, n), b in sorted(buckets.items()):
        n_eff = b["n"] - b["n_tie"]
        u = (b["n_err"] + 0.5) / (n_eff + 1.0) if n_eff > 0 else None
        out.append(
            dict(
                endpoint=ep,
                k=kpos,
                n_raters=n,
                n=b["n"],
                n_scored=n_eff,
                n_errors=b["n_err"],
                n_ties=b["n_tie"],
                error_rate_raw=("" if n_eff == 0 else round(b["n_err"] / n_eff, 4)),
                u_smoothed=("" if u is None else round(u, 4)),
                vote_confidence=("" if u is None else round(1.0 - u, 4)),
                status=("ok" if n_eff >= min_per_k else "insufficient"),
            )
        )
    # 单调性检查：u(k) 应随 k 增加而下降（k 是阳性票数，远离 0/n 两端都应更确定）
    return out


def monotonicity_flag(cal_rows):
    """检查 u(k) 是否随"多数票优势"单调下降；不单调 = 校准失败信号。"""
    by_ep = {}
    for r in cal_rows:
        if r.get("u_smoothed") in ("", None):
            continue
        by_ep.setdefault(r["endpoint"], []).append(r)
    flags = []
    for ep, rs in by_ep.items():
        # 用 |2k-n| 作为"确定性"排序
        rs = sorted(rs, key=lambda x: abs(2 * x["k"] - x["n_raters"]))
        us = [float(x["u_smoothed"]) for x in rs]
        viol = sum(1 for a, b in zip(us, us[1:]) if b > a + 1e-9)
        flags.append(
            dict(
                endpoint=ep,
                n_bins=len(us),
                n_violations=viol,
                monotone=("Y" if viol == 0 else "N"),
            )
        )
    return flags


def posterior_error(k, n, cal_rows, endpoint=""):
    """从校准表取 u(k)（同端点优先，跨端点兜底只在 k/n 相同尺度时）。"""
    cand = [
        r
        for r in cal_rows
        if r.get("k") == k
        and r.get("n_raters") == n
        and r.get("u_smoothed") not in ("", None)
    ]
    if endpoint:
        same = [r for r in cand if r.get("endpoint") == endpoint]
        if same:
            cand = same
    if not cand:
        return None
    return sum(float(r["u_smoothed"]) for r in cand) / len(cand)


# ---------------------------------------------------------------------------
# R-C6：源间相关的成因拆解（评审 C6 的可执行部分）
# ---------------------------------------------------------------------------
# 评审 C6：ρ 高时无法区分「共享训练数据」与「方法同源」，因此把 ρ 解读为
# 「方法学不独立」是越界的。真正的拆解需要各源训练集的分子重叠度（L3-3 TDATA），
# 当前仍是 pending。但**行为层**可以先做一件事：把源间相关精确地分成两部分。
#
# 设 p_i = y + e_i（预测 = 真值 + 误差）。注意**不能**直接对协方差做分解：
#   cov(p_i,p_j) = var_y + cov(e_i,y) + cov(y,e_j) + cov(e_i,e_j)
# 后三项不为 0（残差与真值相关），强行写成「信号项 + 误差项」就不恒等了
# （实测：random 数据下两项之和 1.71 vs 真值 0.95，差得离谱）。
#
# 正确做法是**对方差分解**：
#   平均预测的误差 e_m = (e_i + e_j)/2，其方差
#   Var(e_m) = (Var e_i + Var e_j)/4  +  Cov(e_i,e_j)/2
#            = indep_term             +  shared_term
# 这是恒等式（不含 y 的交叉项）。shared_term 即「多源平均也无法消除」的那部分
# 误差方差，正是 n_eff 想度量的对象。
#
# 判定用误差相关 r_e = corr(e_i, e_j)，而不是占比（占比在 var 很小时数值不稳）：
#   r_e ≤ 0.2 → 误差近似独立：平均确实降噪，收缩只会白白丢信息
#   r_e ≥ 0.5 → 误差显著共享：平均无法降噪，收缩有依据
# 这与 total_corr 高低**无关**——高相关可能只来自共同真值（见 signal_dominated）。
#
# 边界（必须随结果一起写）：这是**行为层代理**，能排除「纯信号导致的高相关」，
# 但无法进一步区分「共享数据」与「方法同源」——那仍需要 TDATA。


def _pearson(a, b):
    import numpy as _np

    a = _np.asarray(a, dtype=float)
    b = _np.asarray(b, dtype=float)
    if a.size < 3:
        return None
    sa, sb = a.std(ddof=1), b.std(ddof=1)
    if not (sa > 0 and sb > 0):
        return None
    return float(_np.corrcoef(a, b)[0, 1])


def decompose_error_variance(p_i, p_j, y):
    """恒等地把「平均预测的误差方差」拆成 indep_term + shared_term。

    返回 dict：
      total_corr      corr(p_i,p_j)（高不高都不能单独作为独立性证据）
      r_error         corr(e_i,e_j)，判定依据
      var_err_mean    Var((e_i+e_j)/2)
      indep_term      (Var e_i + Var e_j)/4
      shared_term     Cov(e_i,e_j)/2 = var_err_mean − indep_term
      shared_share    shared_term / var_err_mean（平均误差方差中不可消除的比例）
      verdict         independent_errors / shared_errors / mixed / undetermined
    """
    import numpy as _np

    p_i = _np.asarray(p_i, dtype=float)
    p_j = _np.asarray(p_j, dtype=float)
    y = _np.asarray(y, dtype=float)
    total = _pearson(p_i, p_j)
    if p_i.size < 3:
        return dict(
            total_corr=None,
            r_error=None,
            var_err_mean=None,
            indep_term=None,
            shared_term=None,
            shared_share=None,
            verdict="undetermined",
            note="样本不足",
        )
    e_i, e_j = p_i - y, p_j - y
    if e_i.std(ddof=1) <= 0 or e_j.std(ddof=1) <= 0:
        return dict(
            total_corr=total,
            r_error=None,
            var_err_mean=None,
            indep_term=None,
            shared_term=None,
            shared_share=None,
            verdict="undetermined",
            note="某一源误差方差为 0（恒定预测）",
        )
    var_i = float(e_i.var(ddof=1))
    var_j = float(e_j.var(ddof=1))
    cov = float(_np.cov(e_i, e_j, ddof=1)[0, 1])
    var_mean = float(((e_i + e_j) / 2.0).var(ddof=1))
    indep_term = (var_i + var_j) / 4.0
    shared_term = var_mean - indep_term
    r_e = _pearson(e_i, e_j)
    share = (shared_term / var_mean) if var_mean > 1e-12 else None
    if r_e is None:
        verdict = "undetermined"
    elif r_e <= 0.2:
        verdict = "independent_errors"
    elif r_e >= 0.5:
        verdict = "shared_errors"
    else:
        verdict = "mixed"
    return dict(
        total_corr=(round(total, 4) if total is not None else None),
        r_error=round(r_e, 4),
        var_err_mean=round(var_mean, 5),
        indep_term=round(indep_term, 5),
        shared_term=round(shared_term, 5),
        shared_share=(round(share, 4) if share is not None else None),
        cov_error=round(cov, 5),
        verdict=verdict,
        note=(
            "indep_term+shared_term=var_err_mean 为恒等分解；"
            "判定只用 r_error，不得用 total_corr 单独断言独立性"
        ),
    )


def decompose_correlation(p_i, p_j, y):
    """兼容旧名（早期版本用协方差分解，不恒等，已废弃）；转发到方差分解。"""
    d = decompose_error_variance(p_i, p_j, y)
    d["deprecated_alias"] = "decompose_correlation -> decompose_error_variance"
    return d


def pairwise_decomposition(P, y, names=None):
    """对一组源做两两误差方差分解，返回列表（供报告直接排版）。"""
    import numpy as _np

    P = _np.asarray(P, dtype=float)
    k = P.shape[1]
    names = names or ["s%d" % i for i in range(k)]
    out = []
    for i in range(k):
        for j in range(i + 1, k):
            d = decompose_error_variance(P[:, i], P[:, j], y)
            d.update(a=names[i], b=names[j])
            out.append(d)
    return out


def attribution_summary(decomp):
    """把两两分解汇总成一句可写进报告的话（不做超出证据的推断）。"""
    if not decomp:
        return dict(verdict="undetermined", statement="无可用源对")
    rs = [d["r_error"] for d in decomp if d.get("r_error") is not None]
    if not rs:
        return dict(verdict="undetermined", statement="无可用源对")
    mean_r = sum(rs) / len(rs)
    verds = [d["verdict"] for d in decomp]
    if verds.count("shared_errors") >= max(1, (len(verds) + 1) // 2):
        v = "shared_errors"
    elif verds.count("independent_errors") >= max(1, (len(verds) + 1) // 2):
        v = "independent_errors"
    else:
        v = "mixed"
    msg = {
        "shared_errors": "误差显著共享：多源平均无法降噪，收缩权重的方向正确；"
        "但成因（共享数据 vs 同源方法）仍未拆解",
        "independent_errors": "误差近似独立：高相关主要来自共同真值，"
        "此时收缩会丢掉真实信息，ρ 不得读作「方法不独立」",
        "mixed": "误差部分共享：可报「输出相关 + 共享误差占比」，" "不得做独立性归因",
    }[v]
    return dict(
        verdict=v,
        mean_r_error=round(mean_r, 4),
        mean_shared_share=round(
            sum(d["shared_share"] for d in decomp if d.get("shared_share") is not None)
            / max(1, len(rs)),
            4,
        ),
        statement="平均误差相关 r_e=%.2f；%s" % (mean_r, msg),
    )
