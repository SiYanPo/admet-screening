# -*- coding: utf-8 -*-
"""保形预测（split conformal）——给点估计配"有覆盖率保证"的区间。

文献：Norinder U, Carlsson L, Boyer S, Eklund M.
      Introducing Conformal Prediction in Predictive Modeling. A Transparent and
      Flexible Alternative to Applicability Domain Determination.
      J Chem Inf Model. 2014;54(6):1596-1603. DOI: 10.1021/ci5001168

为什么 ADMET 需要它
------------------
本 skill 之前给的是"点估计 + 三态（PASS/FAIL/UNDETERMINED）"。三态回答"能不能判"，
但不回答"这个数离阈值有多远、误差多大"。保形预测补的正是这一层：
在**有限样本**下给出

    P(|y − ŷ| ≤ q) ≥ 1 − α

的**边际覆盖率保证**（不需要正态性、不需要同方差假设）——比"按经验设一个 ±20%"硬得多。

三条纪律（避免把 CP 用成新的伪精度）
------------------------------------
1. **校准集必须是实测真值**，不能是另一模型的预测；用预测-预测做校准是自欺。
2. **覆盖率保证是边际的**（average over compounds），不是对每个分子都成立；
   分组/条件覆盖需要 Mondrian CP，本模块不提供。
3. **在校准集上算出的经验覆盖率天然 ≥1−α**（构造使然），
   **不能当作验证**；真覆盖率必须在不参与校准的独立集上检查。本模块会把这句话写进 note。

接口
----
  calibrate(cal_pairs, alpha) -> dict(q, n, alpha, k, empirical, note)
  predict_one(yhat, cal, scale=None) -> (lo, hi)
  build(pred_rows, truth_rows, endpoint, alpha, min_n) -> (rows, summary)
"""

import csv
import io
import math
import os
import warnings

try:
    from .reliability import _f, _median
except ImportError:  # 允许直接脚本运行
    from reliability import _f, _median  # type: ignore

PRED_FLAGS = {"predicted", "measured", "manual", "saturated"}


def _quantile_index(n, alpha):
    """split conformal 的秩：k = ceil((n+1)(1−α))（1-based）。"""
    return int(math.ceil((n + 1) * (1.0 - alpha)))


def calibrate(cal_pairs, alpha=0.2, mode="absolute"):
    """从校准集算分位数 q。

    cal_pairs: [(yhat, y_true)] 或 [(yhat, y_true, sigma)]；
      mode="absolute" 用 |y−ŷ|；
      mode="normalized" 用 |y−ŷ|/sigma（sigma 为逐化合物难度尺度）。
    返回 dict(q, n, alpha, k, empirical, degenerate, note, mode)。
    """
    scores = []
    for p in cal_pairs:
        if len(p) == 3:
            yh, y, s = p
        else:
            yh, y = p
            s = 1.0
        if y is None or yh is None:
            continue
        try:
            sd = float(s) if s not in (None, "") else 1.0
        except (TypeError, ValueError):
            sd = 1.0
        if sd <= 0 or not math.isfinite(sd):
            sd = 1.0
        resid = abs(float(y) - float(yh))
        scores.append((resid / sd) if mode == "normalized" else resid)
    scores = sorted(scores)
    n = len(scores)
    res = dict(
        q=float("inf"),
        n=n,
        alpha=alpha,
        k=0,
        empirical=None,
        degenerate=False,
        note="",
        mode=mode,
    )
    if n == 0:
        res["degenerate"] = True
        res["note"] = "校准集为空：无法给区间"
        return res
    k = _quantile_index(n, alpha)
    res["k"] = k
    if k > n:
        # 有限样本下秩超过 n：只能给无穷区间（这就是"样本太少"的诚实表达）
        res["degenerate"] = True
        res["note"] = (
            "n=%d 太小：k=ceil((n+1)(1−α))=%d > n，"
            "只能在 ±∞ 下保证 %d%% 覆盖——等于没有信息"
            % (n, k, round((1 - alpha) * 100))
        )
        res["empirical"] = 1.0
        return res
    res["q"] = scores[k - 1]
    res["empirical"] = sum(1 for s in scores if s <= res["q"]) / float(n)
    res["note"] = (
        "校准集经验覆盖率 %.3f 是**构造保证**，不是验证结果；"
        "真覆盖率需在不参与校准的独立集上检查" % res["empirical"]
    )
    return res


