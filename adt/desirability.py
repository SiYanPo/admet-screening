# -*- coding: utf-8 -*-
"""s6：desirability + 几何平均 + Pareto 前沿 + 排名守卫。

设计原则（都来自本项目的实测教训，见 references/04_decision_funnel.md）：

1) **单端点 desirability ∈ [0,1]**，形状由 rules yaml 的 shape 定义。
2) **同轴内用几何平均**，不用加权和：
   加权和会被长板补偿——一个端点 0.99 能拉回另一个端点 0.10，
   这正是本项目 MPO Spearman ρ=0.024 的原因之一。
3) **UNDETERMINED 既不当 1 也不当 0**：
   - 当 1 = "没证据=好"，是毒理学里最危险的默认；
   - 当 0 = "没证据=坏"，会把"数据不够"和"分子差"混为一谈。
   正确做法：UNDETERMINED 端点**不进几何平均**，但会计入分母
   （n_axis_all）。轴覆盖率 = n_audited / n_all 低于阈值时，
   该轴分数标 `insufficient_coverage`，不参与 Pareto。
4) **Pareto 前沿替代排名**：在没有排名资格时（can_rank 三条件不满足），
   只输出"哪些分子不被任何其他分子在所有轴上同时超越"。
5) **FAIL 端点 = desirability 0**，会真实拉低几何平均——这是有意的：
   PASS/FAIL 是阈值判定，比连续 desirability 更硬。

输出两张表：
  desirability.csv   分子 × 端点 × desirability（含 verdict 回填）
  axis_scores.csv    分子 × 轴 × 几何平均 + 覆盖率 + Pareto 标记
"""

import csv
import io
import math
import os

# 轴覆盖率低于此值时，该轴分数标 insufficient_coverage，不参与 Pareto
AXIS_COVERAGE_MIN = 0.5


