# -*- coding: utf-8 -*-
"""工作包 E：与 Dempster-Shafer（DST）/ WoE 传统的对照。

外部评审意见（2026-10-29）：三态输出在形式上与 DST 同构，审稿人一定会问
"为什么不直接用 DST 组合？" 答案不是"我们更好"，而是**分工**：
  DST 处理的是"已知证据体之间的冲突组合"；
  ADMET 多源场景的核心问题之一是"某个证据体是否应该被赋予非零 mass"本身。
  本框架的 class blocks / out_of_domain 无值 / 单位守卫 = **证据准入控制**，
  是组合的前置层，而不是替代品。

本模块实现一个最小 DST（Dempster / Yager）+ 两种准入策略的对照：
  all_in    域外源赋 ignorance mass（theta=1），全部进入组合
  admission 域外源不进入组合（本框架做法），只进入 action 列表
比较两者在域外子集上的裁决分布与冲突系数 K。
预期：all_in 会把"准入失败"稀释成看似有界的 Bel/Pl；admission 则明确拒绝。
"""

import math

IN_DOMAIN = {"predicted", "measured", "saturated"}
UNIT_PROB = {"probability", "fraction"}
UNIT_CLASS = {"class", "class_0_1", "binary"}
FOCAL = ("pos", "neg", "theta")


