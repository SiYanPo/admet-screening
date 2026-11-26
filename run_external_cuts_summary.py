# -*- coding: utf-8 -*-
"""把三次外源切分的分层结果汇总成一张可引用的表（v2 / 2026-11-04 C01 撤回）。

## 撤回记录（C01，见 references/RETRACTION_NOTE.md）

v1 的第 78-80 行用
``bool(ov["auc"] < ov["always_positive_accuracy"])`` 生成 ``below_trivial_baseline``，
把 **AUC（排序能力，随机基线 0.5）** 与 **always-positive accuracy
（分类准确率，恒等于 prevalence）** 直接比大小 —— 跨量纲比较，结论无效。
该字段曾是 TAIL_RISK_THESIS §2/§3、PAPER_SKELETON_v4.4.md 可证伪预测 #2、
Fig 6 以及「门全拒是保守的正确」的唯一量化支点，现予撤回。

## v2 的正确双轨口径（两条轨道不得再合并成一个 bool）

轨道 1 · AUC <-> 0.5（排序能力）：
    引用上游已落盘的 ``r1_interval_requests.auc_ci95``；下界 > 0.5 才提示
    「弱但非零排序能力」。单侧 p 由 CI 宽度反推 SE 的正态近似给出，
    显式标 method=ci_inversion_normal_approx。本汇总层没有逐分子分数，
    **不伪称新做了 bootstrap**。

轨道 2 · accuracy <-> prevalence（分类准确率）：
    ``always_positive_accuracy`` 恒等于 ``prevalence``。上游
    ``r1_interval_requests.accuracy_at_0.5_minus_always_positive`` 已含
    **逐分子差的配对 bootstrap 95%CI**，直接引用、不重算。McNemar 需要逐样本
    2x2 列联表，汇总产物不含，故如实标 ``mcnemar_computable=false``，不伪造。

## 领域级限制（外审 B，2026-11-04；见 §3.4 领域级修正）

不得把结论翻转为「域外仍有弱排序能力」：hERG 端点 estimand 未绑定实验金标准
（真值应为膜片钳 IC50 的电压协议／温度／血清／尾峰电流，而非 probability
0.5 切点），在本 estimand 未定义前 AUC 不承载决策含义。正确处置是
**撤销该结论的推断资格**：``inference_status = inference_revoked_pending_estimand``。
待 references/ENDPOINT_ESTIMAND_CARDS.yaml 与 Q4 求证完成后方可重估。

## v4.4 标签更正（保留，与 C01 无关）

原被称作 "post-cutoff 外源留出" 的 n=9443 其实不是 post-cutoff：时间条件交给
ChEMBL 服务端（document__year__gte），该端点实测不执行过滤（>=2021/2022/2023
返回同一 total_count=19130）。修正后本地重切分为 mixed / y2021 / y2023 三套。

用法：
    python run_external_cuts_summary.py
"""
from __future__ import annotations

import io
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out_ext/external/external_cuts_summary_v2.json")
LEGACY = os.path.join(HERE, "out_ext/external/external_cuts_summary.json")
LEGACY_REL = "out_ext/external/external_cuts_summary.json"

SOURCES = [
    ("mixed", "不过滤（year_mode=none，仅解释旧数字）",
     "out_ext/external/_legacy_stratified.json"),
    ("y2021", "document_year >= 2021（真时间留出，切点 1）",
     "out_ext/external/herg_holdout_y2021_stratified.json"),
    ("y2023", "document_year >= 2023（真时间留出，切点 2）",
     "out_ext/external/herg_holdout_stratified.json"),
]

REMOVED_EXPRESSION = "bool(ov['auc'] < ov['always_positive_accuracy'])"


def _load(rel):
    p = os.path.join(HERE, rel)
    if not os.path.exists(p):
        return None
    return json.load(io.open(p, encoding="utf-8"))


