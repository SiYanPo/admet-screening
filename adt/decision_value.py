# -*- coding: utf-8 -*-
"""工作包 D：决策价值分析（UNDETERMINED 的决策论辩护）。

外部评审意见（2026-10-29）：
  "如果一个框架对 42 个 分子×端点 全部输出 UNDETERMINED，它相对'直接说不知道'
   的增量价值是什么？" 必须证明：在固定实验预算下，证据准入控制把实验资源
   从不可裁决区域重新分配到可裁决区域，减少强行共识导致的假阳性暴露。

本模块提供：
  1) decision_curve   经典 Vickers 净收益曲线（阈值概率 pt 下的净收益）
  2) resource_allocation  三策略对比：
       vote_all   对全部候选强行排序，按分数送前 budget 个
       admission  只送 PASS 且确定性 high/moderate；UNDETERMINED-可解决按
                  p_convert 折算为期望可救回数
       random     随机送 budget 个（基线）
     输出期望真阳性、假阳性、期望效用（TP - cost_fp * FP）。

诚实边界：没有实测真值时只能做 proxy（多源多数票）或 demo；产物必须标
label_source，且不得写成"提高了准确率"——只能说"在给定预算下的期望效用"。
"""

import math

IN_DOMAIN = {"predicted", "measured", "saturated"}