def predict_one(yhat, cal, scale=1.0):
    q = cal["q"] * (scale if scale else 1.0)
    if q == float("inf"):
        return (-float("inf"), float("inf"))
    return (yhat - q, yhat + q)


def build(
    pred_rows,
    truth_rows,
    endpoint,
    alpha=0.2,
    min_n=20,
    target_ids=None,
    mode="absolute",
    scale_map=None,
):
    """把长表拆成校准集/目标集，输出区间。

    pred_rows : measurements 长表（多源，取域内中位数作 ŷ）
    truth_rows: 实测真值（truth.csv 契约）；**只有实测化合物能进校准集**
    target_ids: 需要区间的分子；None = 全部有预测的分子
    mode      : "absolute"（默认，宽度=2q）或 "normalized"（宽度=2q·sigma）
    scale_map : {compound_id: sigma}，仅 normalized 模式使用；缺省 sigma=1

    诚实边界：若某分子既有实测又被用来校准，它自己的区间是"自我校准"的，
    会偏窄 → 本模块把这类分子单独标 `self_calibrated`，不参与覆盖率统计。
    """
    agg = {}
    for r in pred_rows:
        if r.get("endpoint") != endpoint:
            continue
        if r.get("domain_flag") not in PRED_FLAGS:
            continue
        v = _f(r.get("value"))
        if v is None:
            continue
        agg.setdefault(r.get("compound_id"), []).append(v)
    yhat = {c: _median(v) for c, v in agg.items()}

    truth = {}
    for t in truth_rows:
        if t.get("endpoint") != endpoint:
            continue
        v = _f(t.get("truth_value"))
        if v is None:
            continue
        truth[t.get("compound_id")] = v

    if mode == "normalized":
        cal_pairs = [
            (yhat[c], truth[c], (scale_map or {}).get(c, 1.0))
            for c in yhat
            if c in truth
        ]
    else:
        cal_pairs = [(yhat[c], truth[c]) for c in yhat if c in truth]
    cal = calibrate(cal_pairs, alpha, mode=mode)
    cal["flag"] = "insufficient" if cal["degenerate"] or cal["n"] < min_n else "ok"
    if cal["n"] < min_n and not cal["degenerate"]:
        cal["flag"] = "insufficient"
        cal["note"] = "校准集 n=%d < %d：区间宽度不可靠（q 由个别点决定）" % (
            cal["n"],
            min_n,
        )

    ids = target_ids or sorted(yhat)
    rows, n_self = [], 0
    for cid in ids:
        if cid not in yhat:
            rows.append(
                dict(
                    compound_id=cid,
                    endpoint=endpoint,
                    yhat="",
                    lo="",
                    hi="",
                    width="",
                    q=cal["q"],
                    alpha=alpha,
                    n_cal=cal["n"],
                    flag="no_prediction",
                    note="该端点无域内预测",
                )
            )
            continue
        scale = (scale_map or {}).get(cid, 1.0) if mode == "normalized" else 1.0
        lo, hi = predict_one(yhat[cid], cal, scale)
        self_cal = cid in truth
        n_self += int(self_cal)
        rows.append(
            dict(
                compound_id=cid,
                endpoint=endpoint,
                yhat=round(yhat[cid], 4),
                lo=round(lo, 4) if lo != -float("inf") else "",
                hi=round(hi, 4) if hi != float("inf") else "",
                width=round(hi - lo, 4) if hi != float("inf") else "",
                q=round(cal["q"], 4) if cal["q"] != float("inf") else "",
                alpha=alpha,
                n_cal=cal["n"],
                flag=("self_calibrated" if self_cal else cal["flag"]),
                note=(
                    "该分子在真值集里 → 区间由自身参与校准，偏窄，不可用于覆盖率统计"
                    if self_cal
                    else (("normalized: sigma=%.4f; " % scale) + cal["note"])
                ),
            )
        )
    summary = dict(
        endpoint=endpoint,
        n_cal=cal["n"],
        q=cal["q"],
        alpha=alpha,
        mode=mode,
        flag=cal["flag"],
        n_targets=len(rows),
        n_self_calibrated=n_self,
        empirical_cal=cal["empirical"],
        note=cal["note"],
    )
    return rows, summary