def _f(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _unit_kind(u):
    u = (u or "").strip().lower()
    if u in UNIT_PROB:
        return "prob"
    if u in UNIT_CLASS:
        return "class"
    return "other"


def mass_from_value(value, unit):
    """把一个源的值转成 {pos, neg, theta} 的 mass（pos=风险阳性/FAIL）。"""
    v = _f(value)
    if v is None:
        return dict(pos=0.0, neg=0.0, theta=1.0)
    k = _unit_kind(unit)
    if k == "prob":
        p = max(0.0, min(1.0, v))
        return dict(pos=p, neg=1.0 - p, theta=0.0)
    if k == "class":
        p = 1.0 if v >= 0.5 else 0.0
        return dict(pos=p, neg=1.0 - p, theta=0.0)
    return dict(pos=0.0, neg=0.0, theta=1.0)


def ignorance():
    return dict(pos=0.0, neg=0.0, theta=1.0)


def _combine2(m1, m2, rule="dempster"):
    K = m1["pos"] * m2["neg"] + m1["neg"] * m2["pos"]
    res = dict(pos=0.0, neg=0.0, theta=0.0)
    inter = {
        ("pos", "pos"): "pos",
        ("pos", "neg"): None,
        ("pos", "theta"): "pos",
        ("neg", "pos"): None,
        ("neg", "neg"): "neg",
        ("neg", "theta"): "neg",
        ("theta", "pos"): "pos",
        ("theta", "neg"): "neg",
        ("theta", "theta"): "theta",
    }
    for A in FOCAL:
        for B in FOCAL:
            c = inter[(A, B)]
            if c is not None:
                res[c] += m1[A] * m2[B]
    if rule == "dempster":
        if 1.0 - K < 1e-12:
            return None, K
        for k in FOCAL:
            res[k] /= 1.0 - K
    elif rule == "yager":
        res["theta"] += K  # 冲突归入 ignorance，不归一化
    else:
        raise ValueError("rule 只支持 dempster / yager")
    return res, K


def combine(masses, rule="dempster"):
    """顺序两两组合。返回 (mass, K_total)；K_total 取各步最大（保守报告）。"""
    if not masses:
        return None, 0.0
    cur = masses[0]
    k_max = 0.0
    for m in masses[1:]:
        nxt, K = _combine2(cur, m, rule)
        k_max = max(k_max, K)
        if nxt is None:
            return None, 1.0
        cur = nxt
    return cur, k_max


def belief_plausibility(m):
    if m is None:
        return None
    return dict(
        bel_pos=round(m["pos"], 4),
        pl_pos=round(m["pos"] + m["theta"], 4),
        bel_neg=round(m["neg"], 4),
        pl_neg=round(m["neg"] + m["theta"], 4),
        ignorance=round(m["theta"], 4),
    )


def decide(bp, bel_threshold=0.5):
    if bp is None:
        return "UNDETERMINED", "no_evidence"
    if bp["bel_pos"] >= bel_threshold:
        return "FAIL", "bel_pos>=%.2f" % bel_threshold
    if bp["bel_neg"] >= bel_threshold:
        return "PASS", "bel_neg>=%.2f" % bel_threshold
    # 用 Pl 判断是否"可能阳性/阴性"，但 Bel 不足 -> 不确定
    return "UNDETERMINED", "bel<%.2f (pl_pos=%.2f, pl_neg=%.2f)" % (
        bel_threshold,
        bp["pl_pos"],
        bp["pl_neg"],
    )


def _canon_ep(ep):
    try:
        from .endpoints import canonical_name

        return canonical_name(ep) or (ep or "").strip().lower()
    except Exception:  # pragma: no cover
        return (ep or "").strip().lower()


def compare(measurements, rule="dempster", blocked=None, reliability=None):
    """返回 per (cid, ep) 的 all_in vs admission 对照行。

    blocked: {(source, canonical_endpoint)} —— registry 登记的"本化学类域外"。
      这类源在数据里可能仍带 probability 值（如 ADMETlab DILI 14/14 全阳）。
      all_in 会把它当正常证据参与组合；admission 会把它排除。
    reliability: 可选 reliability.csv 行；用于报告"DST 判死但框架弃权"的过度裁决。
    """
    blocked = blocked or set()
    rel = {
        (r.get("compound_id", ""), r.get("endpoint", "")): r
        for r in (reliability or [])
    }
    by_key = {}
    for r in measurements or []:
        by_key.setdefault((r.get("compound_id", ""), r.get("endpoint", "")), []).append(
            r
        )
    out = []
    for (cid, ep), rows in sorted(by_key.items()):
        masses_all, masses_adm = [], []
        n_dom = 0
        n_blocked = 0
        for r in rows:
            in_dom = r.get("domain_flag") in IN_DOMAIN
            is_blocked = (r.get("source", ""), _canon_ep(ep)) in blocked
            if in_dom:
                n_dom += 1
            if is_blocked:
                n_blocked += 1
            m = (
                mass_from_value(r.get("value"), r.get("unit"))
                if in_dom
                else ignorance()
            )
            masses_all.append(m)  # all_in：域外=ignorance，但 blocked 仍按值投票
            if in_dom and not is_blocked:
                masses_adm.append(m)  # admission：域外 + blocked 都排除
        ma, Ka = combine(masses_all, rule) if masses_all else (None, 0.0)
        madm, Kadm = combine(masses_adm, rule) if masses_adm else (None, 0.0)
        bpa, bpadm = belief_plausibility(ma), belief_plausibility(madm)
        da, ra = decide(bpa)
        dadm, radm = decide(bpadm)
        rv = (rel.get((cid, ep)) or {}).get("verdict", "")
        overclaim = "Y" if (da in ("PASS", "FAIL") and rv == "UNDETERMINED") else "N"
        out.append(
            dict(
                compound_id=cid,
                endpoint=ep,
                n_total=len(rows),
                n_in_domain=n_dom,
                n_blocked=n_blocked,
                allin_conflict=round(Ka, 4),
                allin_bel_pos=("" if bpa is None else bpa["bel_pos"]),
                allin_pl_pos=("" if bpa is None else bpa["pl_pos"]),
                allin_ignorance=("" if bpa is None else bpa["ignorance"]),
                allin_decision=da,
                allin_reason=ra,
                adm_conflict=round(Kadm, 4),
                adm_bel_pos=("" if bpadm is None else bpadm["bel_pos"]),
                adm_pl_pos=("" if bpadm is None else bpadm["pl_pos"]),
                adm_ignorance=("" if bpadm is None else bpadm["ignorance"]),
                adm_decision=dadm,
                adm_reason=radm,
                decisions_differ=("Y" if da != dadm else "N"),
                reliab_verdict=rv,
                dst_overclaims=overclaim,
            )
        )
    return out


def summarize(rows):
    n = len(rows)
    diff = sum(1 for r in rows if r["decisions_differ"] == "Y")
    allin_decisive = sum(1 for r in rows if r["allin_decision"] in ("PASS", "FAIL"))
    adm_decisive = sum(1 for r in rows if r["adm_decision"] in ("PASS", "FAIL"))
    overclaim = sum(1 for r in rows if r.get("dst_overclaims") == "Y")
    return dict(
        n=n,
        n_decisions_differ=diff,
        allin_decisive=allin_decisive,
        admission_decisive=adm_decisive,
        allin_overclaim=allin_decisive - adm_decisive,
        dst_overclaims_vs_reliab=overclaim,
    )
