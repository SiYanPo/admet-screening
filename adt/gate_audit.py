# -*- coding: utf-8 -*-
"""Gate 审计（R19 / A8 + R20 / R2-1）：验证"适用域门"本身准不准。

评审 C8 原话："材料将 58% 的 PASSTHRU 叙述为'域外诚实'的胜利……竞争性解释是
适用域（AD）模型本身可能过于粗糙，把大量实际可预测的分子错误判出域外。要区分
这两种解释，必须验证 gate 本身的灵敏度和特异度。"

本模块只做一件事：把 gate 当成一个"预测可预测性"的分类器来审计——
  · 误放率 mispass  = gate 放过（判域内）但模型预测错的比例
  · 误杀率 miskill  = gate 杀掉（判域外）但模型其实能预测对的比例
并扫阈值给出 coverage × risk 权衡曲线，使用户**自选工作点**（R2-1）。
"""

import numpy as np


def _wilson(k, n, alpha=0.05):
    if n == 0:
        return (0.0, 1.0)
    try:
        from scipy.stats import norm

        z = norm.ppf(1 - alpha / 2.0)
    except Exception:
        z = 1.96
    p = k / float(n)
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / den
    return (max(0.0, c - h), min(1.0, c + h))


def sweep(sims, y_true, y_pred, thresholds=None):
    """按相似度阈值扫描 gate 的通过/拒绝效果。

    sims   : 每个 query 分子到参考集的最大 Tanimoto
    y_true : 真标签（0/1）
    y_pred : 模型二值预测
    """
    sims = np.asarray(sims, float)
    y_true = np.asarray(y_true, int)
    y_pred = np.asarray(y_pred, int)
    correct = (y_true == y_pred).astype(int)
    if thresholds is None:
        thresholds = [0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5, 0.55, 0.6, 0.65, 0.7]
    rows = []
    for thr in thresholds:
        passed = sims >= thr
        killed = ~passed
        n_pass, n_kill = int(passed.sum()), int(killed.sum())
        err_pass = int((1 - correct[passed]).sum()) if n_pass else 0
        right_kill = int(correct[killed].sum()) if n_kill else 0
        lo_mp, hi_mp = _wilson(err_pass, n_pass)
        lo_mk, hi_mk = _wilson(right_kill, n_kill)
        rows.append(
            {
                "threshold": thr,
                "coverage": round(float(passed.mean()), 3),
                "n_pass": n_pass,
                "n_kill": n_kill,
                "risk_decided": (
                    round(err_pass / float(n_pass), 3) if n_pass else None
                ),
                "mispass_rate": (
                    round(err_pass / float(n_pass), 3) if n_pass else None
                ),
                "mispass_ci95": [round(lo_mp, 3), round(hi_mp, 3)],
                "miskill_rate": (
                    round(right_kill / float(n_kill), 3) if n_kill else None
                ),
                "miskill_ci95": [round(lo_mk, 3), round(hi_mk, 3)],
                "gate_accuracy": round(
                    float(
                        (correct[passed].sum() + (1 - correct[killed]).sum())
                        / len(sims)
                    ),
                    3,
                ),
            }
        )
    return rows


def roc_pr(sims, y_true, y_pred):
    """gate 作为"可预测性分类器"的 ROC/PR（正类=模型预测正确）。"""
    sims = np.asarray(sims, float)
    label = (np.asarray(y_true, int) == np.asarray(y_pred, int)).astype(int)
    order = np.argsort(-sims)
    lab = label[order]
    tp = np.cumsum(lab)
    fp = np.cumsum(1 - lab)
    P = int(lab.sum())
    N = len(lab) - P
    tpr = tp / max(P, 1)
    fpr = fp / max(N, 1)
    prec = tp / np.maximum(tp + fp, 1)
    rec = tpr
    # AUC（梯形，按 fpr 排序）
    idx = np.argsort(fpr)
    # numpy 2.x 移除了 np.trapz（实测 2.5.4 报 AttributeError）→ 用 trapezoid
    _trap = getattr(np, "trapezoid", None) or getattr(np, "trapz")
    auc = float(_trap(tpr[idx], fpr[idx])) if len(fpr) > 1 else 0.5
    # AP（11 点插值近似）
    ap = float(
        np.mean(
            [
                prec[rec >= t].max() if np.any(rec >= t) else 0.0
                for t in np.linspace(0, 1, 11)
            ]
        )
    )
    return {
        "auc_gate_as_predictability": round(auc, 3),
        "ap_gate_as_predictability": round(ap, 3),
        "base_correct_rate": round(float(label.mean()), 3),
        "n": int(len(label)),
    }


GATE_AUC_FLOOR = 0.65
"""门要被称为"有判别力"，其作为可预测性分类器的 AUC 至少 0.65。
依据：0.5 = 随机；0.65 是弱但有意义的判别力下限。该阈值是**约定**，不是定理，
故本模块同时输出原始 AUC，使用者可自行改判（评审 R2-1 要求"用户自选工作点"）。"""