def _f(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def desirability(value, rule):
    """按 shape 算单端点 desirability ∈ [0,1]。

    返回 None 表示"该端点不该打分"（shape=none 或 value 缺失）。
    """
    if rule is None:
        return None
    shape = rule.get("shape", "down")
    if shape == "none" or value is None:
        return None
    v = _f(value)
    if v is None:
        return None

    if shape == "up":
        p, f = rule.get("pass"), rule.get("fail")
        if p is None:
            return None
        lo = f if f is not None else p * 0.2  # fail 缺省 = pass 的 20%
        if p <= lo:
            return None
        return _clamp((v - lo) / (p - lo))

    if shape == "down":
        p, f = rule.get("pass"), rule.get("fail")
        if f is None:
            return None
        hi = p if p is not None else f * 0.3  # pass 缺省 = fail 的 30%
        if f <= hi:
            return None
        return _clamp((f - v) / (f - hi))

    if shape == "window":
        lo, hi = rule.get("window", [-1, 3])
        soft = rule.get("soft", [lo - (hi - lo), hi + (hi - lo)])
        if lo <= v <= hi:
            return 1.0
        if v < lo:  # 左侧：soft_lo→0, window_lo→1
            slo = soft[0]
            return _clamp((v - slo) / (lo - slo)) if slo < lo else 0.0
        shi = soft[1]  # 右侧：window_hi→1, soft_hi→0
        return _clamp((shi - v) / (shi - hi)) if shi > hi else 0.0

    if shape == "step":
        f = rule.get("fail")
        if f is None:
            return None
        # 阶跃不做软过渡：过线 1.0，未过 0.0
        return 0.0 if v > f else 1.0

    return None


def _geo(vals, weights=None):
    """几何平均（可加权）。任一值为 0 时结果为 0（有意的：FAIL 真实拉低分）。

    加权形式即 Derringer-Suich (1980) 的总 desirability：
        D = (∏ d_i^{w_i}) ^ (1/Σw_i)
    等权时退化为普通几何平均——所以 w_i 是**指数（importance）**，
    不是线性系数：w=2 表示"该响应的重要性相当于两个等权响应"，
    而不是"该响应的得分乘 2"。这一点在 1980 年原文与 CNS MPO 的实现里是一致的，
    写成线性加权和会破坏"任一 d=0 则 D=0"的性质（那正是本模块要的"不能有致命短板"）。

    文献：Derringer G, Suich R. J Qual Technol. 1980;12(4):214-219.
    """
    if not vals:
        return None
    if weights is None:
        p = 1.0
        for v in vals:
            p *= max(v, 0.0)
        return p ** (1.0 / len(vals))
    wsum = sum(weights)
    if wsum <= 0:
        return _geo(vals)
    acc = 0.0
    for v, w in zip(vals, weights):
        x = max(v, 0.0)
        if x <= 0.0:
            return 0.0  # 任一短板 → 总分为 0（Derringer-Suich 的定义性质）
        acc += w * math.log(x)
    return math.exp(acc / wsum)


def load_rules(path):
    import yaml

    d = yaml.safe_load(io.open(path, encoding="utf-8"))
    out = {}
    for e in d.get("endpoints", []):
        out[e["id"]] = e
    return out


def _w_of(endpoint, rules):
    """端点权重（默认 1.0）。负值视为 0——权重是"重要性"，不能为负。"""
    r = rules.get(endpoint) or {}
    try:
        w = float(r.get("weight", 1.0))
    except (TypeError, ValueError):
        return 1.0
    return max(0.0, w)


def compound_scores(reliability_rows, rules):
    """输入 reliability.csv 的行，输出 分子 × 轴 的几何平均与覆盖率。

    返回 (per_endpoint, per_axis)：
      per_endpoint: list[dict] 分子×端点×desirability
      per_axis:     list[dict] 分子×轴×geo_mean/coverage/pareto
    """
    # 分子 × 端点 -> (verdict, value_used, rule)
    per_ep = {}
    for r in reliability_rows:
        if r.get("verdict") == "PASSTHRU":
            continue  # 参照/适用域端点不进轴聚合（v2.1）
        cid, ep = r["compound_id"], r["endpoint"]
        rule = rules.get(ep)
        if rule is None:
            # 可靠性模块允许子串匹配，这里对齐同样的宽松匹配
            from .reliability import _match_rule

            rule = _match_rule(ep, rules)
        if rule is None:
            continue
        v = _f(r.get("value_used"))
        vd = r.get("verdict")
        d = desirability(v, rule)
        per_ep.setdefault(cid, {})[ep] = dict(
            verdict=vd,
            value=v,
            desirability=d,
            axis=rule.get("axis") or "ungrouped",
            confidence=r.get("confidence", ""),
        )

    ep_rows = []
    axis_rows = []
    axes = sorted(
        {
            info["axis"]
            for c in per_ep.values()
            for info in c.values()
            if info["axis"] not in ("coverage", "ungrouped")
        }
    )

    for cid in sorted(per_ep):
        eps = per_ep[cid]
        for ep, info in sorted(eps.items()):
            ep_rows.append(
                dict(
                    compound_id=cid,
                    endpoint=ep,
                    axis=info["axis"],
                    value=("" if info["value"] is None else round(info["value"], 4)),
                    verdict=info["verdict"],
                    desirability=(
                        ""
                        if info["desirability"] is None
                        else round(info["desirability"], 4)
                    ),
                    confidence=info["confidence"],
                )
            )

        for ax in axes:
            eps_ax = {e: i for e, i in eps.items() if i["axis"] == ax}
            n_all = len(eps_ax)
            usable = {
                e: i
                for e, i in eps_ax.items()
                if i["desirability"] is not None and i["verdict"] != "UNDETERMINED"
            }
            n_usable = len(usable)
            cov = n_usable / n_all if n_all else 0.0
            # v3.0：端点可在规则里声明 weight（Derringer-Suich 的指数权重）。
            # 未声明 = 1.0（等权，与旧行为完全一致）。
            wts = [_w_of(ep, rules) for ep in usable]
            gm = (
                _geo([i["desirability"] for i in usable.values()], wts)
                if n_usable
                else None
            )
            # F6（全流程覆盖测试）：覆盖不足时**不得**输出 geo_mean——此前 cov<阈值仍写 gm，
            # 只要 1 个端点 PASS 就显示 geo=1.0（"满分安全"），与"缺失不赋分 / 不能有致命短板"
            # 直接冲突。改为留空，flag 仍标 insufficient_coverage（信息不丢、结论不越界）。
            insufficient = gm is not None and cov < AXIS_COVERAGE_MIN
            axis_rows.append(
                dict(
                    compound_id=cid,
                    axis=ax,
                    n_endpoints=n_all,
                    n_audited=n_usable,
                    coverage=round(cov, 3),
                    geo_mean=("" if (gm is None or insufficient) else round(gm, 4)),
                    flag=(
                        "insufficient_coverage"
                        if insufficient
                        else ("ok" if gm is not None else "no_audited_endpoints")
                    ),
                    endpoints_audited=";".join(sorted(usable)),
                    endpoints_skipped=";".join(
                        sorted(e for e, i in eps_ax.items() if e not in usable)
                    ),
                )
            )

    return ep_rows, axis_rows


def pareto_front(axis_rows, axes):
    """轴级 Pareto 前沿（越大越好；缺失/覆盖率不足的轴视为"不知道"，不参与支配判断）。

    返回 (front_ids, details)。details[compound_id] = 被谁支配（空 = 前沿）。
    """
    by_cid = {}
    for r in axis_rows:
        if r["flag"] != "ok":
            continue
        gm = _f(r["geo_mean"])
        if gm is None:
            continue
        by_cid.setdefault(r["compound_id"], {})[r["axis"]] = gm

    ids = sorted(by_cid)
    dom = {i: [] for i in ids}
    front = []
    for a in ids:
        va = by_cid[a]
        for b in ids:
            if a == b:
                continue
            vb = by_cid[b]
            # 支配语义（保守）：支配者必须覆盖被支配者的**全部**轴。
            # 反例（本轮测试抓出）：R 只有 safety 0.95，Q 有 safety 0.8+exposure 0.9；
            # 只比共同轴的话 R 会"支配"Q，但 R 的 exposure 未知、可能很差。
            if not set(va).issubset(vb):
                continue
            if all(vb[ax] >= va[ax] for ax in va) and any(vb[ax] > va[ax] for ax in va):
                dom[a].append(b)
        if not dom[a]:
            front.append(a)
    return front, dom


def can_rank_full(
    n_compounds,
    max_cluster_frac,
    max_cross_source_spread,
    min_audited_endpoints_per_compound,
    n_audited=None,
):
    """排名守卫的完整版：can_rank 三条件 + desirability 覆盖率条件。

    返回 (ok, reasons)。四者必须同时满足。
    n_audited: **已废弃**（v2.1 起函数体不再使用），保留为可选形参仅为向后兼容。
    """
    from .reliability import can_rank

    ok0, reasons = can_rank(n_compounds, max_cluster_frac, max_cross_source_spread)
    if min_audited_endpoints_per_compound < 3:
        reasons.append(
            "可判端点数 %d < 3（至少要 3 个端点才有排名意义）"
            % min_audited_endpoints_per_compound
        )
    return (not reasons), reasons


def write_reports(outdir, ep_rows, axis_rows, front, dom):
    """落盘两张 CSV + 控制台摘要。返回 (ep_path, axis_path)。"""
    p1 = os.path.join(outdir, "desirability.csv")
    cols1 = [
        "compound_id",
        "endpoint",
        "axis",
        "value",
        "verdict",
        "desirability",
        "confidence",
    ]
    with io.open(p1, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols1, extrasaction="ignore")
        w.writeheader()
        w.writerows(ep_rows)

    p2 = os.path.join(outdir, "axis_scores.csv")
    cols2 = [
        "compound_id",
        "axis",
        "n_endpoints",
        "n_audited",
        "coverage",
        "geo_mean",
        "flag",
        "pareto",
        "dominated_by",
        "endpoints_audited",
        "endpoints_skipped",
    ]
    with io.open(p2, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols2, extrasaction="ignore")
        w.writeheader()
        for r in axis_rows:
            r = dict(r)
            cid = r["compound_id"]
            r["pareto"] = "front" if cid in front else "dominated"
            r["dominated_by"] = ";".join(sorted(dom.get(cid, [])))
            w.writerow(r)
    return p1, p2