def write(path, rows):
    cols = [
        "compound_id",
        "endpoint",
        "yhat",
        "lo",
        "hi",
        "width",
        "q",
        "alpha",
        "n_cal",
        "flag",
        "note",
    ]
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with io.open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return len(rows)


# ============================================================================
# 类条件（Mondrian）保形预测 —— 方向1：与 2026 少数类失效文献正面对话
# ============================================================================
# 文献锚点（已核验）：Tursunbadalov & Tursunbadalov, arXiv:2607.06605v1 (2026),
#   "A Quiet Failure in Calibrated Virtual Screening: Marginal Conformal Prediction
#   Under-Covers the Minority Class, and a Class-Conditional Fix Recovers It".
#   边际保形在类不平衡下系统性低覆盖少数类：BBBP 少数类 64.8%、Tox21 SR-ARE 38.9%、
#   ClinTox 4.2%；Mondrian（类条件）将少数类恢复到目标 90.3%。
#
# 本框架的方法学立场（与核心命题一致）：我们的**准入驱动弃权**是结构性的——
#   不依赖 exchangeability / 边际覆盖假设（域外 block、票数不足即弃权），
#   因此天然规避边际保形在少数类上的失效。conformal 宽度作为**辅助**信号，
#   在少数类上必须做类别条件化。两类弃权信号是不同轴，不能互相替代。
#
# 非一致性分数（概率分类器）：s = 1 − p(y_true)；值越大越"该类的证据越弱"。
def _cc_score(yhat, ytrue):
    """yhat = P(class=1)；返回非一致性分数 1 − p(y_true)。"""
    p = float(yhat)
    p = min(max(p, 1e-9), 1 - 1e-9)
    pt = p if int(ytrue) == 1 else (1.0 - p)
    return 1.0 - pt


def _cc_quantile(scores, alpha):
    n = len(scores)
    if n == 0:
        return float("inf"), 0, n
    k = int(math.ceil((n + 1) * (1.0 - alpha)))
    if k > n:
        return float("inf"), k, n
    return sorted(scores)[k - 1], k, n


def class_conditional_coverage(pairs, alpha=0.1, mode="probability"):
    """对二分类概率预测做边际 vs 类条件（Mondrian）覆盖对比。

    pairs: [(yhat, ytrue)]，yhat=P(class=1)∈[0,1]，ytrue∈{0,1}。
    返回 dict：marginal_q / marginal_coverage / class_coverage{0,1} /
              mondrian_q0 / mondrian_q1 / mcq(marginal coverage gap) /
              cii(coverage imbalance index) / n0 / n1 / flag。

    注意：本函数只用**交换性**假设下的构造覆盖；真覆盖率须在不参与校准的独立集上检查。
    """
    p0 = [(yh, yt) for (yh, yt) in pairs if int(yt) == 0]
    p1 = [(yh, yt) for (yh, yt) in pairs if int(yt) == 1]
    s0 = sorted(_cc_score(yh, yt) for (yh, yt) in p0)
    s1 = sorted(_cc_score(yh, yt) for (yh, yt) in p1)
    mq, _mk, mn = _cc_quantile([_cc_score(yh, yt) for (yh, yt) in pairs], alpha)
    q0, _k0, n0 = _cc_quantile(s0, alpha)
    q1, _k1, n1 = _cc_quantile(s1, alpha)

    def cov(q, ps):
        if q == float("inf"):
            return 1.0
        return (
            sum(1 for (yh, yt) in ps if _cc_score(yh, yt) <= q) / float(len(ps))
            if ps
            else float("nan")
        )

    marginal_cov = cov(mq, pairs)
    cov0 = cov(q0, p0)
    cov1 = cov(q1, p1)
    # mcq（minority coverage gap）= (1−α) − cov_min；cii = cov_maj − cov_min
    cmin = min(cov0, cov1) if (p0 and p1) else float("nan")
    cmax = max(cov0, cov1) if (p0 and p1) else float("nan")
    mcq = (1.0 - alpha) - cmin if (p0 and p1) else float("nan")
    cii = cmax - cmin if (p0 and p1) else float("nan")
    enough = (n0 >= 20) and (n1 >= 20)
    flag = "ok" if enough else "insufficient (某类 n<20)"
    return dict(
        alpha=alpha,
        n0=n0,
        n1=n1,
        marginal_q=mq,
        mondrian_q0=q0,
        mondrian_q1=q1,
        marginal_coverage=marginal_cov,
        class_coverage_0=cov0,
        class_coverage_1=cov1,
        minority_coverage_gap=mcq,
        coverage_imbalance_index=cii,
        flag=flag,
        note=(
            "类条件（Mondrian）保形恢复少数类覆盖；真覆盖率须独立集验证"
            if enough
            else "某类校准样本<20，q 不可靠"
        ),
    )


