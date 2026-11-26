# -*- coding: utf-8 -*-
"""组件贡献置换检验（2026-11-19；100 篇精读移植 #3）。

## 文献依据（真实 PMID，精读语料组1[22]）
- PMID 40899589 / DOI 10.1021/acs.jcim.5c00395 "All That Glitters Is Not Gold:
  Importance of Rigorous Evaluation of Proteochemometric Models"：
  用 **permutation testing** 发现 "protein embeddings contributed minimally to
  PCM efficacy"——即组件的复杂度没有带来真实贡献。

## 与已有 randomization_null_control 的区别（避免重复）
`adt/pred_displacement.randomization_null_control` 检验"结构扰动位移是否超过随机基线"
（Gate 0 必要性）。本模块检验的是"**某个组件/特征块/证据源对性能的贡献是否为零**"，
用于负结果闭环：贡献不显著 → 默认不采纳该组件，并回填 NEGATIVE_RESULT_DEFAULTS。

## 诚实边界
* 置换检验只测"该组件与标签的关联是否超过随机"，不证明因果。
* 须用与真实评估相同的切分/seed；否则置换分布不可比。
* 多次检验须 Holm 校正（复用 stats_ci.holm）。
"""

from __future__ import annotations

import random


def permutation_contribution(
    metric_fn,
    features,
    labels,
    component_idx,
    n_perm=200,
    seed=20261119,
    higher_is_better=True,
):
    """把 component_idx 指定的列置换 n_perm 次，比较真实指标与置换分布。

    metric_fn(features, labels) -> float；features 为 list of rows（等长）。
    返回 effect（真实 - 置换均值）、p（单尾经验 p）、verdict。
    """
    n = len(features)
    if n < 10 or not features:
        return dict(
            verdict="INDETERMINATE",
            reason="样本不足 n=%d" % n,
            human_confirmation_required=True,
        )
    if n_perm <= 0:
        return dict(
            verdict="ERROR",
            reason="n_perm 必须 >0，实际 %d" % n_perm,
            human_confirmation_required=True,
        )
    k = len(features[0])
    idx = [component_idx] if isinstance(component_idx, int) else list(component_idx)
    if any(i >= k or i < 0 for i in idx):
        return dict(verdict="ERROR", reason="component_idx 越界：%s" % idx)

    def score(fn):
        return float(metric_fn(fn, labels))

    real = score(features)
    rng = random.Random(seed)
    null = []
    for _ in range(n_perm):
        perm = [list(r) for r in features]
        for comp_i in idx:
            # 每列独立 Fisher-Yates 置换（保持边际分布，充分破坏与标签的对应）。
            # 不能用固定 n//2 次随机对换：实测 n=60/30 次对换后置换列与原列
            # 仍显著相关(≈0.36)，置换分布偏离零假设 → p 值失真。
            col = [r[comp_i] for r in perm]
            rng.shuffle(col)
            for r, v in zip(perm, col):
                r[comp_i] = v
        null.append(score(perm))

    mean_null = sum(null) / float(len(null))
    ge = (
        sum(1 for v in null if v >= real)
        if higher_is_better
        else sum(1 for v in null if v <= real)
    )
    p = (ge + 1) / float(len(null) + 1)  # +1 校正，避免 p=0
    effect = real - mean_null if higher_is_better else mean_null - real
    # 置换分布标准差 → 标准化效应（z 风格，仅描述）
    var = sum((v - mean_null) ** 2 for v in null) / max(1, len(null) - 1)
    sd = var**0.5
    zlike = effect / sd if sd > 0 else None
    verdict = (
        "CONTRIBUTES"
        if p < 0.05 and effect > 0
        else "NO_CONTRIBUTION" if effect <= 0 else "INDETERMINATE"
    )
    return dict(
        verdict=verdict,
        real=round(real, 6),
        null_mean=round(mean_null, 6),
        effect=round(effect, 6),
        p=round(p, 6),
        n_perm=n_perm,
        seed=seed,
        zlike=(round(zlike, 3) if zlike is not None else None),
        evidence="PMID 40899589 (protein embeddings contributed minimally)",
        reason=(
            "组件贡献显著"
            if verdict == "CONTRIBUTES"
            else "置换后指标不低于真实：该组件贡献不显著，不得写'有效组件'"
        ),
        human_confirmation_required=True,
        negative_result_default=(
            "不采纳该组件为独立证据" if verdict == "NO_CONTRIBUTION" else None
        ),
    )


