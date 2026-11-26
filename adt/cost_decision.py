# -*- coding: utf-8 -*-
"""代价进入决策 + 会计恒等式审计（C18 / B6 / L+2，2026-11-04）。

外审 A 的独立复算（已在报告标注为「外审」，非本仓一手证据）：
    costs 在 pick_threshold / strategies 函数体内零引用（AST）；
    run_keystone.py:272-278 明写「同一预测，只改代价，不重训」；
    Δu(c) = a − q·c（q=弃权率），线性回归 R²=0.9999995、q=0.8189、c*=0.2598。
因此「无差异点存在且可估计」是线性函数零点的**代数必然**，不可证伪。

本模块提供两条真实出路：
1. `linearity_audit(points)` —— 在任何产物上机械判定 accounting_only；
2. `pi_cost_sensitive(probs, costs)` —— 代价**真正进入 decided_mask** 的参考实现，
   配合 `sweep_decision_masks()` 落每档 sha256(decided_mask)；若各档 hash 全同，
   说明代价仍未进入决策，必须标 accounting_only 并撤回 c*。

诚实边界：本模块是「正确参考实现」，不等于 run_keystone 的既有流水线已被替换。
迁移状态见 references/REVIEW_FINDINGS.yaml（C18）。
"""

from __future__ import annotations

import hashlib
import json
import math


def linearity_audit(points, r2_threshold=0.999):
    """points: [(cost, delta_utility)]。判定 Δu 是否为 c 的一阶线性会计恒等式。"""
    pts = [(float(c), float(u)) for c, u in points if c is not None and u is not None]
    if len(pts) < 3:
        return dict(status="insufficient_points", n=len(pts), accounting_only=None)
    n = len(pts)
    mx = sum(c for c, _ in pts) / n
    my = sum(u for _, u in pts) / n
    sxx = sum((c - mx) ** 2 for c, _ in pts)
    sxy = sum((c - mx) * (u - my) for c, u in pts)
    slope = sxy / sxx if sxx else 0.0
    intercept = my - slope * mx
    ss_tot = sum((u - my) ** 2 for _, u in pts)
    ss_res = sum((u - (intercept + slope * c)) ** 2 for c, u in pts)
    r2 = 1.0 - (ss_res / ss_tot) if ss_tot else 1.0
    c_star_algebraic = (intercept / (-slope)) if slope else None
    return dict(
        status="ok",
        n=n,
        r2=round(r2, 8),
        slope=round(slope, 6),
        intercept=round(intercept, 6),
        c_star_algebraic=(round(c_star_algebraic, 6) if c_star_algebraic else None),
        accounting_only=bool(r2 >= r2_threshold),
        interpretation=(
            "Δu(c) 对 c 近乎完全线性：代价只进入事后重标价，不进入决策。"
            "『无差异点存在且可估计』是会计恒等式，不是可证伪命题。"
            if r2 >= r2_threshold
            else "未达会计恒等式阈值；仍需检查 decided_mask 是否随 c 改变。"
        ),
        forbidden_claims=["c_star", "无差异点", "条件性优势区", "准入层条件性价值"],
    )


def pi_cost_sensitive(probs, costs, threshold=0.5):
    """代价真正进入决策掩码的参考实现。

    costs = (c_false_pass, c_false_fail, c_abstain)；probs 中数值为 P(FAIL)。
    对每个分子比较「判定为 FAIL / PASS / 弃权」的期望代价，取最小者。
    与既有 utility() 的区别：costs 改变会改变 decided_mask（不只是事后计分）。
    """
    c_fp_pass, c_fp_fail, c_abst = costs
    decided, actions = [], []
    for p in probs:
        p = min(1.0, max(0.0, float(p)))
        # 记号必须与 run_keystone.utility() 严格一致（2026-11-04 语义走查纠错）：
        #   c_fp_pass = 真 FAIL 被判 PASS 的成本 → 判 PASS 的期望代价按 P(FAIL)=p 计
        #   c_fp_fail = 真 PASS 被判 FAIL 的成本 → 判 FAIL 的期望代价按 P(PASS)=1-p 计
        # 旧写法把两者对调，导致贝叶斯阈值反向（c_fp_pass/(sum) 而非正确的
        # c_fp_fail/(sum)），会使代价扫描方向整体失真，必须修正。
        cost_pass = p * c_fp_pass
        cost_fail = (1.0 - p) * c_fp_fail
        cost_abst = float(c_abst)
        # 平局时优先弃权（保守）：弃权代价与最小判定代价相等也不强行判定。
        if cost_abst <= min(cost_fail, cost_pass):
            decided.append(False)
            actions.append("ABSTAIN")
        elif cost_fail < cost_pass:
            decided.append(True)
            actions.append("FAIL")
        else:
            decided.append(True)
            actions.append("PASS")
    return dict(
        decided_mask=decided,
        actions=actions,
        decided_mask_sha256=hashlib.sha256(
            json.dumps(decided).encode("utf-8")
        ).hexdigest(),
        n=len(decided),
        costs=list(costs),
    )