def risk_coverage_curve(pairs, alpha=0.1, mode="probability"):
    """弃权-风险曲线（selective classification）：按置信度 max(p,1−p) 由高到低接纳，
    返回边际 vs 类条件两条曲线：每个阈值下的 (coverage, accuracy)。

    用于与 "A Quiet Failure" 对话：类条件化后少数类在同等覆盖率下精度更高。
    """

    def build(q):
        rows = []
        ps = sorted(pairs, key=lambda x: -max(float(x[0]), 1 - float(x[0])))
        for t in range(1, len(ps) + 1):
            subset = ps[:t]
            cov = t / float(len(ps))
            acc = sum(1 for (yh, yt) in subset if int((yh >= 0.5)) == int(yt)) / float(
                t
            )
            rows.append((round(cov, 4), round(acc, 4)))
        return rows

    return dict(
        marginal=build(float("inf")),  # 边际：无类条件，全接纳按置信度排
        mondrian=None,  # 类条件曲线需按类分别 q，单独构造
        note="marginal 曲线为参考；mondrian 曲线由 build_class_conditional_endpoint 生成",
    )


def class_conditional_risk_coverage(pairs, alpha=0.1):
    """类条件（Mondrian）弃权-风险曲线：按各自类的 q 决定弃权，返回累计 (coverage, accuracy)。

    与 marginal 曲线对照，可直接复现 "A Quiet Failure" 的结论：Mondrian 在同等覆盖率下
    少数类精度更高、且 minority coverage 不再塌陷。
    """
    p0 = [(yh, yt) for (yh, yt) in pairs if int(yt) == 0]
    p1 = [(yh, yt) for (yh, yt) in pairs if int(yt) == 1]
    _, _k0, _ = _cc_quantile(sorted(_cc_score(yh, yt) for (yh, yt) in p0), alpha)
    _, _k1, _ = _cc_quantile(sorted(_cc_score(yh, yt) for (yh, yt) in p1), alpha)
    q_info = class_conditional_coverage(pairs, alpha)
    q0 = q_info["mondrian_q0"]
    q1 = q_info["mondrian_q1"]

    def cov_curve(q_per_class):
        # 按类分别用本类 q 决定弃权；整体按置信度排序后累计
        accepted = []
        for yh, yt in pairs:
            qc = q0 if int(yt) == 0 else q1
            accepted.append((yh, yt)) if _cc_score(yh, yt) <= qc else None
        # 按置信度降序接纳（已过滤掉被类条件 q 弃权的）
        acc = [a for a in accepted]
        acc.sort(key=lambda x: -max(float(x[0]), 1 - float(x[0])))
        rows = []
        n = len(acc)
        for t in range(1, n + 1):
            sub = acc[:t]
            rows.append(
                (
                    round(t / float(len(pairs)), 4),
                    round(
                        sum(1 for (yh, yt) in sub if int((yh >= 0.5)) == int(yt))
                        / float(t),
                        4,
                    ),
                )
            )
        return rows

    return dict(
        marginal=risk_coverage_curve(pairs, alpha)["marginal"],
        mondrian=cov_curve(None) if pairs else [],
        note="mondrian 曲线：按类分别 q 弃权后再按置信度累计",
    )


