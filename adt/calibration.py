# -*- coding: utf-8 -*-
"""概率型端点的校准评估（Van Calster 2019, BMC Med 17:230）。

为什么必须有这一层
------------------
`benchmark` 之前只报 AUROC/AUPRC。判别力（discrimination）与校准（calibration）
是两个正交概念：AUROC 高只说明"能排序"，**不说明"0.7 就是 70%"**。
把概率当阈值做决策（DILI 阳性/阴性、hERG 风险档）时，校准是必要条件——
Van Calster 等人把它称作预测分析的"阿喀琉斯之踵"。

本模块给出五件东西（均可手工复核）：
  Brier score / Brier skill score   概率预测的均方误差（相对基准流行率的改进）
  calibration slope & intercept     logistic 重校准 y ~ a + b·logit(p)
                                    b<1 过自信（预测过极端）、b>1 欠自信；a≠0 系统性偏移
  O:E ratio                         观测阳性数 / 期望阳性数（sum y / sum p）
  ECE                               分箱后的期望校准误差（加权 |mean_p − obs_rate|）
  calibration table                 逐箱 n / mean_p / obs_rate / Wilson 95% CI

**量纲门控（硬约束）**
只对"概率量纲"启用：unit ∈ {probability, prob, fraction, pct/100} 且值域 ⊂ [0,1]。
unit 缺失但值域全在 [0,1] 时启用并标 `range_implied`（提示单位未声明）。
其余量纲（log10 cm/s、µL/min/mg、%、percentile）**一律拒绝**并给出原因——
尤其 DrugBank percentile（ADMET-AI）**不是概率**，混进来会算出假校准。

文献：
  Van Calster B, McLernon DJ, van Smeden M, Wynants L, Steyerberg EW.
  Calibration: the Achilles heel of predictive analytics. BMC Med. 2019;17:230.
  DOI: 10.1186/s12916-019-1466-7
"""

PROB_UNITS = {"probability", "prob", "fraction", "fraction_1", "pct/100", "p"}
EPS = 1e-6


def _clip(p):
    return min(1.0 - EPS, max(EPS, p))


def _logit(p):
    p = _clip(p)
    import math

    return math.log(p / (1.0 - p))


def is_probability(unit, scores):
    """是否可按概率解读。返回 (ok, mode, reason)。"""
    if not scores:
        return False, "", "无样本"
    u = (unit or "").strip().lower()
    in_range = all(0.0 <= s <= 1.0 for s in scores)
    if u in PROB_UNITS:
        if not in_range:
            return False, "", "unit=%s 但存在越界值（>1 或 <0）" % unit
        return True, "declared", ""
    if u in ("", "none", "unitless"):
        if in_range:
            return True, "range_implied", "unit 未声明，按值域 ⊂ [0,1] 推断为概率"
        return False, "", "unit 未声明且值域不在 [0,1]"
    return False, "", "非概率量纲（unit=%s）：校准无定义" % unit


def brier(p, y):
    """Brier score（越小越好）。"""
    n = len(y)
    if n == 0:
        return None
    return sum((_clip(a) - b) ** 2 for a, b in zip(p, y)) / n


def brier_skill(p, y):
    """Brier skill score = 1 − BS/BS_ref（ref = 用流行率常数预测）。0=无改进，1=完美。"""
    bs = brier(p, y)
    if bs is None or not y:
        return None
    prev = sum(y) / float(len(y))
    ref = sum((prev - b) ** 2 for b in y) / float(len(y))
    if ref <= 1e-12:
        return None
    return 1.0 - bs / ref


def log_loss(p, y):
    import math

    n = len(y)
    if n == 0:
        return None
    s = 0.0
    for a, b in zip(p, y):
        q = _clip(a)
        s += -(b * math.log(q) + (1 - b) * math.log(1 - q))
    return s / n


def oe_ratio(p, y):
    """O:E = 观测阳性 / 期望阳性。>1 低估风险，<1 高估风险。"""
    exp = sum(_clip(a) for a in p)
    obs = sum(y)
    if exp <= 1e-12:
        return None
    return obs / exp


def calibration_slope_intercept(p, y, iters=60, tol=1e-9):
    """logistic 重校准：y ~ a + b·logit(p)。返回 (intercept a, slope b) 或 (None, None)。

    完美校准 = (0, 1)。b<1 → 预测过极端（过自信）；b>1 → 欠自信；a≠0 → 系统性偏移。
    用 IRLS/Newton 求解；分离（separation）或奇异时返回 None——**不硬凑数**。
    """
    import math

    if len(y) < 10 or len(set(y)) < 2:
        return None, None
    x = [_logit(v) for v in p]
    a, b = 0.0, 1.0
    for _ in range(iters):
        eta = [max(-30.0, min(30.0, a + b * xi)) for xi in x]
        mu = [1.0 / (1.0 + math.exp(-e)) for e in eta]
        w = [m * (1.0 - m) for m in mu]
        g0 = sum(yi - mi for yi, mi in zip(y, mu))
        g1 = sum((yi - mi) * xi for yi, mi, xi in zip(y, mu, x))
        h11 = -sum(w)
        h12 = -sum(wi * xi for wi, xi in zip(w, x))
        h22 = -sum(wi * xi * xi for wi, xi in zip(w, x))
        det = h11 * h22 - h12 * h12
        if abs(det) < 1e-12:
            return None, None
        da = -(h22 * g0 - h12 * g1) / det
        db = -(-h12 * g0 + h11 * g1) / det
        a += da
        b += db
        if max(abs(da), abs(db)) < tol:
            break
        if abs(b) > 1e6 or abs(a) > 1e6:
            return None, None
    return a, b


