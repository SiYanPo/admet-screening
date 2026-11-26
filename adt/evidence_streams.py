# -*- coding: utf-8 -*-
"""证据流互补性审计（2026-11-19；100 篇精读移植 #1）。

## 文献依据（精读语料组 3，真实 PMID）
- PMID 42798706 / DOI 10.1007/s40203-026-00749-7：ML 预测与 docking score 的**实测近零相关**
  (r=0.090, p=0.37, n=100)，作者据此判定二者是 complementary evidence streams，
  并给出 ~14.6 倍富集。这是"多源证据准入先于组合"的直接实证判据。
- PMID 38380444 / DOI 10.1080/1062936X.2024.2314103：QSAR/docking/MD 三路"high agreement"
  作为确证；与本模块的"高相关=冗余、低相关=互补"形成两极判据。

## 为什么需要
本 skill 的 independence.py 用 ρ 做**可靠性降权**（同一信号别算两票），
但缺一个前置问题：**这两个证据流到底是不是在测同一件事？**
本模块把"互补 vs 冗余 vs 不可判定"变成可判定的数值门，输出可直接进 G10 字段级证据链。

## 诚实边界
* 相关为 0 **不等于**独立——只说明在这批样本上无线性/秩相关；非线性依赖可能存在。
* 高相关也可能是"都测对了"（确证）而非"同源重复"——须结合 `agreement` 与领域判断。
* 判定须人确认（与 SciForge 移植的 fragility 分类同一纪律），本模块只给候选裁决。
* 不做因果声称；不做"互补就一定该组合"的承诺——互补只解除重复计票的担忧。
"""

from __future__ import annotations

import math


def _pearson(x, y):
    n = len(x)
    if n < 2:
        return None
    mx, my = sum(x) / n, sum(y) / n
    dx = [v - mx for v in x]
    dy = [v - my for v in y]
    sxy = sum(a * b for a, b in zip(dx, dy))
    sxx = sum(a * a for a in dx)
    syy = sum(b * b for b in dy)
    if sxx <= 0 or syy <= 0:
        return None
    return sxy / math.sqrt(sxx * syy)


def _rank(vals):
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    r = [0.0] * len(vals)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            r[order[k]] = avg
        i = j + 1
    return r


def _spearman(x, y):
    return _pearson(_rank(x), _rank(y))


def _p_two_sided(r, n):
    """Pearson/Spearman r 的 t 近似双尾 p（无 scipy 时仍可用）。

    H0: rho=0 时 t = r*sqrt((n-2)/(1-r^2)) 服从 df=n-2 的 t 分布；
    双尾 p = I_{df/(df+t^2)}(df/2, 1/2)。自由度必须用 df=n-2（不得用 n），
    否则 p 系统性偏小、夸大显著性。n<3 或 |r|>=1 返回 None。
    """
    if r is None or n < 3 or abs(r) >= 1:
        return None
    try:
        df = n - 2
        t = abs(r) * math.sqrt(df / (1 - r * r))
        x = df / (df + t * t)
        return _betainc_reg(df / 2.0, 0.5, x)
    except (ValueError, ZeroDivisionError, OverflowError):
        return None


def _betainc_reg(a, b, x, itmax=200, eps=3e-14):
    """正则化不完全 beta I_x(a,b)（Lentz 连分数， Numerical Recipes 风格）。"""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    lbeta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    front = math.exp(lbeta + a * math.log(x) + b * math.log(1 - x))
    if x < (a + 1) / (a + b + 2):
        return front * _betacf(a, b, x, itmax, eps) / a
    return (
        1.0
        - math.exp(lbeta + b * math.log(1 - x) + a * math.log(x))
        * _betacf(b, a, 1 - x, itmax, eps)
        / b
    )


