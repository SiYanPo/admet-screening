# -*- coding: utf-8 -*-
"""工作包 H：选择性预测的风险-覆盖分析（risk–coverage）。

外部评审意见（2026-10-29）的核心攻击点：
  "如果一个框架对 42 个 分子×端点 全部输出 UNDETERMINED，它相对'直接说不知道'
   的增量价值是什么？" 以及 "在分布偏移下，弃权信号本身是否可靠？"

本模块回答两件事：
  1) 把弃权从"失败模式"变成可评估的**选择性预测**：给定置信分数，
     按分数从高到低保留，画 risk–coverage 曲线，算 AURC（越低越好）。
  2) 对比**结构性弃权**（源间分歧/域外/单位/票数）与**分数型弃权**
     （预测方差 / conformal 区间宽度 / 校准后 vote_confidence），
     看哪种在分布偏移子集上退化更慢。

诚实边界：
  - 没有实测真值时只能做 **proxy**（以多源多数票为伪标签），产物必须标
    `label_source=proxy_majority`，不得写成外部验证。
  - UNDETERMINED 不计入 risk 的分母（它是弃权，不是预测错误）；
    但它会降低 coverage，这正是曲线要表达的信息。
"""

import math

IN_DOMAIN = {"predicted", "measured", "saturated"}
UNIT_PROB = {"probability", "fraction"}
UNIT_CLASS = {"class", "class_0_1", "binary"}