def _auc_vs_chance(auc, ci95):
    """AUC 对照 0.5。SE 由已落盘 95%CI 宽度反推；z 动态求，不硬编码。"""
    out = {
        "reference": 0.5,
        "same_dimension": True,
        "method": "ci_inversion_normal_approx",
        "note": ("单侧 p 由上游已落盘 95%CI 反推 SE 的正态近似；"
                 "汇总层无逐分子分数，未新做 bootstrap。"),
        "auc_ci95": ci95,
        "ci95_lower_above_chance": None,
        "one_sided_p": None,
        "se_from_ci": None,
    }
    if auc is None or not ci95 or len(ci95) != 2:
        return out
    lo, hi = float(ci95[0]), float(ci95[1])
    out["ci95_lower_above_chance"] = bool(lo > 0.5)
    if hi <= lo:
        return out
    try:
        from scipy.stats import norm
        z = float(norm.ppf(0.975))
        p_one = float(norm.sf((auc - 0.5) / ((hi - lo) / (2 * z))))
    except Exception:
        z = 1.959963984540054
        se = (hi - lo) / (2 * z)
        p_one = 0.5 * math.erfc(((auc - 0.5) / se) / math.sqrt(2))
        out["method"] = "ci_inversion_normal_approx_math_fallback"
    se = (hi - lo) / (2 * z)
    out["se_from_ci"] = round(se, 8)
    out["one_sided_p"] = round(p_one, 8)
    return out


def _paired_bootstrap(d):
    """直接引用上游逐分子差的配对 bootstrap；不伪造 McNemar 2x2 表。"""
    r = ((d.get("r1_interval_requests") or {})
         .get("accuracy_at_0.5_minus_always_positive") or {})
    ci = r.get("boot_ci95")
    return {
        "method": "paired_bootstrap_per_molecule_from_upstream",
        "source_field": "r1_interval_requests.accuracy_at_0.5_minus_always_positive",
        "boot_ci95": ci,
        "upstream_note": r.get("note"),
        "significant_at_05": (
            None if (not ci or len(ci) != 2) else bool(ci[0] > 0 or ci[1] < 0)),
        "mcnemar_computable": False,
        "mcnemar_reason": ("汇总产物不含逐样本 2x2 列联表；配对 bootstrap 已由上游"
                           "逐分子差给出，承担配对检验，不伪造 McNemar。"),
    }