def _wilson(k, n, z=1.96):
    if n == 0:
        return (None, None)
    ph = k / float(n)
    den = 1.0 + z * z / n
    ctr = (ph + z * z / (2 * n)) / den
    half = z * ((ph * (1 - ph) / n + z * z / (4 * n * n)) ** 0.5) / den
    return (max(0.0, ctr - half), min(1.0, ctr + half))


def table(p, y, bins=10, strategy="width"):
    """校准表。默认**等宽分箱**（ECE 的标准定义）；strategy="quantile" 为等频。

    等宽分箱在预测值大量并列时不会人为拆散同一预测值（等频会），
    因此更适合"多数源给出同一概率"的 ADMET 场景。
    """
    pairs = sorted(zip(p, y), key=lambda t: t[0])
    n = len(pairs)
    if n == 0:
        return []
    rows = []
    for b in range(bins):
        if strategy == "quantile":
            idx = [int(i * bins / n) for i in range(n)]
            sub = [pairs[i] for i in range(n) if idx[i] == b]
        else:
            lo, hi = b / float(bins), (b + 1) / float(bins)
            sub = [
                (a, bb)
                for a, bb in pairs
                if (lo <= a < hi) or (b == bins - 1 and a >= lo)
            ]
        if not sub:
            continue
        mp = sum(a for a, _ in sub) / len(sub)
        k = sum(bb for _, bb in sub)
        lo_ci, hi_ci = _wilson(k, len(sub))
        rows.append(
            dict(
                bin=b + 1,
                n=len(sub),
                mean_pred=round(mp, 4),
                obs_rate=round(k / float(len(sub)), 4),
                ci_low=round(lo_ci, 4) if lo_ci is not None else "",
                ci_high=round(hi_ci, 4) if hi_ci is not None else "",
                gap=round(k / float(len(sub)) - mp, 4),
            )
        )
    return rows


def ece(p, y, bins=10, strategy="width"):
    """期望校准误差（按箱 n 加权）。"""
    rows = table(p, y, bins, strategy)
    n = sum(r["n"] for r in rows)
    if n == 0:
        return None
    return sum(r["n"] * abs(r["gap"]) for r in rows) / float(n)


def assess(p, y, unit="", min_n=30, min_pos=5, bins=10):
    """完整校准评估。返回 dict；不满足条件时明确写 flag，不返回可疑数字。"""
    ok, mode, reason = is_probability(unit, p)
    res = dict(
        applicable=ok,
        unit_mode=mode,
        unit_note=reason,
        n=len(p),
        n_pos=int(sum(y)) if y else 0,
        brier="",
        brier_skill="",
        log_loss="",
        oe="",
        cal_intercept="",
        cal_slope="",
        ece="",
        flag="",
        note="",
    )
    if not ok:
        res["flag"] = "not_applicable"
        res["note"] = reason
        return res
    if (
        res["n"] < min_n
        or res["n_pos"] < min_pos
        or (res["n"] - res["n_pos"]) < min_pos
    ):
        res["flag"] = "insufficient"
        res["note"] = (
            "n=%d、阳性=%d、阴性=%d：低于校准最低要求（n≥%d 且两类各≥%d），"
            "不报校准值（少样本斜率会被少数点主导）"
            % (res["n"], res["n_pos"], res["n"] - res["n_pos"], min_n, min_pos)
        )
        return res

    a, b = calibration_slope_intercept(p, y)
    res["brier"] = round(brier(p, y), 4)
    bs = brier_skill(p, y)
    res["brier_skill"] = round(bs, 4) if bs is not None else ""
    res["log_loss"] = round(log_loss(p, y), 4)
    oe = oe_ratio(p, y)
    res["oe"] = round(oe, 3) if oe is not None else ""
    res["cal_intercept"] = round(a, 3) if a is not None else ""
    res["cal_slope"] = round(b, 3) if b is not None else ""
    res["ece"] = round(ece(p, y, bins), 4)

    issues = []
    if b is not None:
        if b < 0.75:
            issues.append("过自信(slope=%.2f<0.75)" % b)
        elif b > 1.25:
            issues.append("欠自信(slope=%.2f>1.25)" % b)
    if a is not None and abs(a) > 0.3:
        issues.append("系统性偏移(intercept=%+.2f)" % a)
    if b is None:
        issues.append("slope 不可识别（预测值取值过少或完全分离）")
    if res["ece"] is not None and res["ece"] > 0.10:
        issues.append("ECE=%.3f>0.10" % res["ece"])
    if oe is not None and (oe < 0.8 or oe > 1.25):
        issues.append("O:E=%.2f 偏离 1" % oe)
    res["flag"] = "poor" if issues else "acceptable"
    res["note"] = (
        "；".join(issues)
        if issues
        else ("校准可接受（slope≈1、intercept≈0、ECE≤0.10）")
    )
    if mode == "range_implied":
        res["note"] += "｜单位未声明，按 [0,1] 推断"
    return res