def batch_contribution(metric_fn, features, labels, component_indices, **kw):
    """多组件检验 + Holm 校正（复用 stats_ci.holm，不重复实现）。"""
    rows = []
    for name, idx in component_indices.items():
        r = permutation_contribution(metric_fn, features, labels, idx, **kw)
        r["component"] = name
        rows.append(r)
    try:
        from .stats_ci import holm
    except ImportError:  # 兼容 `python adt/perm_contribution.py --selftest` 直接运行
        import os as _os, sys as _sys

        _sys.path.insert(
            0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
        )
        from adt.stats_ci import holm
    valid = [r for r in rows if isinstance(r.get("p"), float)]
    if valid:
        adj = holm([r["p"] for r in valid], alpha=kw.get("alpha", 0.05))["family"]
        # holm().family 按原始 p 升序返回，每项带 idx（原序列下标）。
        # 必须按 idx 回填，不能 zip(valid, adj)——否则当传入顺序与 p 升序
        # 不一致时，校正后的 p/reject 会错配到错误的组件（结论完全颠倒）。
        for a in adj:
            r = valid[a["idx"]]
            r["p_holm"] = a["adj"]
            r["reject_holm"] = a["reject"]
    return rows


def selftest():
    rows = []

    def chk(name, cond, detail=""):
        rows.append(dict(name=name, ok=bool(cond), detail=detail))

    # 构造：col0 是强信号（与标签同向），col1 是纯噪声
    rng = random.Random(7)
    feats, labs = [], []
    for i in range(60):
        sig = 1 if i % 2 == 0 else 0
        noise = rng.random()
        feats.append([sig, noise])
        labs.append(sig)

    def acc(F, y):
        return sum(1 for r, v in zip(F, y) if (1 if r[0] >= 0.5 else 0) == v) / float(
            len(y)
        )

    r0 = permutation_contribution(acc, feats, labs, 0, n_perm=100)
    chk(
        "signal_contributes",
        r0["verdict"] == "CONTRIBUTES",
        "p=%s effect=%s" % (r0["p"], r0["effect"]),
    )
    # 检验一个真正无贡献的组件：metric_fn 只用 col0，置换 col1 不影响
    r1 = permutation_contribution(acc, feats, labs, 1, n_perm=100)
    chk(
        "noise_no_contribution",
        r1["verdict"] == "NO_CONTRIBUTION" or r1["p"] >= 0.05,
        "p=%s effect=%s" % (r1["p"], r1["effect"]),
    )
    # 小样本护栏
    r2 = permutation_contribution(acc, [[1], [0]], [1, 0], 0, n_perm=10)
    chk("small_n_guard", r2["verdict"] == "INDETERMINATE", "")
    # 批量 Holm
    batch = batch_contribution(acc, feats, labs, {"signals": 0, "noise": 1}, n_perm=60)
    chk(
        "batch_holm_wiring",
        all("p_holm" in r for r in batch),
        str([(r["component"], r.get("p_holm")) for r in batch]),
    )
    return all(x["ok"] for x in rows), rows


if __name__ == "__main__":
    import argparse, json

    ap = argparse.ArgumentParser(prog="perm-contribution")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        ok, rows = selftest()
        for r in rows:
            print(
                "[%s] %s %s"
                % ("OK" if r["ok"] else "FAIL", r["name"], r["detail"][:60])
            )
        print("[perm-contribution] %s" % ("PASS" if ok else "FAIL"))
        raise SystemExit(0 if ok else 4)