def _f(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def structural_score(rec):
    """结构性置信分数（0=弃权，1=最可信）。规则透明、可审计。"""
    verdict = rec.get("verdict", "")
    conf = (rec.get("confidence") or "").lower()
    if verdict == "UNDETERMINED":
        return 0.0
    if verdict not in ("PASS", "FAIL"):
        return 0.0
    base = {"high": 1.0, "medium": 0.7, "low": 0.45}.get(conf, 0.45)
    if str(rec.get("pseudo_consensus") or "N").upper() == "Y":
        base = min(base, 0.35)
    return base


def spread_score(rec):
    """分数型弃权基线 1：源间分歧越小越可信（与 structural 独立）。"""
    try:
        s = float(rec.get("spread") or 0.0)
    except (TypeError, ValueError):
        s = 0.0
    return max(0.0, 1.0 - min(1.0, s / 0.5))


def vote_confidence_score(rec, table=None):
    """分数型弃权基线 2：来自 independence 校准表的 vote_confidence。"""
    vc = rec.get("vote_confidence")
    if vc not in ("", None):
        try:
            return float(vc)
        except (TypeError, ValueError):
            pass
    if table:
        try:
            k = int(rec.get("n_indep_groups") or 0)
            n = int(rec.get("n_in_domain") or 0)
            hit = [
                r
                for r in table
                if int(r.get("k", -1)) == k
                and int(r.get("n_raters", -1)) == n
                and r.get("vote_confidence") not in ("", None)
            ]
            if hit:
                return sum(float(x["vote_confidence"]) for x in hit) / len(hit)
        except (TypeError, ValueError):
            pass
    return spread_score(rec)


def risk_coverage(pairs, c_abstain=1.0, total_n=None):
    """pairs: [(score, correct_bool | None)]。返回 (points, aurc)。

    2026-11-04 / C06 + §5.1 复审：
    - `ok is None` 表示 **弃权/无真值**，按 `c_abstain` 计代价（默认 1.0，
      等价于一次错误；可由 COST_ELICITATION.md 的代价链配置）。
    - `total_n` 是**输入记录总数**（含弃权）。coverage = i/total_n，尾部
      [last_cov, 1] 按 c_abstain 补齐 → 弃权率进入 AURC，不再与曲线解耦。
    - 旧实现从 AURC 分母删掉 UNDETERMINED，使任何弃权率都得到满覆盖曲线，
      导致"弃权策略比较"无效（full_abstain_baseline 也不在同一坐标系）。
    - AURC 按阶梯积分（不用梯形法：梯形从 (0,0) 起算会把"全错"压到 0.83）。
    """
    n_total = int(total_n) if total_n else len(pairs)
    if n_total == 0:
        return [], None
    s = sorted(pairs, key=lambda x: -x[0])
    pts = []
    err = 0.0
    prev = 0.0
    aurc = 0.0
    for i, (_score, ok) in enumerate(s, 1):
        if ok is None:
            err += float(c_abstain)
        elif not ok:
            err += 1.0
        cov = i / float(n_total)
        risk = err / float(i)
        pts.append(dict(coverage=round(cov, 4), risk=round(risk, 4), n_retained=i))
        aurc += risk * (cov - prev)
        prev = cov
    if prev < 1.0:
        # 剩余为弃权/无真值样本：按 c_abstain 计代价，补齐到 coverage=1
        aurc += float(c_abstain) * (1.0 - prev)
        tail_risk = (err + float(c_abstain) * (n_total - len(s))) / float(n_total)
        pts.append(
            dict(
                coverage=1.0,
                risk=round(tail_risk, 4),
                n_retained=n_total,
                tail="abstained_or_no_truth",
            )
        )
    return pts, round(aurc, 4)


def risk_at(pts, target):
    """在指定 coverage 处的 risk（取最近的已保留点）。"""
    if not pts:
        return None
    best = min(pts, key=lambda p: abs(p["coverage"] - target))
    return best["risk"]


def conformal_width_score(rec, width_map):
    """分数型弃权基线 3：conformal 区间越窄越可信（区间宽 -> 低分）。"""
    w = (width_map or {}).get((rec.get("compound_id", ""), rec.get("endpoint", "")))
    if w in (None, ""):
        return 0.0
    try:
        w = float(w)
    except (TypeError, ValueError):
        return 0.0
    return 1.0 / (1.0 + max(0.0, w))


def _truth_map(truth_rows, rules):
    from .independence import _truth_binary

    out = {}
    for t in truth_rows or []:
        y = _truth_binary(t, rules)
        if y is None:
            continue
        out[(t.get("compound_id", ""), t.get("endpoint", ""))] = y
    return out


def _majority_map(measurements, rules):
    """以多源多数票为伪标签（0=PASS/阴性，1=FAIL/阳性）。"""
    from .reliability import _judge, _match_rule

    by_key = {}
    for r in measurements or []:
        if r.get("domain_flag") not in IN_DOMAIN:
            continue
        v = _f(r.get("value"))
        if v is None:
            continue
        key = (r.get("compound_id", ""), r.get("endpoint", ""))
        rule = _match_rule(r.get("endpoint", ""), rules or {}) or {}
        vd = _judge(v, rule) if rule else None
        if vd is None:
            continue
        by_key.setdefault(key, []).append(vd)
    out = {}
    for key, vds in by_key.items():
        n1 = sum(1 for x in vds if x == "FAIL")
        n0 = sum(1 for x in vds if x == "PASS")
        if n1 > n0:
            out[key] = 1
        elif n0 > n1:
            out[key] = 0
        # 平局不入标签
    return out


def holdout_eval(measurements, rules, source, groups=None, conformal=None):
    """留一源验证（非循环）：用 source 的裁决做标签，用其余源重算框架裁决。

    这不是"准确率"（source 本身也是预测），而是"多源裁决能否复现一个被留出的源"。
    相比 majority proxy，它切断了标签与分数共享同一证据的循环。
    """
    from .reliability import _judge, _match_rule, evaluate as rel_evaluate

    truth = []
    for r in measurements or []:
        if r.get("source") != source:
            continue
        v = _f(r.get("value"))
        rule = _match_rule(r.get("endpoint", ""), rules or {}) or {}
        vd = _judge(v, rule) if rule else None
        if vd in ("PASS", "FAIL"):
            truth.append(
                dict(
                    compound_id=r.get("compound_id", ""),
                    endpoint=r.get("endpoint", ""),
                    truth_class=vd,
                )
            )
    filt = [r for r in measurements or [] if r.get("source") != source]
    if not truth or not filt:
        return dict(
            methods={},
            label_source="holdout_" + source,
            error="留出源没有可判记录，或剩余源为空",
        )
    recs = rel_evaluate(filt, rules, source_groups=groups)
    res = evaluate(recs, truth, filt, rules, proxy="none", conformal=conformal)
    res["label_source"] = "holdout_" + source
    return res


def build_pairs(recs, label_map):
    """给**每条**记录配 (score 来源记录, correct_bool | None)。

    2026-11-04 / C06：不再删除 UNDETERMINED。分母不变性：
    len(build_pairs(recs, ...)) == len(recs) 恒成立。`None` = abstained
    （包括有 verdict 但配不到真值的记录），由 risk_coverage 按 c_abstain 计代价。
    """
    out = []
    for r in recs:
        v = r.get("verdict")
        key = (r.get("compound_id", ""), r.get("endpoint", ""))
        if v not in ("PASS", "FAIL"):
            out.append((r, None))
            continue
        if key not in label_map:
            out.append((r, None))
            continue
        truth_fail = label_map[key] == 1
        pred_fail = v == "FAIL"
        out.append((r, truth_fail == pred_fail))
    return out


def evaluate(
    recs,
    truth_rows=None,
    measurements=None,
    rules=None,
    proxy="none",
    vote_table=None,
    conformal=None,
):
    """返回 dict(methods={name: {points, aurc, risk80, risk90}}, label_source)。"""
    if truth_rows:
        label_map = _truth_map(truth_rows, rules)
        label_source = "measured_truth"
    elif proxy == "majority" and measurements:
        label_map = _majority_map(measurements, rules)
        label_source = "proxy_majority"
    else:
        return dict(
            methods={},
            label_source="none",
            error="无实测真值且未启用 --proxy majority：无法计算 risk（不臆造）",
        )

    pairs = build_pairs(recs, label_map)
    n_all = len(recs)
    n_abstained = sum(1 for _r, ok in pairs if ok is None)
    if not pairs:
        return dict(
            methods={},
            label_source=label_source,
            n_all=n_all,
            error="没有可配对的 (verdict, truth) 记录",
        )

    scorers = {
        "structural": lambda r: structural_score(r),
        "spread": lambda r: spread_score(r),
        "vote_confidence": lambda r: vote_confidence_score(r, vote_table),
    }
    if conformal:
        wmap = {
            (r.get("compound_id", ""), r.get("endpoint", "")): r.get("width")
            for r in conformal
            if r.get("width") not in ("", None)
        }
        scorers["conformal_width"] = lambda r: conformal_width_score(r, wmap)
    methods = {}
    for name, fn in scorers.items():
        # 弃权记录不调用 scorer（可能缺字段），赋 -inf 排到末尾 = 最后才被覆盖
        ps = [(fn(r) if ok is not None else float("-inf"), ok) for r, ok in pairs]
        pts, aurc = risk_coverage(ps, total_n=n_all)
        # 旧口径（仅已判定样本）保留作对照，但标 non_evidence，不参与任何比较
        decided = [(s, ok) for s, ok in ps if ok is not None]
        _pts_old, aurc_old = risk_coverage(decided)
        methods[name] = dict(
            points=pts,
            aurc=aurc,
            risk80=risk_at(pts, 0.80),
            risk90=risk_at(pts, 0.90),
            n=len(ps),
            n_all=n_all,
            n_abstained=n_abstained,
            abstention_rate=round(n_abstained / float(n_all), 4),
            denominator_fixed=True,
            coordinate_system="all_records_inclusive",
            aurc_conditional_on_decided=aurc_old,
            aurc_conditional_evidence_grade="non_evidence",
        )
    out = dict(
        methods=methods,
        label_source=label_source,
        error="",
        n_all=n_all,
        n_abstained=n_abstained,
        abstention_rate=round(n_abstained / float(n_all), 4),
        denominator_fixed=True,
    )
    if label_source == "proxy_majority":
        out.update(
            evidence_grade="non_evidence",
            comparable_for_prediction_check=False,
            circularity_note=(
                "proxy majority 用同批 measurements + 同一套 rules "
                "造伪标签评估同一 verdict，属循环论证；"
                "本产物 AURC 不得参与 sd/一致性比较（C06 / 外审 A N6）"
            ),
        )
    else:
        out.update(
            evidence_grade=(
                "measured_truth" if label_source == "measured_truth" else "holdout"
            ),
            comparable_for_prediction_check=True,
        )
    return out


def full_abstain_baseline(pairs, c_abstain=1.0, total_n=None):
    """全弃权基线（评审 P3）。

    2026-11-04 / C06：默认保留旧口径（向后兼容）；当调用方传入 total_n 时
    与 risk_coverage 统一到 `all_records_inclusive` 坐标系：coverage=0，
    risk=c_abstain（每个样本都弃权的平均代价），否则两者不可比。
    """
    if not pairs:
        return None
    if total_n:
        return dict(
            coverage=0.0,
            risk=round(float(c_abstain), 4),
            coordinate_system="all_records_inclusive",
            total_n=int(total_n),
            c_abstain=float(c_abstain),
            note="全弃权：coverage=0，risk=c_abstain（与含弃权曲线同坐标系）",
        )
    err = sum(1 for _s, ok in pairs if not ok)
    return dict(
        coverage=0.0,
        risk=round(err / float(len(pairs)), 4),
        coordinate_system="decided_only_legacy",
        note="全弃权（旧口径，仅供兼容；与 all_records_inclusive 曲线不可比）",
    )


def base_rate_stratified(pairs, strata):
    """按基率分层（评审 P3）：strata = [(label, sub_pairs), ...]，sub_pairs 同 (score, ok)。

    揭示"高基率端点好做、低基率端点难做"——曲线整体好看但分层后某层 risk 高，
    是 selective prediction 最常见的伪装，必须分层报告。
    """
    out = []
    n_all = len(pairs) or 1
    for label, sub in strata:
        if not sub:
            continue
        err = sum(1 for _s, ok in sub if not ok)
        n = len(sub)
        out.append(
            dict(
                stratum=label,
                n=n,
                risk=round(err / float(n), 4),
                coverage_cap=round(n / float(n_all), 4),
            )
        )
    return out


def risk_coverage_report(pairs, target_risk=0.2):
    """整合报告（评审 P3）：曲线 + AURC + 全弃权基线 + 最优弃权率。

    最优弃权率 = 1 − 满足 risk≤target_risk 的最大 coverage（代价矩阵最优弃权点）。
    """
    pts, aurc = risk_coverage(pairs)
    base = full_abstain_baseline(pairs)
    best_cov = 0.0
    for p in pts:
        if p["risk"] <= target_risk:
            best_cov = max(best_cov, p["coverage"])
    return dict(
        curve=pts,
        aurc=aurc,
        full_abstain=base,
        optimal_abstain_rate=round(1.0 - best_cov, 4),
        target_risk=target_risk,
    )


def summary_rows(result):
    out = []
    for name, m in sorted(result.get("methods", {}).items()):
        n = m["n"]
        status = "ok" if n >= 20 else ("weak" if n >= 10 else "insufficient")
        out.append(
            dict(
                method=name,
                n=n,
                aurc=m["aurc"],
                risk_at_80=m["risk80"],
                risk_at_90=m["risk90"],
                status=status,
                label_source=result.get("label_source", ""),
            )
        )
    return out


# ---- R15 / R18：校准分数驱动的 risk–coverage + 代价敏感曲线 -------------------
# 评审 C9 原话："最优弃权率 0.000 与'高风险层 27.3% 错误'并存，未解释……只可能是
# (i) 置信度分数未校准；(ii) 效用函数使弃权永不划算；(iii) 27.3% 本身噪声大。"
# 处置：三条同时给——(a) 分数强制走校准层并声明分数类型；(b) 代价比扫描；
#       (c) 分层错误率附 Clopper-Pearson 区间。
def risk_coverage_calibrated(pairs, score_kind="calibrated"):
    """pairs = [(score, correct_bool)]，**score 必须已校准**（本函数不校准，只断言）。

    返回曲线 + AURC，并在结果里写明 score_kind，避免"惩罚错误对象"（R1-2）。
    """
    if score_kind not in ("calibrated", "conformal_p", "raw"):
        raise ValueError("score_kind 必须是 calibrated/conformal_p/raw")
    pts, aurc = risk_coverage(pairs)  # 注意：返回 (points, aurc) 二元组
    return {
        "score_kind": score_kind,
        "curve": pts,
        "aurc": aurc,
        "note": ("raw 分数下的 AURC 不可用于结论；" "报告须写明分数类型（R1-2）"),
    }


def cost_sensitive_abstain(pairs, cost_grid=None):
    """R15(b)：不同代价比下的最优弃权率曲线（替代单点 0.000）。"""
    if cost_grid is None:
        cost_grid = [0.05, 0.1, 0.2, 0.3, 0.5, 0.8, 1.0, 1.5, 2.0]
    pts, _aurc_val = risk_coverage(pairs)
    n = len(pairs)
    out = []
    for c_abst in cost_grid:
        best = (None, -1e9)
        for p in pts:
            keep = int(round(p["coverage"] * n))
            if keep == 0:
                continue
            cost = p["risk"] * keep + c_abst * (n - keep)
            utility = -cost / float(n)
            if utility > best[1]:
                best = (p["coverage"], utility)
        out.append(
            {
                "cost_abstain": c_abst,
                "optimal_coverage": best[0],
                "optimal_abstain_rate": (
                    None if best[0] is None else round(1 - best[0], 3)
                ),
                "utility": round(best[1], 4) if best[0] is not None else None,
            }
        )
    return out


# ---------------------------------------------------------------------------
# R-C9：统一分数口径的 risk–coverage（评审 C9 的直接修补）
# ---------------------------------------------------------------------------
# 评审原话：旧版报"最优弃权率 0.000"，新版报"S4 覆盖率 0.182"——两个数字来自
# **不同的分数口径**（旧的是在离散票数差上扫，新的是在连续校准概率上扫），
# 因此不可比，换口径等于绕过了原问题。
#
# 修法不是"再挑一个口径"，而是**把所有策略压到同一个分数上**：
#   · 统一分数  score = |p_calibrated − 0.5|   （距决策边界越远越可信）
#   · 统一预测  pred  = (p_calibrated ≥ 0.5)   （与分数同一对象，避免边排序边换判据）
# 于是策略之间的唯一差异只剩**弃权规则**（哪些样本被判），这才是要比较的东西。
# 每个策略给出两个数：
#   coverage / risk_decided          它的实际运行点
#   frontier_risk_at_coverage        在同一 coverage 上，"纯按置信度取 top-c"能做到的 risk
#   efficiency_gap = risk_decided − frontier_risk
#       > 0 → 该策略的弃权选择比"只看置信度"更差（弃权选错了样本）
#       < 0 → 该策略额外用到的信息（域/分歧）确实挑出了更该弃权的样本
UNIFIED_COVERAGE_GRID = (
    0.05,
    0.10,
    0.15,
    0.20,
    0.25,
    0.30,
    0.40,
    0.50,
    0.60,
    0.70,
    0.80,
    0.90,
    1.00,
)


def unified_confidence(p_cal, pred=None):
    """统一置信度分数。p_cal 必须已校准（本函数不校准，调用方负责）。

    用距离 0.5 的绝对值而非 p 本身：p 是"FAIL 概率"，用它排序等于假设
    "越像 FAIL 越可信"，在 PASS 侧就会把高置信 PASS 排到末尾。绝对值对称，两侧都成立。
    """
    import numpy as _np

    p = _np.asarray(p_cal, dtype=float)
    return _np.abs(p - 0.5)


def unified_risk_coverage(y_true, pred, score, grid=None):
    """统一分数口径的 risk–coverage 曲线（全曲线，不是单点）。

    与 `risk_coverage()` 的区别：那个接受任意 (score, correct) 对，各策略可以喂不同
    分数（于是不可比）；本函数强制 y_true/pred/score 三者同源于**同一批校准概率**。
    """
    import numpy as _np

    y = _np.asarray(y_true).astype(int)
    p = _np.asarray(pred).astype(int)
    s = _np.asarray(score, dtype=float)
    n = len(y)
    if n == 0:
        return {"curve": [], "aurc": None, "n": 0}
    grid = tuple(grid or UNIFIED_COVERAGE_GRID)
    order = _np.argsort(-s, kind="mergesort")
    y, p = y[order], p[order]
    err = _np.cumsum((p != y).astype(int))
    curve = []
    for c in grid:
        k = max(1, min(n, int(round(c * n))))
        curve.append(
            {
                "coverage": round(k / float(n), 4),
                "risk": round(float(err[k - 1]) / k, 4),
                "n_kept": int(k),
            }
        )
    aurc, prev = 0.0, 0.0
    for pt in curve:
        aurc += pt["risk"] * (pt["coverage"] - prev)
        prev = pt["coverage"]
    return {
        "curve": curve,
        "aurc": round(aurc, 4),
        "n": int(n),
        "score_kind": "calibrated_absmargin",
        "note": (
            "AURC 越小越好；该曲线只按置信度排序，"
            "不含域/分歧信息——正是它的用途：作为弃权策略的对照前沿"
        ),
    }


def frontier_risk_at(curve, coverage):
    """在统一曲线上按 coverage 线性插值取 risk（用于与运行点对齐）。"""
    if not curve:
        return None
    pts = sorted(curve, key=lambda p: p["coverage"])
    if coverage <= pts[0]["coverage"]:
        return pts[0]["risk"]
    if coverage >= pts[-1]["coverage"]:
        return pts[-1]["risk"]
    for a, b in zip(pts, pts[1:]):
        if a["coverage"] <= coverage <= b["coverage"]:
            w = (coverage - a["coverage"]) / (b["coverage"] - a["coverage"])
            return round(a["risk"] * (1 - w) + b["risk"] * w, 4)
    return pts[-1]["risk"]


def operating_point(y_true, pred, decided, score, grid=None):
    """把一个策略的"实际运行点"放到统一前沿上做比较（C9 的核心输出）。

    decided: bool 数组，True=给出判定。
    返回 coverage / risk_decided / all_risk / frontier_risk_at_coverage /
         efficiency_gap（>0 差于纯置信度弃权，<0 好于）/ vs_random（相对不弃权）。
    """
    import numpy as _np

    y = _np.asarray(y_true).astype(int)
    p = _np.asarray(pred).astype(int)
    d = _np.asarray(decided).astype(bool)
    s = _np.asarray(score, dtype=float)
    n = len(y)
    cov = float(d.mean())
    all_risk = float(_np.mean(p != y))
    if d.sum() == 0:
        return {
            "coverage": 0.0,
            "risk_decided": None,
            "all_risk": round(all_risk, 4),
            "frontier_risk_at_coverage": frontier_risk_at(
                unified_risk_coverage(y, p, s, grid)["curve"], 0.0
            ),
            "efficiency_gap": None,
            "vs_random": None,
            "n_decided": 0,
        }
    risk = float(_np.mean(p[d] != y[d]))
    curve = unified_risk_coverage(y, p, s, grid)["curve"]
    fr = frontier_risk_at(curve, cov)
    return {
        "coverage": round(cov, 4),
        "risk_decided": round(risk, 4),
        "all_risk": round(all_risk, 4),
        "frontier_risk_at_coverage": fr,
        "efficiency_gap": (round(risk - fr, 4) if fr is not None else None),
        "vs_random": round(risk - all_risk, 4),
        "n_decided": int(d.sum()),
    }