def forced_prediction_test(y_true, y_pred, out_mask, alpha=0.05):
    """把被 gate 判为域外的分子"强行预测"，其准确率是否真的更差。

    这是"PASSTHRU 是否有据"的第二条独立证据（第一条是 AUC）。
    用 Fisher 精确检验比较域内/域外准确率，而不是比较两个点估计。
    """
    y_true = np.asarray(y_true, int)
    y_pred = np.asarray(y_pred, int)
    out = np.asarray(out_mask, bool)
    correct = (y_true == y_pred).astype(int)
    n_out, n_in = int(out.sum()), int((~out).sum())
    k_out = int(correct[out].sum()) if n_out else 0
    k_in = int(correct[~out].sum()) if n_in else 0
    acc_out = (k_out / float(n_out)) if n_out else None
    acc_in = (k_in / float(n_in)) if n_in else None
    p = None
    if n_out and n_in:
        try:
            from scipy.stats import fisher_exact

            _, p = fisher_exact([[k_out, n_out - k_out], [k_in, n_in - k_in]])
            p = float(p)
        except Exception:
            p = None
    # 差值区间（P2.4-b，2026-11-03 补）：Fisher p 只回答"有没有证据说不同"，
    # 不回答"能不能排除有临床意义的差异"。n_out=46 / n_in=86 这种量级下，
    # p=1.00 的真实含义是**功效不足**，不是"证明了没差异"。
    # 不给区间就写"无显著差异"，等于把"没查出来"说成"不存在"。
    diff_ci = None
    if n_out and n_in:
        try:
            from adt.stats_ci import newcombe_diff_ci

            _d = newcombe_diff_ci(k_out, n_out, k_in, n_in)
            # 四舍五入到 4 位：第 5 位以后是重抽噪声，写出来是伪造精度，
            # 也让 G10 的字面量 token 核验在换 seed 后必失效。
            diff_ci = {
                "diff": round(_d["diff"], 4),
                "lo": round(_d["lo"], 4),
                "hi": round(_d["hi"], 4),
                "method": _d.get("method"),
            }
        except Exception:
            diff_ci = None
    if n_out == 0 or n_in == 0 or p is None:
        verdict, interp = "inconclusive", "样本不足或统计库缺失，不下结论。"
    elif p < alpha and acc_out < acc_in:
        verdict = "passthru_justified"
        interp = (
            "域外分子强行预测准确率显著更低（%.3f vs %.3f，Fisher p=%.4f）"
            "→ PASSTHRU 有据。" % (acc_out, acc_in, p)
        )
    elif p < alpha and acc_out > acc_in:
        verdict = "passthru_harmful"
        interp = (
            "域外分子强行预测准确率反而更高（%.3f vs %.3f，Fisher p=%.4f）"
            "→ gate 在丢掉更准的分子，PASSTHRU 有害。" % (acc_out, acc_in, p)
        )
    else:
        verdict = "passthru_unfounded"
        if diff_ci is None:
            interp = (
                "域内/域外准确率无显著差异（%.3f vs %.3f，Fisher p=%.4f）"
                "→ 无法支持'域外不可预测'，PASSTHRU 缺乏依据。" % (acc_out, acc_in, p)
            )
        else:
            interp = (
                "域内/域外准确率之差 %.3f（95%%CI [%.3f, %.3f]，Newcombe；"
                "n_out=%d / n_in=%d），Fisher p=%.4f。区间**跨 0 且很宽**，"
                "说明该比较**功效不足**：既不能证明域外更差，也不能证明无差异。"
                "PASSTHRU 缺乏依据是**逻辑推断**（没有证据支持'域外不可预测'），"
                "不是'已证明域外与域内一样准'。"
                % (acc_out - acc_in, diff_ci["lo"], diff_ci["hi"], n_out, n_in, p)
            )
    return {
        "acc_out_of_domain": (round(acc_out, 3) if acc_out is not None else None),
        "acc_in_domain": (round(acc_in, 3) if acc_in is not None else None),
        "n_out": n_out,
        "n_in": n_in,
        "fisher_p": (round(p, 4) if p is not None else None),
        "diff_ci": diff_ci,
        "verdict": verdict,
        "interpretation": interp,
    }


