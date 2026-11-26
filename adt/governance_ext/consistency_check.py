# -*- coding: utf-8 -*-
"""盲区2：Fast Mode 静默劣化防御——轻量级内部一致性校验。

问题：Fast Mode 为求快，缓存损坏/子进程超时时可能静默跳过端点或返回默认值，
但报告仍标 exploratory_only，用户误当绿灯决策。

对策：在 Fast Mode 输出前，用**物理/化学不变量**做交叉校验。任一致命矛盾 →
拒绝 T1 结论，返回 data_inconsistent，强制 Rigorous 重跑。

这些校验不需要外部源、不增加延迟（纯描述符算术），是 Fast Mode 的"内部熔断"。
纯标准库 + 可选 rdkit 描述符（通过 l0_guard 已算好的字段传入）。
"""

from __future__ import annotations

# 致命矛盾（任一命中 → 拒绝 T1）
CRITICAL = "critical"
WARN = "warn"


def check_consistency(record):
    """record 至少含: mol_wt, n_atoms, logp, tpsa, hbd, hba, n_rings, ...
    缺失字段则跳过对应校验（不误报）。

    返回 dict(consistent, critical=[], warnings=[], refuse_t1=bool)
    """
    crit, warn = [], []
    g = record.get

    mw = g("mol_wt")
    n_atoms = g("n_atoms")
    logp = g("logp")
    tpsa = g("tpsa")
    hbd, hba = g("hbd"), g("hba")
    n_rings = g("n_rings")

    # --- 数值合法性（NaN/Inf/负）---
    for key, v in (("mol_wt", mw), ("logp", logp), ("tpsa", tpsa)):
        if isinstance(v, float) and (v != v or v in (float("inf"), float("-inf"))):
            crit.append("%s 非有限值(%r)——子进程/缓存异常" % (key, v))
    if isinstance(mw, (int, float)) and mw <= 0:
        crit.append("mol_wt<=0(%r)——结构解析失败" % mw)
    if isinstance(tpsa, (int, float)) and tpsa < 0:
        crit.append("tpsa<0(%r)——物理不可能" % tpsa)

    # --- 核心矛盾：LogP vs 分子量（用户举的例子 LogP=8 & MW=150）---
    if isinstance(logp, (int, float)) and isinstance(mw, (int, float)):
        if logp > 6.0 and mw < 200:
            crit.append(
                "LogP=%.1f 但 MW=%.0f：小分子不可能如此亲脂，结构/计算严重出错"
                % (logp, mw)
            )
        if logp > 10 or logp < -6:
            crit.append("LogP=%.1f 超出物理可信区间[-6,10]" % logp)

    # --- LogP vs 极性表面积：TPSA 很高却极亲脂 → 矛盾 ---
    if isinstance(logp, (int, float)) and isinstance(tpsa, (int, float)):
        if tpsa > 140 and logp > 4:
            crit.append(
                "TPSA=%.0f 高极性 而 LogP=%.1f 高亲脂：不可能同时成立" % (tpsa, logp)
            )
        if tpsa < 10 and logp < -3:
            warn.append("TPSA<10 且 LogP<−3：疑数据缺列或单位错")

    # --- MW vs 重原子数：MW/atoms 应落在合理区间 ---
    if (
        isinstance(mw, (int, float))
        and isinstance(n_atoms, (int, float))
        and n_atoms > 0
    ):
        ratio = mw / n_atoms
        if ratio < 3.0:
            crit.append("MW/原子数=%.2f 过低（应≥~5）：原子数或分子量记录错误" % ratio)
        if ratio > 25.0:
            crit.append("MW/原子数=%.2f 过高（应≤~20）：疑含重原子/盐未去" % ratio)

    # --- HBD/HBA vs MW：氢键数不可能超过原子总数 ---
    if isinstance(hbd, (int, float)) and isinstance(n_atoms, (int, float)):
        if hbd > n_atoms:
            crit.append("HBD=%d > 原子总数=%d：不可能" % (hbd, n_atoms))
    if isinstance(hba, (int, float)) and isinstance(n_atoms, (int, float)):
        if hba > n_atoms:
            crit.append("HBA=%d > 原子总数=%d：不可能" % (hba, n_atoms))

    # --- 环数 vs 原子数 ---
    if (
        isinstance(n_rings, (int, float))
        and isinstance(n_atoms, (int, float))
        and n_atoms > 0
    ):
        if n_rings > n_atoms / 2.0:
            crit.append("环数=%d > 原子数/2=%d：不可能" % (n_rings, n_atoms / 2.0))

    refuse = len(crit) > 0
    return {
        "consistent": not refuse,
        "critical": crit,
        "warnings": warn,
        "refuse_t1": refuse,
        "action": (
            "数据矛盾，拒绝给出 T1 结论；请用 Rigorous 模式重跑"
            if refuse
            else ("有告警，可出 T1 但须标注" if warn else "通过")
        ),
    }


def guard_fast_output(record):
    """Fast Mode 输出前的最终内部熔断。

    若 refuse_t1 → 把结论强制改为 UNDETERMINED(data_inconsistent)，绝不流出 T1。
    """
    c = check_consistency(record)
    if c["refuse_t1"]:
        out = dict(record)
        out["verdict"] = "UNDETERMINED"
        out["certainty_modifier"] = "low_unresolvable"
        out["reason"] = "data_inconsistent"
        out["detail"] = "; ".join(c["critical"])
        out["tier_ceiling"] = "T0"  # 连 T1 都不给
        out["fast_guard"] = c
        return out
    out = dict(record)
    out["fast_guard"] = c
    if c["warnings"]:
        out["note"] = "一致性告警: " + "; ".join(c["warnings"])
    return out
