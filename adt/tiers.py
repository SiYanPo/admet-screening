# -*- coding: utf-8 -*-
"""运行档位 T1/T2/T3 + 项目级结论封顶（移植自 reverse-molecular-docking E0/门控状态机）。

与 phrasing.py 的分工
---------------------
- `phrasing.allowed_statement()`：**行级**措辞封顶——单个 (分子×端点) 能说到多强。
- 本模块：**项目级**结论封顶——**整批证据**能支撑到"探索 / 决策 / 发表"哪一档。
两者叠加：行级决定每句话，项目级决定整篇报告的上限。缺任一层都会出现
"每句都合规、整篇却在过度声称"的情况。

档位定义（对应反向 skill 的 T1/T2/T3）
--------------------------------------
  T1 快筛   → 结论上限 exploratory_only （探索性趋势；**不得进论文结论表**）
  T2 标准   → 结论上限 decision_support （项目决策/标书预实验；不得写"已确证/安全"）
  T3 发表   → 结论上限 publication      （论文正式结论；需实测真值 + 独立基准 + 覆盖声明）

判定规则（可复核、不靠自觉）
------------------------------
  T3 = n_measured≥1 且 有独立基准(且可算 AUROC) 且 有覆盖矩阵
  T2 = n_measured≥1 或 ≥1 个端点达到 2 个独立方法组
  T1 = 其余
"""

import csv
import io
import os

TIERS = ["T1", "T2", "T3"]
MAX_CONCLUSION = {
    "T1": "exploratory_only",
    "T2": "decision_support",
    "T3": "publication",
}


def _int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def _isnum(v):
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


def stats_from_reliability(recs):
    """从 reliability.csv 行统计证据构成。"""
    n_measured = sum(1 for r in recs if _int(r.get("n_measured")) > 0)
    n_judged = sum(1 for r in recs if r.get("verdict") in ("PASS", "FAIL"))
    n_indep2 = sum(
        1
        for r in recs
        if r.get("verdict") in ("PASS", "FAIL") and _int(r.get("n_indep_groups")) >= 2
    )
    return dict(
        n_rows=len(recs),
        n_measured=n_measured,
        n_judged=n_judged,
        n_judged_indep2=n_indep2,
    )


def assign(
    stats, has_benchmark=False, has_coverage_decl=False, benchmark_ok=False, rob=None
):
    """返回 (tier, max_conclusion, missing_for_next)。

    rob：PROBAST 整体偏倚风险（low/medium/high）。**high 不得升 T3**——
    发表级结论要求偏倚风险低/中（Wolff 2019, Ann Intern Med 170:51-58）。
    rob=None 表示未评估（不施加约束，保持旧行为）。
    """
    nm = stats.get("n_measured", 0)
    nj2 = stats.get("n_judged_indep2", 0)
    rob_block = rob == "high"
    if (
        nm >= 1
        and has_benchmark
        and has_coverage_decl
        and benchmark_ok
        and not rob_block
    ):
        tier = "T3"
    elif nm >= 1 or nj2 >= 1:
        tier = "T2"
    else:
        tier = "T1"

    missing = []
    if tier == "T1":
        if nj2 < 1:
            missing.append("至少 1 个端点达到 2 个独立方法组（当前 %d）" % nj2)
        if nm < 1:
            missing.append("至少 1 个实测端点")
    if tier != "T3":
        if nm < 1:
            missing.append("实测真值（T3 必须）")
        if not has_benchmark:
            missing.append("独立基准（benchmark --demo 不算）")
        if not has_coverage_decl:
            missing.append("覆盖声明（coverage 矩阵）")
        if rob_block:
            missing.append(
                "偏倚风险降为低/中（PROBAST 当前 high：无实测真值/单方法组）"
            )
    return tier, MAX_CONCLUSION[tier], missing


def enforce(requested, allowed):
    """请求档位是否超过证据允许档位。返回 (ok, msg)。"""
    if requested not in TIERS:
        return False, "未知档位 %r（只允许 %s）" % (requested, TIERS)
    if TIERS.index(requested) > TIERS.index(allowed):
        return False, (
            "越级：请求 %s（%s），但证据只支持 %s（%s）"
            % (requested, MAX_CONCLUSION[requested], allowed, MAX_CONCLUSION[allowed])
        )
    return True, "ok"


def write(path, row):
    cols = [
        "tier",
        "max_conclusion",
        "n_rows",
        "n_measured",
        "n_judged",
        "n_judged_indep2",
        "has_benchmark",
        "benchmark_ok",
        "has_coverage_decl",
        "risk_of_bias",
        "missing",
    ]
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with io.open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerow(row)
    return 1