def discriminative_power(sims, y_true, y_pred, auc_floor=GATE_AUC_FLOOR, auc_ci=None):
    """门到底能不能区分"可预测"与"不可预测"的分子（R20 的核心指标）。

    这是对 C8 竞争性解释的**直接裁决**：
      · AUC 高 → PASSTHRU 可解释为"域外诚实"；
      · AUC ≈ 0.5 → 门没有信息量，PASSTHRU 只是随机丢弃，
        此时**禁止**把弃权叙述为谨慎（评审 F5）。

    2026-11-03 更正（P2.4-b）：此前只比"点估计 vs 0.65"，于是 hERG 的 0.580 被直接
    写成"与随机丢弃在统计上不可区分"。**这句话是过头的**——0.580 的 95% CI 是
    [0.456, 0.701]，上界 0.701 **越过** 0.65 工作点，即"判别力弱"这件事本身也没有
    被数据证实，样本只有 132 条（109 对 / 23 错）。
    正确的表述只有一句：**未证明有判别力**。不能说"已证明无判别力"。
    故引入 `auc_ci`，把结论降进四种状态，杜绝在负方向上过度声称。
    """
    r = roc_pr(sims, y_true, y_pred)
    auc = r["auc_gate_as_predictability"]
    base = r["base_correct_rate"]
    informative = auc >= auc_floor

    lo = hi = None
    if isinstance(auc_ci, dict) and auc_ci.get("lo") is not None:
        lo, hi = float(auc_ci["lo"]), float(auc_ci["hi"])

    if lo is None:
        # 无 CI：只能给点估计状态，且必须显式标注"未提供 95% CI"
        state = "no_ci"
        interp = (
            "门对'模型是否会做对'的点估计 AUC 为 %.3f（%s %.2f），"
            "**未提供 95%% CI，不得据此下'有/无判别力'的结论**。"
        ) % (auc, "≥" if informative else "<", auc_floor)
    elif informative and lo >= auc_floor:
        state = "informative_supported"
        interp = (
            "门对'模型是否会做对'有判别力，且经 CI 支持：AUC %.3f，"
            "95%%CI [%.3f, %.3f] 下界越过工作点 %.2f。" % (auc, lo, hi, auc_floor)
        )
    elif informative:
        state = "informative_unconfirmed"
        interp = (
            "门 AUC 点估计 %.3f 高于工作点 %.2f，但 95%%CI [%.3f, %.3f] 下界越过了它，"
            "**判别力未被证实**，只能写'点估计高于工作点'。" % (auc, auc_floor, lo, hi)
        )
    elif hi < auc_floor:
        state = "uninformative_supported"
        interp = (
            "门无判别力，且经 CI 支持：AUC %.3f，95%%CI [%.3f, %.3f] 上界仍低于 %.2f。"
            "**禁止**把 PASSTHRU 叙述为'域外诚实'。" % (auc, lo, hi, auc_floor)
        )
    else:
        state = "uninformative_unconfirmed"
        interp = (
            "门 AUC 点估计 %.3f 低于工作点 %.2f，但 95%%CI [%.3f, %.3f] 上界**越过**了它"
            "（n=%d，正确 %d / 错误 %d）→ 只能说**未证明有判别力**；"
            "**不得**写成'已证明与随机丢弃不可区分'。PASSTHRU 的可解释性维持 UNRESOLVED。"
            % (
                auc,
                auc_floor,
                lo,
                hi,
                r["n"],
                int(round(base * r["n"])),
                int(round((1 - base) * r["n"])),
            )
        )
    return {
        "auc": auc,
        "ap": r["ap_gate_as_predictability"],
        "base_correct_rate": base,
        "auc_floor": auc_floor,
        "auc_ci": (
            None
            if lo is None
            else dict(lo=lo, hi=hi, method=(auc_ci or {}).get("method"))
        ),
        "n": r["n"],
        # verdict 保持"点估计口径"以兼容既有调用方；CI 口径单列 verdict_ci，
        # 二者冲突时**以 verdict_ci 为准**（点估计不构成结论）。
        "verdict": "informative" if informative else "uninformative",
        "verdict_ci": state,
        "informative": bool(informative),
        "interpretation": interp,
    }


def actionability_summary(rows, ref_threshold=0.35, power=None):
    """首页摘要：可执行率 + 弃权构成 + 与基线对比（R19 要求进首页）。

    power : 可选，``discriminative_power()`` 的返回值。给了就一并报告，
            使"可执行率"永远与"门是否有效"绑定出现，杜绝只报覆盖率。
    """
    chosen = None
    for r in rows:
        if abs(r["threshold"] - ref_threshold) < 1e-9:
            chosen = r
    if chosen is None:
        chosen = min(rows, key=lambda r: abs(r["threshold"] - ref_threshold))
    best = max(rows, key=lambda r: (r["coverage"] or 0) - 3 * (r["risk_decided"] or 0))
    out = {
        "at_threshold": chosen["threshold"],
        "actionable_rate": chosen["coverage"],
        "actionable_risk": chosen["risk_decided"],
        "abstain_composition": {"out_of_domain": round(1 - chosen["coverage"], 3)},
        "mispass": {"rate": chosen["mispass_rate"], "ci95": chosen["mispass_ci95"]},
        "miskill": {"rate": chosen["miskill_rate"], "ci95": chosen["miskill_ci95"]},
        "max_coverage": max(r["coverage"] for r in rows),
        "utility_optimal_threshold": best["threshold"],
        "note": "可执行率与误差必须并列报告；单一覆盖率不是优点也不是缺点",
    }
    if power is not None:
        out["gate_power"] = power
        out["gate_verdict"] = power["verdict"]
        out["gate_verdict_ci"] = power.get("verdict_ci", "no_ci")
        out["passthru_interpretation"] = power["interpretation"]
    else:
        out["gate_power"] = None
        out["gate_verdict"] = "not_measured"
        out["passthru_interpretation"] = (
            "未做门判别力测量。**在此状态下不得**把 PASSTHRU 表述为域外诚实，"
            "只能表述为'未加权重的弃权'。"
        )
    return out