def _f(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _risk_score(rec):
    """越高 = 风险越大（越不该送）。用于 vote_all 排序。"""
    v = rec.get("verdict")
    if v == "FAIL":
        return 1.0
    if v == "PASS":
        return 0.0
    x = _f(rec.get("value_used"))
    if x is not None and (rec.get("unit") or "").lower() in ("probability", "fraction"):
        return x
    return 0.5


def decision_curve(scores, labels, thresholds=None):
    """scores: 预测"好"的概率（越高越好）；labels: 1=真好，0=真坏。

    返回 [(pt, n_selected, tp, fp, net_benefit)]；NB = TP/n - FP/n * (1-pt)/pt。
    """
    thresholds = thresholds or [i / 20.0 for i in range(1, 20)]
    n = len(scores)
    out = []
    for pt in thresholds:
        sel = [(s, y) for s, y in zip(scores, labels) if s >= pt]
        tp = sum(1 for _s, y in sel if y == 1)
        fp = sum(1 for _s, y in sel if y == 0)
        nb = (tp / float(n)) - (fp / float(n)) * ((1.0 - pt) / pt)
        out.append(
            dict(
                pt=round(pt, 3),
                n_selected=len(sel),
                tp=tp,
                fp=fp,
                net_benefit=round(nb, 4),
            )
        )
    return out


def _good_map(truth_rows, rules):
    """truth -> 1=真好(PASS) / 0=真坏(FAIL)。"""
    from .reliability import _judge, _match_rule

    out = {}
    for t in truth_rows or []:
        ep = t.get("endpoint", "")
        tc = (t.get("truth_class") or "").strip().upper()
        if tc == "PASS":
            out[(t.get("compound_id", ""), ep)] = 1
            continue
        if tc == "FAIL":
            out[(t.get("compound_id", ""), ep)] = 0
            continue
        v = _f(t.get("truth_value"))
        rule = _match_rule(ep, rules or {}) or {}
        if v is None or not rule:
            continue
        vd = _judge(v, rule)
        if vd == "PASS":
            out[(t.get("compound_id", ""), ep)] = 1
        elif vd == "FAIL":
            out[(t.get("compound_id", ""), ep)] = 0
    return out


def _proxy_map(measurements, rules):
    """多源多数票作为伪标签（1=多数 PASS，0=多数 FAIL）。"""
    from .reliability import _judge, _match_rule

    by_key = {}
    for r in measurements or []:
        if r.get("domain_flag") not in IN_DOMAIN:
            continue
        v = _f(r.get("value"))
        rule = _match_rule(r.get("endpoint", ""), rules or {}) or {}
        if v is None or not rule:
            continue
        vd = _judge(v, rule)
        if vd in ("PASS", "FAIL"):
            by_key.setdefault(
                (r.get("compound_id", ""), r.get("endpoint", "")), []
            ).append(vd)
    out = {}
    for key, vds in by_key.items():
        n0 = sum(1 for x in vds if x == "PASS")
        n1 = sum(1 for x in vds if x == "FAIL")
        if n0 > n1:
            out[key] = 1
        elif n1 > n0:
            out[key] = 0
    return out


def _aggregate_by_compound(recs, good_map):
    """分子级状态机：FAIL 支配 > 不可解决 > 可解决 > 全 PASS。

    不用"最差端点"单条记录：一个分子可能 3 个端点 PASS、1 个端点可解决，
    按最差记录会被误判成"整分子不可用"，从而让准入策略永远选不到人。
    """
    from .certainty import classify

    by_c = {}
    for r in recs:
        cid = r.get("compound_id", "")
        by_c.setdefault(cid, []).append(r)
    out = {}
    for cid, rs in by_c.items():
        rs2 = [r for r in rs if (cid, r.get("endpoint")) in good_map]
        if not rs2:
            continue
        annotated = [(r,) + classify(r) for r in rs2]  # (rec, cert, why)
        fails = [x for x in annotated if x[0].get("verdict") == "FAIL"]
        unres = [x for x in annotated if x[1] == "low_unresolvable"]
        res = [
            x
            for x in annotated
            if x[1] in ("low_resolvable", "medium_needs_experiment")
        ]
        passes = [x for x in annotated if x[0].get("verdict") == "PASS"]
        if fails:
            verdict, cert = "FAIL", "moderate"
        elif unres:
            verdict, cert = "UNDETERMINED", "low_unresolvable"
        elif res:
            verdict, cert = "UNDETERMINED", "low_resolvable"
        elif passes:
            verdict, cert = "PASS", "moderate"
        else:
            continue
        risk = max(_risk_score(r) for r in rs2)
        tv = [good_map.get((cid, r.get("endpoint"))) for r in rs2]
        truth_good = (
            1
            if (any(v == 1 for v in tv) and all(v == 1 for v in tv if v is not None))
            else 0
        )
        out[cid] = dict(
            risk=risk,
            verdict=verdict,
            certainty=cert,
            n=len(rs2),
            truth_good=truth_good,
        )
    return out


def resource_allocation(recs, good_map, budget=10, cost_fp=3.0, p_convert=0.5):
    """三策略的期望效用（按 worst-endpoint 聚合到分子级）。"""
    agg = _aggregate_by_compound(recs, good_map)
    if not agg:
        return [], dict(error="没有可配对 (分子, 端点) 标签")
    cids = sorted(agg)

    # A: vote_all —— 按 risk 升序
    a_sorted = sorted(cids, key=lambda c: (agg[c]["risk"], c))
    a_sel = a_sorted[:budget]

    # B: admission —— 先 PASS 且 high/moderate；再 UNDETERMINED-可解决按 p_convert
    def cert_rank(c):
        m = agg[c]["certainty"]
        return {
            "high": 0,
            "moderate": 1,
            "medium_needs_experiment": 2,
            "low_resolvable": 3,
        }.get(m, 4)

    b_conf = [
        c
        for c in cids
        if agg[c]["verdict"] == "PASS" and agg[c]["certainty"] in ("high", "moderate")
    ]
    b_res = [c for c in cids if agg[c]["certainty"] == "low_resolvable"]
    b_conf = sorted(b_conf, key=lambda c: (cert_rank(c), agg[c]["risk"], c))
    b_sel = b_conf[:budget]
    remaining = max(0, budget - len(b_sel))
    b_sel_extra = b_res[:remaining]

    # C: random —— 期望值 = budget * base_rate
    base = sum(1 for c in cids if agg[c]["truth_good"] == 1) / float(len(cids))

    def _tally(selected):
        tp = sum(1 for c in selected if agg[c]["truth_good"] == 1)
        fp = sum(1 for c in selected if agg[c]["truth_good"] == 0)
        return tp, fp

    a_tp, a_fp = _tally(a_sel)
    b_tp, b_fp = _tally(b_sel)
    # 可解决子集按 p_convert 折算期望
    b_extra_good = sum(p_convert for c in b_sel_extra if agg[c]["truth_good"] == 1)
    b_extra_bad = sum(p_convert for c in b_sel_extra if agg[c]["truth_good"] == 0)
    b_tp_exp = b_tp + b_extra_good
    b_fp_exp = b_fp + b_extra_bad

    def row(name, n_sel, tp, fp, note=""):
        return dict(
            strategy=name,
            n_selected=round(n_sel, 2),
            tp=round(tp, 2),
            fp=round(fp, 2),
            expected_utility=round(tp - cost_fp * fp, 2),
            utility_per_experiment=round((tp - cost_fp * fp) / max(n_sel, 1e-9), 3),
            note=note,
        )

    return [
        row("vote_all", len(a_sel), a_tp, a_fp, "全部候选强行排序后取前 budget"),
        row(
            "admission",
            len(b_sel) + p_convert * len(b_sel_extra),
            b_tp_exp,
            b_fp_exp,
            "PASS+确定性优先；UNDETERMINED-可解决按 p_convert=%.2f 折算" % p_convert,
        ),
        row(
            "random",
            budget,
            budget * base,
            budget * (1 - base),
            "基线：随机送 budget 个（base_rate=%.2f）" % base,
        ),
    ], dict(
        n_compounds=len(cids),
        base_rate=round(base, 4),
        n_confident=len(b_conf),
        n_resolvable=len(b_res),
        n_undetermined=sum(1 for c in cids if agg[c]["verdict"] == "UNDETERMINED"),
    )


def bayes_three_state(p_bad, c_fp=1.0, c_fn=5.0, c_defer=0.5):
    """贝叶斯决策层（评审 L1-1）：后验风险 p_bad=P(坏|证据) → 三态最优动作。

    动作期望代价（代价矩阵，默认取自筛选场景：放行坏化合物的代价 >> 误杀好化合物）：
      PASS  : 若真坏付 c_fn（漏检/误放行，下游浪费大），真好付 0
      FAIL  : 若真好付 c_fp（误杀/机会成本），真坏付 0
      UNDETERMINED : 固定 defer 代价 c_defer（再实验或弃）
    选期望代价最小者。

    UNDETERMINED 为最优 当且仅当
      c_defer < min(c_fp·(1-p_bad), c_fn·p_bad)
    —— 即当"花 c_defer 再确认"比直接判 PASS 或 FAIL 都便宜时，理智选择是弃权。
    这把 UNDETERMINED 从"不可推导的占位"变成"代价比可推导的量"（评审核心要求）。
    """
    p_good = 1.0 - p_bad
    ec_pass = c_fn * p_bad
    ec_fail = c_fp * p_good
    ec_und = c_defer
    costs = dict(PASS=ec_pass, FAIL=ec_fail, UNDETERMINED=ec_und)
    best = min(costs, key=costs.get)
    return dict(
        p_bad=round(p_bad, 4),
        p_good=round(p_good, 4),
        expected_cost=round(costs[best], 4),
        action=best,
        costs=dict((k, round(v, 4)) for k, v in costs.items()),
    )


def cost_ratio_sensitivity_grid(p_bad, c_fn=5.0, c_fp=1.0, defer_grid=None):
    """评审 L1-3：在 c_defer 网格上找 UNDETERMINED 为最优的"稳定区"。

    稳定区 = 使 bayes_three_state 返回 UNDETERMINED 的 c_defer 区间。
    报告只报稳定区内的结论（区间外应直接二态判），避免把"恰好取某 c_defer"当普适结论。
    """
    defer_grid = defer_grid or [0.05, 0.1, 0.2, 0.3, 0.5, 0.8, 1.0, 1.5, 2.0]
    rows = []
    for c_def in defer_grid:
        r = bayes_three_state(p_bad, c_fp=c_fp, c_fn=c_fn, c_defer=c_def)
        rows.append(
            dict(c_defer=c_def, action=r["action"], expected_cost=r["expected_cost"])
        )
    stable = [r["c_defer"] for r in rows if r["action"] == "UNDETERMINED"]
    if stable:
        return dict(
            rows=rows,
            undetermined_region=(min(stable), max(stable)),
            note=(
                "UNDETERMINED 在 c_defer∈[%.2f, %.2f] 为最优（稳定区）；"
                "低于下界应直接判 FAIL/PASS，高于上界也应直接二态判"
                % (min(stable), max(stable))
            ),
        )
    return dict(
        rows=rows,
        undetermined_region=None,
        note="给定成本结构下 UNDETERMINED 从不为最优——应直接二态判",
    )


def build(
    recs,
    truth_rows=None,
    measurements=None,
    rules=None,
    proxy="none",
    budget=10,
    cost_fp=3.0,
    p_convert=0.5,
):
    if truth_rows:
        good_map, label_source = _good_map(truth_rows, rules), "measured_truth"
    elif proxy == "majority" and measurements:
        good_map, label_source = _proxy_map(measurements, rules), "proxy_majority"
    else:
        return dict(
            error="无实测真值且未启用 --proxy majority：不臆造决策价值",
            label_source="none",
        )
    rows, meta = resource_allocation(recs, good_map, budget, cost_fp, p_convert)
    # 决策曲线：用 1-risk 作为"好"的概率
    agg = _aggregate_by_compound(recs, good_map)
    cids = sorted(agg)
    scores = [1.0 - agg[c]["risk"] for c in cids]
    labels = [1 if agg[c]["truth_good"] == 1 else 0 for c in cids]
    curve = decision_curve(scores, labels) if len(scores) >= 2 else []
    return dict(rows=rows, meta=meta, curve=curve, label_source=label_source, error="")


# ---- R16 / B3：UNDETERMINED 四细分 + 弱推荐方向 -----------------------------
# 评审 B3 原话："UNDETERMINED 不再是无差别弃权，而细分 undet_domain / undet_conflict /
# undet_insufficient_votes / undet_power，各自附'若必须决策的建议方向'。"
UNDET_SUBTYPES = {
    "undet_domain": "端点/分子在适用域外（域外不带值）",
    "undet_conflict": "源间方向冲突（source_conflict）",
    "undet_insufficient_votes": "独立方法组不足（<2 有效票）",
    "undet_power": "样本量/功效不足（结构性原因，非证据缺失）",
    "undet_low_validity": "端点被登记为'不推荐计算'（R21）",
}


def classify_undetermined(reason_text):
    """把自由文本归因映射到四（五）个细分类型。"""
    r = (reason_text or "").lower()
    if "not_recommended" in r or "low_validity" in r:
        return "undet_low_validity"
    if "conflict" in r or "方向相反" in r or "方向冲突" in r:
        return "undet_conflict"
    if "sample_size" in r or "power" in r or "功效" in r:
        return "undet_power"
    if "独立" in r or "independent" in r or "票" in r:
        return "undet_insufficient_votes"
    if "域外" in r or "domain" in r or "out_of_domain" in r:
        return "undet_domain"
    return "undet_insufficient_votes"


def weak_recommendation(
    subtype, per_source_votes=None, p_bad=None, c_fp=1.0, c_fn=5.0, c_defer=0.5
):
    """若必须决策，给出**弱推荐**方向并明确标注不可作为裁决。

    - conflict：按逐源理由给多数倾向，标注"分歧未解，弱推荐"
    - insufficient_votes：按已有一票方向（弱）
    - domain/power/low_validity：不给方向（诚实：没有依据）
    """
    if subtype == "undet_conflict":
        if not per_source_votes:
            return {
                "direction": None,
                "strength": "none",
                "note": "源冲突且无逐源票，无法给弱推荐",
            }
        pos = sum(1 for v in per_source_votes if v and v > 0)
        neg = sum(1 for v in per_source_votes if v and v < 0)
        if pos == neg:
            return {"direction": None, "strength": "none", "note": "正负票数相等"}
        d = "FAIL" if pos > neg else "PASS"
        return {
            "direction": d,
            "strength": "weak",
            "note": "分歧未解（%d 正 / %d 负）；仅作沟通用，不得写入裁决" % (pos, neg),
        }
    if subtype == "undet_insufficient_votes":
        if not per_source_votes:
            return {"direction": None, "strength": "none", "note": "无票"}
        v = [x for x in per_source_votes if x]
        if not v:
            return {"direction": None, "strength": "none", "note": "无有效票"}
        d = "FAIL" if sum(v) > 0 else "PASS"
        return {
            "direction": d,
            "strength": "weak",
            "note": "仅 1 个独立组，方向不具证据强度",
        }
    return {
        "direction": None,
        "strength": "none",
        "note": "该细分类型不提供方向（域外/功效不足/低有效性）",
    }
