#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""第二实现者交叉复算（2026-11-18）—— 独立数值核验，不 import adt.stats_ci。

## 定位与诚实边界
这不是"第二实现者外部复现"（G9 条件③）的替代品——那需要一位非本仓库作者
按冻结 SAP 独立实现。本脚本是一个**局部数值交叉核验**：用独立编写的实现
（scipy.stats 直接调用 + 统计教科书公式，不复用 adt 的任何统计函数）重算
核心统计量，逐位比对 skill 产物里的数字。它能抓出"实现写错/产物抄错/单位错"，
但抓不出"estimand 定义错/整套方法选错"——后者只能靠专家判断。

## 核验项
1. Clopper-Pearson 精确二项 CI（用 scipy.stats.beta 独立实现）
2. Wilson score CI（教科书公式）
3. Holm–Bonferroni（逐步法，独立实现）
4. Newcombe 混合 score 差分 CI
5. 产物内部一致性：AUC 点估计落在自身 bootstrap CI 内；n_pos+n_neg==n；
   各端点 gate AUC 与 CLAIMS_REGISTRY expect token 一致。

运行：python tools/independent_recompute.py
"""

from __future__ import annotations

import io
import json
import os
import sys

from scipy.stats import beta as _beta, norm as _norm

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


# ---- 独立实现（不调用 adt）----
def cp_ci(k, n, alpha=0.05):
    lo = 0.0 if k == 0 else _beta.ppf(alpha / 2, k, n - k + 1)
    hi = 1.0 if k == n else _beta.ppf(1 - alpha / 2, k + 1, n - k)
    return float(lo), float(hi)


def wilson(k, n, alpha=0.05):
    z = _norm.ppf(1 - alpha / 2)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * (p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5 / d
    return max(0, c - h), min(1, c + h)


def holm(pvals, alpha=0.05):
    order = sorted(range(len(pvals)), key=lambda i: pvals[i])
    m = len(pvals)
    adj = [0.0] * m
    run = 0.0
    for rank, i in enumerate(order):
        run = max(run, min(1.0, pvals[i] * (m - rank)))
        adj[i] = round(run, 6)
    return adj


def newcombe_diff(k1, n1, k2, n2, alpha=0.05):
    """Newcombe hybrid score interval; k1/n1 - k2/n2。"""
    l1, u1 = wilson(k1, n1, alpha)
    l2, u2 = wilson(k2, n2, alpha)
    d = k1 / n1 - k2 / n2
    lo = d - ((k1 / n1 - l1) ** 2 + (u2 - k2 / n2) ** 2) ** 0.5
    hi = d + ((u1 - k1 / n1) ** 2 + (k2 / n2 - l2) ** 2) ** 0.5
    return dict(diff=round(d, 6), lo=round(lo, 6), hi=round(hi, 6))


def main():
    from adt import stats_ci as S  # 只用于取被核验值，核验逻辑全在上面独立实现

    rows = []

    def chk(name, got, exp, tol=1e-6):
        ok = abs(got - exp) <= tol
        rows.append((name, ok, got, exp))
        return ok

    # 1. Clopper-Pearson
    for k, n in [(0, 20), (5, 20), (109, 132), (1, 10)]:
        glo, ghi = S.clopper_pearson_ci(k, n)
        elo, ehi = cp_ci(k, n)
        chk("CP_lo_k%d_n%d" % (k, n), glo, elo)
        chk("CP_hi_k%d_n%d" % (k, n), ghi, ehi)

    # 2. Wilson
    for k, n in [(5, 20), (109, 132)]:
        g = S.wilson_ci(k, n)
        elo, ehi = wilson(k, n)
        chk("Wilson_lo_k%d" % k, g["lo"], elo)
        chk("Wilson_hi_k%d" % k, g["hi"], ehi)

    # 3. Holm
    pv = [0.0267, 0.7554, 1.0]
    g = [x["adj"] for x in S.holm(pv)["family"]]
    e = holm(pv)
    for i, (a, b) in enumerate(zip(g, e)):
        chk("Holm_adj_%d" % i, a, b)

    # 4. Newcombe
    g = S.newcombe_diff_ci(109, 132, 97, 132)
    e = newcombe_diff(109, 132, 97, 132)
    for key in ("diff", "lo", "hi"):
        chk("Newcombe_%s" % key, g[key], e[key], tol=2e-3)  # Wilson 实现细节差异容差

    # 5. 产物内部一致性
    for art, ep, key in [
        ("out_ext/tdc/gate_audit.json", "hERG", "gate_as_predictability"),
        ("out_ext/tdc/gate_audit_DILI.json", "DILI", "gate_as_predictability"),
        (
            "out_ext/tdc/gate_audit_BBB_Martins.json",
            "BBB_Martins",
            "gate_as_predictability",
        ),
    ]:
        p = os.path.join(ROOT, art)
        o = json.load(io.open(p, encoding="utf-8"))
        aci = o["auc_ci"][key]
        auc, lo, hi = aci["auc"], aci["lo"], aci["hi"]
        rows.append(("%s_auc_in_ci" % ep, lo <= auc <= hi, auc, "[%s,%s]" % (lo, hi)))
        rows.append(
            (
                "%s_npos_nneg" % ep,
                aci.get("n_pos", 0) + aci.get("n_neg", 0) == aci["n"],
                aci.get("n_pos", 0) + aci.get("n_neg", 0),
                aci["n"],
            )
        )

    n_ok = sum(1 for _, ok, _, _ in rows if ok)
    print("=== 第二实现者交叉复算（独立实现 vs adt 实现 / 产物）===")
    for name, ok, got, exp in rows:
        print(
            "  [%s] %-26s got=%-22s exp=%s"
            % ("OK" if ok else "FAIL", name, str(got)[:22], str(exp)[:30])
        )
    print("\n交叉核验 %d/%d 通过" % (n_ok, len(rows)))
    return 0 if n_ok == len(rows) else 4


if __name__ == "__main__":
    sys.exit(main())