def sweep_decision_masks(probs, cost_grid):
    """每档代价落 sha256(decided_mask)；hash 集合大小=1 即 accounting_only。"""
    out = []
    for costs in cost_grid:
        r = pi_cost_sensitive(probs, costs)
        out.append(
            dict(
                costs=list(costs),
                decided_mask_sha256=r["decided_mask_sha256"],
                n_abstained=sum(1 for a in r["actions"] if a == "ABSTAIN"),
                n_decided=sum(r["decided_mask"]),
            )
        )
    hashes = {o["decided_mask_sha256"] for o in out}
    return dict(
        points=out,
        n_cost_points=len(out),
        distinct_decided_masks=len(hashes),
        accounting_only=bool(len(hashes) == 1),
        note=(
            "各档 decided_mask 完全相同 → 代价未进入决策，Δu 仅为事后重标价；"
            "必须标 accounting_only=true 并撤回 c*。"
            if len(hashes) == 1
            else "代价已进入决策掩码；Δu 不再是会计恒等式，可重新讨论可识别 estimand。"
        ),
    )


def forbid_accounting_claims(text, accounting_only=True):
    """供 adt.phrasing / adt.redlines 调用：accounting_only 时拦截对外文本。"""
    if not accounting_only:
        return dict(hits=[], advice="")
    bans = ["c_star", "c*", "无差异点", "条件性优势区", "准入层条件性价值"]
    hits = [b for b in bans if b in (text or "")]
    return dict(
        hits=hits,
        advice=(
            "Δu(c) 是会计恒等式（C18 / 外审 A 复算 R²=0.9999995）；"
            "禁止在对外文本中出现上述表述，见 references/RETRACTION_NOTE.md §5。"
        ),
    )


def audit_pipeline(pi_rows, legacy_points_by_endpoint=None, r2_threshold=0.999):
    """流水线级裁决：把「旧流水线是不是会计恒等式」与「新流水线代价是否进决策」分开。

    pi_rows               : run_keystone 的 π(c) 产物行，每行须带
                            endpoint / seed / cost_point / decided_mask_sha256
    legacy_points_by_endpoint : {endpoint: [(c_abstain, delta_utility_median)]}，
                            来自 cost_sweep 的 S4−S1 配对差值（**旧流水线**）

    关键判定分离（不得合并、不得互相洗白）：
      * legacy_accounting_only —— 旧结论 Δu/c* 是否为会计恒等式；为 True 则旧主张
        永久撤回，即使新流水线修好了也不能复活（estimand 需重新识别）。
      * cost_sensitive_decision_verified —— 新 π(c) 是否真的让 decided_mask 随 c 改变；
        这是「代价进入决策」的必要条件，不是「结论可识别」的充分条件。
    """
    groups = {}
    for r in pi_rows or []:
        key = (r.get("endpoint"), r.get("seed"))
        groups.setdefault(key, []).append(r)
    per_group = []
    for key in sorted(groups, key=lambda k: (str(k[0]), str(k[1]))):
        rs = groups[key]
        hashes = {r.get("decided_mask_sha256") for r in rs}
        per_group.append(
            dict(
                endpoint=key[0],
                seed=key[1],
                n_cost_points=len(rs),
                distinct_decided_masks=len(hashes),
                decision_varies_with_cost=bool(len(hashes) > 1),
            )
        )
    n_varying = sum(1 for g in per_group if g["decision_varies_with_cost"])
    verified = bool(per_group) and n_varying == len(per_group)

    legacy_audits = {}
    for ep, pts in (legacy_points_by_endpoint or {}).items():
        legacy_audits[str(ep)] = linearity_audit(pts, r2_threshold=r2_threshold)
    legacy_vals = [
        a.get("accounting_only")
        for a in legacy_audits.values()
        if a.get("status") == "ok"
    ]
    # 无合格点时按「未证否」处理：举证责任在作者，默认仍为会计恒等式。
    legacy_accounting = bool(legacy_vals) if legacy_vals else True

    return dict(
        schema_version="1.0",
        binding_items=["C18", "B6", "§5.1 复审", "L+2", "外审 A 独立复算"],
        legacy_linearity_by_endpoint=legacy_audits,
        legacy_accounting_only=legacy_accounting,
        legacy_claim_status="revoked_pending_estimand",
        cost_sensitive_groups=per_group,
        n_groups=len(per_group),
        groups_with_decision_varying=n_varying,
        cost_sensitive_decision_verified=verified,
        accounting_only=legacy_accounting,
        forbidden_claims=[
            "c_star",
            "c*",
            "无差异点",
            "条件性优势区",
            "准入层条件性价值",
        ],
        redline="R18_accounting_identity",
        note=(
            "新流水线证明代价进入决策，仅解除「会计恒等式」这一条技术缺陷；"
            "不等于 estimand 可识别、不等于准入层有净收益，也不使已撤回的 "
            "c* / 条件性优势区主张复活。旧主张须在 ESTIMAND.yaml 冻结后重新推导。"
        ),
    )
