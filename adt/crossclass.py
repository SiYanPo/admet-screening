# -*- coding: utf-8 -*-
"""跨化学类的裁决行为一致性（方向4）。

报告方向4 的核心命题：本框架"证据准入先于证据组合"如果是方法学层面的，它必须在不同化学类上
表现出一致的裁决行为模式；如果只在肉桂酰糖苷上成立，审稿人会把它读成"针对糖苷调过的规则"。

本模块把多个化学空间（每个空间一个 reliability.csv）放在**同一组行为指标**下对比，并检验一个
可检验的预测：

    弃权率 应随 化学空间的可裁决性复杂度 单调变化——
    高极性糖苷类（域外源多、单组端点多）→ 弃权率应显著高于 药物样 OpenADMET 空间。

若反向（糖苷类弃权率反而更低），则是结构性缺口（class block / 独立性分组在高极性类上未正确触发），
必须诚实报告并定位根因。本模块把"我们的框架很保守"升级为"框架的保守程度随可裁决性单调变化，
这是准入逻辑的一个可检验预测"。

指标（均不依赖外部真值，故可在任意空间计算）：
  - abstention_rate = (UNDETERMINED + PASSTHRU) / total_rows
  - decided_rate    = (PASS + FAIL) / total_rows
  - verdict 分布（PASS/FAIL/UNDETERMINED/PASSTHRU 计数与占比）
  - certainty 分布（若列存在：moderate/low_unresolvable/medium_needs_experiment/high）
  - failure_mode 命中频率（从 reason 列抽取 domain/single_group/phys_range 等关键词）
"""

import csv
import os

ABSTAIN = {"UNDETERMINED", "PASSTHRU"}
DECIDED = {"PASS", "FAIL"}

# reason 列中可识别的失效/准入模式关键词（与 failure_modes 模块对齐）
FM_KEYWORDS = {
    "domain_block": "domain",
    "single_group": "single_group",
    "phys_range": "phys_range",
    "unit_isomerism": "isomer",
    "out_of_domain": "out_of_domain",
}