def exchangeability_drift(bins, alpha=0.1):
    """交换性诊断（评审 L2-1）：按时间/结构分箱的 conformal 覆盖漂移。

    bins = [(label, coverage_achieved, n), ...]；名义覆盖 = 1 − alpha。
    对每个箱计算覆盖偏差 dev = cov − 名义覆盖，并据二项标准误判是否越界：
      |dev| > 2·SE，SE = sqrt(nominal·(1−nominal)/n) → 视为交换性漂移（拒绝该箱与
      训练集同分布）。

    配合 weighted_conformal（按时间/结构加权重标定）对照：若加权后各箱覆盖回到
    名义值，说明漂移可由已知协变量解释（可修正）；否则为不可建模漂移（需弃用/重训）。
    """
    import math

    nominal = 1.0 - alpha
    out = []
    for label, cov, n in bins:
        se = math.sqrt(nominal * (1 - nominal) / n) if n else 0.0
        dev = cov - nominal
        drift = (abs(dev) > 2 * se) if se > 0 else False
        out.append(
            dict(
                bin=label,
                coverage=round(cov, 4),
                n=n,
                nominal=round(nominal, 4),
                deviation=round(dev, 4),
                drift=drift,
            )
        )
    any_drift = any(b["drift"] for b in out)
    return dict(
        bins=out,
        nominal=round(nominal, 4),
        any_drift=any_drift,
        note=(
            "检测到交换性漂移（见 drift=True 的分箱），需 weighted conformal 重标定或重训"
            if any_drift
            else "各分箱覆盖与名义值一致，未检测到交换性漂移"
        ),
    )


def evaluate_disjoint(cal_pairs, test_pairs, alpha=0.1):
    """正确（方法学）的 CP：校准集与测试集**不相交**。

    cal_pairs  : [(yhat, ytrue)] 用于算类条件 q（不可出现在 test 中）
    test_pairs : [(yhat, ytrue)] 用于评估真实覆盖率
    返回 dict：marginal_coverage / class_coverage{0,1} / minority_coverage_gap /
              coverage_imbalance_index / mondrian_q0 / mondrian_q1 / flag。

    这是与 "A Quiet Failure" 对话的**正确入口**：边际保形在类不平衡+分布偏移下对少数类
    系统性低覆盖，Mondrian 将其恢复。self-calibrated 的 build_class_conditional_endpoint
    只在有独立测试集时才能暴露该失效。
    """
    s0 = sorted(_cc_score(yh, yt) for (yh, yt) in cal_pairs if int(yt) == 0)
    s1 = sorted(_cc_score(yh, yt) for (yh, yt) in cal_pairs if int(yt) == 1)
    alls = sorted(_cc_score(yh, yt) for (yh, yt) in cal_pairs)
    mq, _mk, _mn = _cc_quantile(alls, alpha)
    q0, _k0, n0 = _cc_quantile(s0, alpha)
    q1, _k1, n1 = _cc_quantile(s1, alpha)

    def cov(q, ps):
        if q == float("inf"):
            return 1.0
        return (
            sum(1 for (yh, yt) in ps if _cc_score(yh, yt) <= q) / float(len(ps))
            if ps
            else float("nan")
        )

    marginal_cov = cov(mq, test_pairs)
    cov0 = cov(q0, [p for p in test_pairs if int(p[1]) == 0])
    cov1 = cov(q1, [p for p in test_pairs if int(p[1]) == 1])
    cmin = min(cov0, cov1) if (cov0 == cov0 and cov1 == cov1) else float("nan")
    cmax = max(cov0, cov1) if (cov0 == cov0 and cov1 == cov1) else float("nan")
    return dict(
        alpha=alpha,
        n0_cal=n0,
        n1_cal=n1,
        n_test=len(test_pairs),
        marginal_q=mq,
        mondrian_q0=q0,
        mondrian_q1=q1,
        marginal_coverage=marginal_cov,
        class_coverage_0=cov0,
        class_coverage_1=cov1,
        minority_coverage_gap=(1.0 - alpha) - cmin if (cmin == cmin) else float("nan"),
        coverage_imbalance_index=(
            cmax - cmin if (cmax == cmax and cmin == cmin) else float("nan")
        ),
        flag=("ok" if (n0 >= 10 and n1 >= 10) else "insufficient calibration"),
    )


def _endpoint_pairs(pred_rows, truth_rows, endpoint):
    """构建 (compound_id, yhat, ytrue) 三元组；同一化合物只出现一次。"""
    agg = {}
    for r in pred_rows:
        if r.get("endpoint") != endpoint:
            continue
        if r.get("domain_flag") not in PRED_FLAGS:
            continue
        v = _f(r.get("value"))
        if v is None:
            continue
        agg.setdefault(r.get("compound_id"), []).append(v)
    yhat = {c: _median(v) for c, v in agg.items()}
    truth = {}
    for t in truth_rows:
        if t.get("endpoint") != endpoint:
            continue
        v = _f(t.get("truth_value"))
        if v is None:
            continue
        truth[t.get("compound_id")] = int(round(v))
    return [(c, yhat[c], truth[c]) for c in sorted(yhat) if c in truth]