def _betacf(a, b, x, itmax, eps):
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    if abs(d) < 1e-30:
        d = 1e-30
    d = 1.0 / d
    h = d
    for m in range(1, itmax + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + aa / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + aa / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        de = d * c
        h *= de
        if abs(de - 1.0) < eps:
            break
    return h


def complementarity(
    stream_a,
    stream_b,
    method="spearman",
    min_n=10,
    r_complement=0.15,
    r_redundant=0.60,
    alpha=0.05,
    agreement=None,
    context="",
):
    """判定两条证据流是互补 / 冗余 / 不可判定。

    stream_a / stream_b：等长的数值向量（同一批分子上的两个源分数/预测）。
    agreement（可选）：两源判定一致的样本占比（0..1），用于区分
      "高相关=确证（都测对）" 与 "高相关=同源重复"。
    """
    n = min(len(stream_a), len(stream_b))
    if n < min_n:
        return dict(
            verdict="INDETERMINATE",
            reason="样本不足 n=%d < %d（ESCALATE，不得据此组合）" % (n, min_n),
            n=n,
            r=None,
            p=None,
            context=context,
            human_confirmation_required=True,
        )
    a, b = list(stream_a)[:n], list(stream_b)[:n]
    r = _spearman(a, b) if method == "spearman" else _pearson(a, b)
    if r is None:
        return dict(
            verdict="INDETERMINATE",
            reason="方差为 0，相关系数不可定义",
            n=n,
            r=None,
            p=None,
            context=context,
            human_confirmation_required=True,
        )
    p = _p_two_sided(r, n)
    if abs(r) <= r_complement and (p is None or p > alpha):
        v, why = "COMPLEMENTARY", (
            "近零相关 (|r|=%.3f, p=%s)：可双源准入、不重复计票；"
            "但不等于独立（非线性依赖可能存在）"
            % (abs(r), ("%.3g" % p) if p is not None else "n/a")
        )
    elif abs(r) >= r_redundant:
        v = (
            "CONFIRMATORY"
            if (agreement is not None and agreement >= 0.8)
            else "REDUNDANT"
        )
        why = "高相关 (|r|=%.3f)：%s" % (
            abs(r),
            (
                "两源高判定一致，可作为确证但仍不得双计独立票"
                if v == "CONFIRMATORY"
                else "疑似同源/重复测量，组合时须降权或择一"
            ),
        )
    else:
        v, why = "INDETERMINATE", (
            "相关处于灰区 (|r|=%.3f, r∈(%.2f,%.2f))，"
            "须领域判断，不自动组合" % (abs(r), r_complement, r_redundant)
        )
    return dict(
        verdict=v,
        reason=why,
        n=n,
        r=round(r, 4),
        p=(round(p, 6) if p is not None else None),
        method=method,
        agreement=agreement,
        context=context,
        evidence="PMID 42798706 (r=0.090,p=0.37,n=100 → complementary)",
        human_confirmation_required=True,
        not_a_claim_of="统计独立 / 因果无关 / 互补即应组合",
    )


def admission_report(streams, names=None, **kw):
    """多流两两审计，输出可进 G10 的准入清单与双计惩罚建议。"""
    names = list(names) if names else []
    names += [
        "S%d" % i for i in range(len(names), len(streams))
    ]  # 名称不足时补齐，避免 IndexError
    pairs = []
    for i in range(len(streams)):
        for j in range(i + 1, len(streams)):
            r = complementarity(
                streams[i], streams[j], context="%s vs %s" % (names[i], names[j]), **kw
            )
            pairs.append(dict(a=names[i], b=names[j], **r))
    ok = [p for p in pairs if p["verdict"] == "COMPLEMENTARY"]
    redundant = [p for p in pairs if p["verdict"] in ("REDUNDANT", "CONFIRMATORY")]
    return dict(
        pairs=pairs,
        admissible=[p for p in ok],
        discount_required=[
            {"a": p["a"], "b": p["b"], "verdict": p["verdict"]} for p in redundant
        ],
        n_complementary=len(ok),
        n_discount=len(redundant),
        discipline="互补仅解除重复计票担忧；不构成'应当组合'的证明",
        human_confirmation_required=True,
    )


def selftest():
    rows = []

    def chk(name, cond, detail=""):
        rows.append(dict(name=name, ok=bool(cond), detail=detail))

    # 近零相关 → complementary（确定性构造：a 单调，b 高频交替打乱秩）
    a = [0.05 * i for i in range(12)]
    b = [0.5 if i % 2 == 0 else 0.1 + 0.02 * i for i in range(12)]
    r = complementarity(a, b)
    chk(
        "near_zero_complementary",
        r["verdict"] == "COMPLEMENTARY",
        "r=%s verdict=%s" % (r["r"], r["verdict"]),
    )
    # 完全同向 → redundant
    r2 = complementarity(a, a)
    chk(
        "identical_redundant",
        r2["verdict"] in ("REDUNDANT", "CONFIRMATORY"),
        str(r2["verdict"]),
    )
    # 完全反向 → redundant（|r| 高）
    r3 = complementarity(a, [1 - x for x in a])
    chk(
        "inverse_redundant",
        r3["verdict"] in ("REDUNDANT", "CONFIRMATORY"),
        str(r3["r"]),
    )
    # 样本不足 → INDETERMINATE（ESCALATE）
    r4 = complementarity([0.1, 0.2], [0.3, 0.4])
    chk("small_n_indeterminate", r4["verdict"] == "INDETERMINATE", r4["reason"][:40])
    # beta/p 数值 sanity：p 应在 [0,1]
    chk("p_in_range", r["p"] is None or 0 <= r["p"] <= 1, str(r["p"]))
    # 多流报告
    rep = admission_report([a, b, a], names=["ML", "docking", "ML2"])
    chk(
        "admission_report_wiring",
        rep["n_discount"] >= 1 and len(rep["pairs"]) == 3,
        "discount=%d" % rep["n_discount"],
    )
    return all(x["ok"] for x in rows), rows


if __name__ == "__main__":
    import argparse, json

    ap = argparse.ArgumentParser(prog="evidence-streams")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        ok, rows = selftest()
        for r in rows:
            print(
                "[%s] %s %s"
                % ("OK" if r["ok"] else "FAIL", r["name"], r["detail"][:60])
            )
        print("[evidence-streams] %s" % ("PASS" if ok else "FAIL"))
        raise SystemExit(0 if ok else 4)