def analyze_space(path, label=""):
    """从单个 reliability.csv 计算该化学空间的行为指标。"""
    n_rows = 0
    n_compounds = set()
    n_endpoints = set()
    verdict = {"PASS": 0, "FAIL": 0, "UNDETERMINED": 0, "PASSTHRU": 0, "other": 0}
    certainty = {}
    fm_hits = {k: 0 for k in FM_KEYWORDS}
    with open(path, encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            n_rows += 1
            n_compounds.add(r.get("compound_id", ""))
            n_endpoints.add(r.get("endpoint", ""))
            v = (r.get("verdict") or "").strip()
            verdict[v if v in verdict else "other"] += 1
            cm = (r.get("certainty_modifier") or "").strip()
            if cm:
                certainty[cm] = certainty.get(cm, 0) + 1
            reason = (r.get("reason") or "").lower()
            for k, kw in FM_KEYWORDS.items():
                if kw in reason:
                    fm_hits[k] += 1
    abstain = verdict["UNDETERMINED"] + verdict["PASSTHRU"]
    decided = verdict["PASS"] + verdict["FAIL"]
    return dict(
        label=label or os.path.basename(path),
        path=path,
        n_rows=n_rows,
        n_compounds=len(n_compounds),
        n_endpoints=len(n_endpoints),
        verdict=verdict,
        abstention_rate=(abstain / n_rows) if n_rows else float("nan"),
        decided_rate=(decided / n_rows) if n_rows else float("nan"),
        pass_rate=(verdict["PASS"] / n_rows) if n_rows else float("nan"),
        fail_rate=(verdict["FAIL"] / n_rows) if n_rows else float("nan"),
        certainty=certainty,
        failure_mode_hits=fm_hits,
        failure_mode_rate={
            k: (c / n_rows if n_rows else float("nan")) for k, c in fm_hits.items()
        },
    )


def compare_spaces(
    spaces,
    prediction_note="",
    expected_highest_abstention=None,
    expected_lowest_abstention=None,
):
    """多空间对比，并检验"弃权率随可裁决性单调变化"的可检验预测。

    spaces: [analyze_space(...)] 列表。
    expected_highest_abstention / expected_lowest_abstention: 标签（label），声明
        **按准入逻辑预期**哪一类应有最高/最低弃权率（即可裁决性最低/最高者）。
        例如高极性糖苷类应 highest、药物样 OpenADMET 应 lowest。
        二者都给出时，预测检验按"预期方向"而非"裸排序"判定——这才能暴露
        "反向"（最该弃权的类反而弃权最少）这一结构性缺口。

    返回 dict：per_space, ordered_by_abstention, prediction_check。
    """
    per = {s["label"]: s for s in spaces}
    ordered = sorted(spaces, key=lambda s: -s["abstention_rate"])
    if len(spaces) >= 2 and expected_highest_abstention and expected_lowest_abstention:
        hi_exp = per.get(expected_highest_abstention)
        lo_exp = per.get(expected_lowest_abstention)
        if hi_exp is None or lo_exp is None:
            check = "预期标签 %s/%s 不在已分析空间中，无法检验预测" % (
                expected_highest_abstention,
                expected_lowest_abstention,
            )
        else:
            delta = hi_exp["abstention_rate"] - lo_exp["abstention_rate"]
            if delta >= 0.05:
                check = (
                    "符合预期：预期高弃权空间=%s(%.3f) 实际也高于预期低弃权=%s(%.3f)，"
                    "差异 %.3f —— 弃权率随可裁决性单调变化，与准入逻辑预测一致"
                    % (
                        hi_exp["label"],
                        hi_exp["abstention_rate"],
                        lo_exp["label"],
                        lo_exp["abstention_rate"],
                        delta,
                    )
                )
            elif delta <= -0.05:
                check = (
                    "⚠ 反向：预期高弃权空间=%s(%.3f) 实际反而低于预期低弃权=%s(%.3f) —— "
                    "这指向 class block / 独立性分组在高极性类未正确触发的结构性缺口，"
                    "须定位根因（见报告方向4 风险提示）"
                    % (
                        hi_exp["label"],
                        hi_exp["abstention_rate"],
                        lo_exp["label"],
                        lo_exp["abstention_rate"],
                    )
                )
            else:
                check = (
                    "差异 %.3f <0.05，不足以支持单调变化预测（需更多空间/更大样本）"
                    % delta
                )
    elif len(spaces) >= 2:
        hi = max(spaces, key=lambda s: s["abstention_rate"])
        lo = min(spaces, key=lambda s: s["abstention_rate"])
        delta = hi["abstention_rate"] - lo["abstention_rate"]
        # v3.6.2：原提示一律写"未声明预期方向"，即使调用方只给了单侧（high 或 low）
        # 也会这么写，误导读者以为完全没声明。现区分四种情况，明确缺哪一侧。
        if expected_highest_abstention or expected_lowest_abstention:
            missing = []
            if not expected_highest_abstention:
                missing.append("--expected-high")
            if not expected_lowest_abstention:
                missing.append("--expected-low")
            prefix = "（只声明了单侧预期，缺 %s，故只作描述性报告）" % "、".join(
                missing
            )
        else:
            prefix = "（未声明预期方向）"
        if hi["label"] == lo["label"]:
            check = "需要至少两个不同化学空间才能检验预测"
        elif delta > 0.05:
            check = "%s最高弃权空间=%s(%.3f) 显著高于最低=%s(%.3f)，" "差异 %.3f" % (
                prefix,
                hi["label"],
                hi["abstention_rate"],
                lo["label"],
                lo["abstention_rate"],
                delta,
            )
        else:
            check = "差异 <0.05，不足以支持单调变化预测（需更多空间/更大样本）"
    else:
        check = "需要至少两个不同化学空间才能检验预测"
    return dict(
        per_space=per,
        ordered_by_abstention=ordered,
        prediction_check=check,
        prediction_note=prediction_note,
    )


def write(path, spaces, comparison):
    import io

    cols = [
        "label",
        "n_rows",
        "n_compounds",
        "n_endpoints",
        "PASS",
        "FAIL",
        "UNDETERMINED",
        "PASSTHRU",
        "other",
        "abstention_rate",
        "decided_rate",
        "pass_rate",
        "fail_rate",
    ]
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with io.open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for s in spaces:
            v = s["verdict"]
            w.writerow(
                dict(
                    label=s["label"],
                    n_rows=s["n_rows"],
                    n_compounds=s["n_compounds"],
                    n_endpoints=s["n_endpoints"],
                    PASS=v["PASS"],
                    FAIL=v["FAIL"],
                    UNDETERMINED=v["UNDETERMINED"],
                    PASSTHRU=v["PASSTHRU"],
                    other=v["other"],
                    abstention_rate=round(s["abstention_rate"], 4),
                    decided_rate=round(s["decided_rate"], 4),
                    pass_rate=round(s["pass_rate"], 4),
                    fail_rate=round(s["fail_rate"], 4),
                )
            )
    return len(spaces)