def build_class_conditional_endpoint(
    pred_rows, truth_rows, endpoint, alpha=0.1, min_n=20
):
    """【DEMO / 自校准】从同一批 pairs 同时算 q 与覆盖率。

    2026-11-04 / C07：**恒标** self_calibrated=True，不再因样本大而覆盖为 ok。
    旧行为 `len(pairs) >= 2*min_n -> cov["flag"]` 恰在最可能被引用时抹掉警告。
    该函数的覆盖率**不构成独立验证**；生产请用 build_class_conditional_disjoint。

    同行评审 §3 疑点 7（2026-11-22）：本入口恒为自校准 demo，仍被旧材料引用为
    Mondrian 入口。自本版起发 DeprecationWarning；下一 major 删除，届时统一走
    build_class_conditional_disjoint。
    """
    warnings.warn(
        "build_class_conditional_endpoint is a self-calibrated DEMO and will be "
        "removed in the next major version; use build_class_conditional_disjoint "
        "for an independent coverage claim.",
        DeprecationWarning,
        stacklevel=2,
    )
    triples = _endpoint_pairs(pred_rows, truth_rows, endpoint)
    pairs = [(yh, yt) for _c, yh, yt in triples]
    cov = class_conditional_coverage(pairs, alpha)
    curve = class_conditional_risk_coverage(pairs, alpha)
    summary = dict(endpoint=endpoint, n_pairs=len(pairs), **cov)
    summary.update(
        flag="self_calibrated_demo",
        disjoint=False,
        self_calibrated=True,
        calibration_n=len(pairs),
        eval_n=len(pairs),
        compound_id_overlap=len(pairs),
        evidence_grade="non_evidence_for_coverage_claim",
        note=(
            "同一批 pairs 既算 q 又算 coverage；覆盖率是构造保证，"
            "不是独立验证（C07）。真实覆盖率须由 "
            "build_class_conditional_disjoint 在不相交测试集上报告。"
        ),
    )
    return pairs, summary, curve


def build_class_conditional_disjoint(
    pred_rows, truth_rows, endpoint, alpha=0.1, min_n=20, cal_fraction=0.5
):
    """【生产入口 / C07】校准集与评测集按 compound_id 不相交划分。

    划分用 sha256(compound_id) 的确定性哈希，不引入随机种子（避免与 SEED_POLICY
    的种子去耦合要求冲突），且保证同一化合物不会同时出现在两集。
    返回 (cal_pairs, test_pairs, summary, curve)；坏输入直接抛 ValueError，
    由 CLI 捕获并 exit 4（禁止「校准集=评测集」静默放行）。
    """
    import hashlib

    triples = _endpoint_pairs(pred_rows, truth_rows, endpoint)
    if not triples:
        raise ValueError("端点 %s 无 (预测∩实测) 化合物，无法做不相交划分" % endpoint)
    cutoff = int(256 * float(cal_fraction))

    def _bucket(cid):
        return int(hashlib.sha256(str(cid).encode("utf-8")).hexdigest()[:2], 16)

    cal = [(yh, yt) for c, yh, yt in triples if _bucket(c) < cutoff]
    test = [(yh, yt) for c, yh, yt in triples if _bucket(c) >= cutoff]
    cal_ids = {c for c, _yh, _yt in triples if _bucket(c) < cutoff}
    test_ids = {c for c, _yh, _yt in triples if _bucket(c) >= cutoff}
    overlap = cal_ids & test_ids
    if overlap:
        raise ValueError("校准/评测集 compound_id 交集非空：%s" % sorted(overlap)[:5])
    if not cal or not test:
        raise ValueError(
            "不相交划分后校准集=%d / 评测集=%d，不足以评估覆盖率"
            % (len(cal), len(test))
        )
    if min(len(cal), len(test)) < min_n:
        raise ValueError(
            "校准集=%d / 评测集=%d，小于 min_n=%d：覆盖率估计不可用"
            % (len(cal), len(test), min_n)
        )
    res = evaluate_disjoint(cal, test, alpha)  # 返回值自身已含 alpha 键
    summary = dict(endpoint=endpoint)
    summary.update(res)
    summary.update(
        n_pairs=len(test),
        n0=res["n0_cal"],
        n1=res["n1_cal"],
        calibration_n=len(cal),
        eval_n=len(test),
        disjoint=True,
        self_calibrated=False,
        compound_id_overlap=0,
        split_method="sha256(compound_id) deterministic hash",
        cal_fraction=float(cal_fraction),
        evidence_grade="independent_holdout",
    )
    curve = class_conditional_risk_coverage(test, alpha)
    return cal, test, summary, curve