def main():
    cuts, missing = [], []
    for key, desc, rel in SOURCES:
        d = _load(rel)
        if d is None:
            missing.append(rel)
            continue
        ov = d.get("overall", {})
        trend = d.get("trend", {})
        ml = d.get("molecule_level_trend", {})
        q = d.get("by_tanimoto_quantile") or []
        ci95 = ((d.get("r1_interval_requests") or {}).get("auc_ci95")
                or ov.get("auc_ci95"))
        auc = ov.get("auc")
        acc = ov.get("accuracy_at_0.5")
        prev = ov.get("prevalence")
        cuts.append({
            "cut": key,
            "time_condition": desc,
            "artifact": rel,
            "year_mode": d.get("provenance", {}).get("year_mode"),
            "year_filter": d.get("provenance", {}).get("year_filter", {}),
            "n": ov.get("n"),
            "prevalence": prev,
            "auc": auc,
            "auc_vs_chance": _auc_vs_chance(auc, ci95),
            "always_positive_accuracy": ov.get("always_positive_accuracy"),
            "accuracy_at_0.5": acc,
            "accuracy_vs_prevalence": {
                "accuracy": acc,
                "baseline": prev,
                "baseline_name": "always_positive_accuracy == prevalence",
                "same_dimension": True,
                "delta": (None if (acc is None or prev is None) else round(acc - prev, 6)),
                "paired_bootstrap": _paired_bootstrap(d),
            },
            "accuracy_below_majority_class": (
                None if (acc is None or prev is None) else bool(acc < prev)),
            "median_tanimoto": ov.get("median_tanimoto"),
            "bucket_aucs": [b.get("auc") for b in q],
            "trend_bins_rho": trend.get("spearman_rho"),
            "trend_bins_p": trend.get("p_value"),
            "trend_bins_monotone": trend.get("monotone_increasing"),
            "molecule_level_rho_correct": ml.get("spearman_tanimoto_vs_correct"),
            "molecule_level_p": ml.get("p_value_correct"),
            "max_bucket_auc": max([b.get("auc") for b in q if b.get("auc") is not None],
                                  default=None),
            "verdict": (d.get("verdict") or {}).get("code"),
        })

    robust = {
        "cross_dimensional_comparison": {
            "valid": False,
            "removed_expression": REMOVED_EXPRESSION,
            "reason": ("AUC 的随机基线是 0.5；always_positive_accuracy 是分类准确率"
                       "且恒等于 prevalence。二者量纲不同，比较无意义。"),
        },
        "accuracy_below_majority_class_all_cuts": all(
            c["accuracy_below_majority_class"] is True for c in cuts) if cuts else None,
        "auc_ci95_lower_above_chance_all_cuts": all(
            (c["auc_vs_chance"]["ci95_lower_above_chance"] is True) for c in cuts)
            if cuts else None,
        "monotone_trend_all_cuts": all(c["trend_bins_monotone"] for c in cuts)
                                    if cuts else None,
        "max_bucket_auc_below_065_all_cuts": all(
            (c["max_bucket_auc"] is not None and c["max_bucket_auc"] < 0.65) for c in cuts)
            if cuts else None,
        "molecule_level_direction_all_positive": all(
            (c["molecule_level_rho_correct"] or 0) > 0 for c in cuts) if cuts else None,
        "nested_subsets_not_independent": True,
        "nested_note": ("y2023 ⊂ y2021 ⊂ mixed：同一 ChEMBL_37 快照、同一靶点 "
                        "CHEMBL240。用 all(...) 宣称『独立于切法』属伪重复，"
                        "不构成独立证据。"),
        "inference_status": "inference_revoked_pending_estimand",
        "inference_note": ("外审 B：安全端点 AUC 略高于 0.5 不产生决策价值，且真值"
                           "仍是未定义标签。撤销推断资格，不得翻转为『域外仍有弱"
                           "排序能力』；待端点 estimand 卡与 Q4 求证后重估。"),
    }

    payload = {
        "schema_version": "2.0",
        "supersedes": LEGACY_REL,
        "superseded_reason": "C01 跨量纲比较；见 references/RETRACTION_NOTE.md",
        "generated_by": "run_external_cuts_summary.py (v2, 2026-11-04)",
        "estimand_status": "NOT_AN_ESTIMAND (hERG 端点卡未绑定实验金标准)",
        "design": ("同一管道 x 三个时间切点。目的：更正 v4.3 的『post-cutoff』标签"
                   "错误，并检验 E1 的哪一部分是稳健的。三切点为嵌套子集，不是三次"
                   "独立实验。"),
        "label_correction": {
            "was_called": "post-cutoff 外源留出（n=9443）",
            "actually_is": "ChEMBL_37 hERG IC50 全集去重（时间混合，document_year 1995-2025）",
            "why": ("ChEMBL activity 端点对 document__year__gte 实测不生效："
                    ">=2021/2022/2023 三种取值的 total_count 均为 19130；"
                    "缓存内 >=2023 的记录仅占 9.6%。"),
            "fix": "run_external_holdout.fetch_activities 改为本地按 document_year 切分，"
                   "并把 year_filter 元数据落盘。",
            "impact": ("数字（0.581 / n=9443）本身可复现，**标签错**：它不是时间留出，"
                       "不能用于『后见数据前瞻』类表述（红线 8 的对象变了）。"),
        },
        "removed_fields": {
            "below_trivial_baseline": {
                "replaced_by": ["auc_vs_chance", "accuracy_vs_prevalence"],
                "reason": "跨量纲比较，见 robustness.cross_dimensional_comparison",
            },
            "below_trivial_baseline_all_cuts": {
                "replaced_by": ["accuracy_below_majority_class_all_cuts",
                                "auc_ci95_lower_above_chance_all_cuts"],
                "reason": "原字段由跨量纲比较导出，无效",
            },
        },
        "cuts": cuts,
        "robustness": robust,
        "reading": [
            "① 【撤回】旧结论『三套 AUC 都低于同批 always-positive -> 域外没有排序"
            "能力稳健』由跨量纲比较推出，无效。受影响文档：TAIL_RISK_THESIS §2/§3"
            "（含 §0.4/§1/§4/§6/§8）、PAPER_SKELETON_v4.4.md 预测#2 与 Fig6、"
            "POSITIONING『保守的正确』、SKILL.md 判据速查行、CLAIMS_REGISTRY headline。",
            "② 【正确口径】AUC 对照 0.5：三切点 95%CI 下界 0.569/0.560/0.562 均 >0.5；"
            "accuracy 对照 prevalence：逐分子差配对 bootstrap CI 分别为 "
            "[-0.0084,-0.0005] / [-0.0062,+0.0108] / [-0.0209,+0.0063]，"
            "仅 mixed 显著为负，y2021 方向为正且不显著 -> 『独立于切法』不成立；"
            "且三切点是嵌套子集，属伪重复。",
            "③ 【禁止翻转】按外审 B 的领域级修正，不得改称『域外仍有弱排序能力』。"
            "hERG 端点 estimand 未绑定实验金标准，AUC 在此不承载决策含义；"
            "本结论的推断资格已撤销（inference_revoked_pending_estimand），"
            "『域外处处不可用 / 门全拒是保守的正确』一并撤回，改为待重估。",
            "④ 【保留】『AUC 随 Tanimoto 单调上升』只在时间混合集上成立；两个真时间"
            "留出切点均判 trend_not_robust，该定量结论不成立，只能退为分子级弱正相关。",
        ],
        "missing_inputs": missing,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with io.open(OUT, "w", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False, indent=2))

    # 保留旧产物作为审计证据，仅注入撤回标记（幂等，不覆盖任何原字段）
    if os.path.exists(LEGACY):
        old = json.load(io.open(LEGACY, encoding="utf-8"))
        if not old.get("superseded_by"):
            marked = {
                "superseded_by": "out_ext/external/external_cuts_summary_v2.json",
                "superseded_at": "2026-11-04",
                "superseded_reason": "C01 跨量纲比较（RETRACTION_NOTE.md）",
                "retained_for_audit_only": True,
            }
            marked.update(old)
            with io.open(LEGACY, "w", encoding="utf-8") as f:
                f.write(json.dumps(marked, ensure_ascii=False, indent=2))

    print("[cuts] %d 套集合（v2 双轨口径）" % len(cuts))
    for c in cuts:
        av = c["accuracy_vs_prevalence"]
        print("  %-6s n=%-5s AUC=%-6s ci=%-16s acc=%-6s prev=%-6s delta=%-8s below_majority=%s"
              % (c["cut"], c["n"], c["auc"], str(c["auc_vs_chance"]["auc_ci95"]),
                 c["accuracy_at_0.5"], c["prevalence"], av["delta"],
                 c["accuracy_below_majority_class"]))
    print("[cuts] 稳健性:", json.dumps(robust, ensure_ascii=False))
    if missing:
        print("[cuts] 缺失:", missing)
    print("[cuts] ->", os.path.relpath(OUT, HERE))
    return 0


if __name__ == "__main__":
    # C5（2026-11-03 评审）：--help 早退，不产生任何写盘副作用。
    if any(_a in ("-h", "--help") for _a in sys.argv[1:]):
        print("用法：%s（无命令行参数；直接运行即按默认配置产出产物）" % __file__)
        raise SystemExit(0)
    sys.exit(main())