# ---------------------------------------------------------------------------
# 同行评审 §3 疑点 3：conformal coverage 在 cluster 偏移下的分层门禁（B14）
# ---------------------------------------------------------------------------
def coverage_by_tanimoto_bins(
    pairs, *, alpha=0.1, n_bins=4, min_far_fraction=0.5, nominal=None
):
    """按 Tanimoto 相似度分位分层检查经验覆盖率，最远层跌破标称一半即拒绝声明。

    pairs: [(tanimoto, covered)]，tanimoto=该分子到参考/训练集的最大相似度，
           covered=该分子是否落入 conformal 预测区间（True/False）。
    标称覆盖率 nominal 默认 1-alpha。

    报告 §3 疑点 3 的判据原文："按 Tanimoto 分位分层；最远层跌破标称一半即拒绝声明"。
    返回 ok=False 时，任何"覆盖率达标"的结论都必须撤回（只能报分桶实测值）。
    """
    rows = [(float(t), bool(c)) for t, c in pairs if t is not None]
    if not rows:
        return dict(
            ok=False, reasons=["无有效 pair"], bins=[], note="无数据，不得声明覆盖率"
        )
    nominal = (1.0 - alpha) if nominal is None else float(nominal)
    rows.sort(key=lambda x: x[0])  # 相似度升序：最远层在前
    n = len(rows)
    edges = []
    for k in range(1, n_bins):
        idx = int(n * k / n_bins)
        idx = max(1, min(n - 1, idx))
        edges.append(rows[idx][0])
    bounds = [None] + edges + [None]

    bins = []
    for bi in range(n_bins):
        lo, hi = bounds[bi], bounds[bi + 1]
        seg = [c for t, c in rows if (lo is None or t >= lo) and (hi is None or t < hi)]
        # 边界处理：最后一桶用 >= lo（含等号），前面用 [lo, hi)
        if bi == n_bins - 1:
            seg = [c for t, c in rows if lo is None or t >= lo]
        cov = (sum(seg) / len(seg)) if seg else None
        bins.append(
            dict(
                bin=bi,
                n=len(seg),
                sim_lo=lo,
                sim_hi=hi,
                empirical_coverage=(round(cov, 4) if cov is not None else None),
            )
        )

    reasons = []
    far = bins[0]  # 相似度最低 = 分布最远
    far_cov = far["empirical_coverage"]
    threshold = nominal * min_far_fraction
    if far["n"] == 0 or far_cov is None:
        reasons.append("最远分桶无样本，无法验证偏移下的覆盖率")
    elif far_cov < threshold:
        reasons.append(
            "最远分桶经验覆盖率 %.3f < 标称 %.3f 的 %.0f%% (=%.3f)："
            "禁止声明 coverage 达标"
            % (far_cov, nominal, min_far_fraction * 100, threshold)
        )
    # 单调性：覆盖率不应随相似度降低而升高（远端不该比近端更"覆盖"得更好）
    covs = [
        b["empirical_coverage"] for b in bins if b["empirical_coverage"] is not None
    ]
    if len(covs) >= 2 and covs[0] > covs[-1] + 0.10:
        reasons.append(
            "最远分桶覆盖率 %.3f 反而高于最近分桶 %.3f（方向可疑）"
            % (covs[0], covs[-1])
        )
    return dict(
        ok=not reasons,
        reasons=reasons,
        bins=bins,
        nominal=round(nominal, 4),
        far_bin_threshold=round(threshold, 4),
        note=(
            "按 Tanimoto 分位分层；远端达标才可声明 coverage；"
            "不达标时只报分桶实测，禁止声称整体覆盖"
        ),
    )
