# -*- coding: utf-8 -*-
"""盲区5：三层报告交付体系 + 盲区6：生物学-ADMET 决策脱节警告。

三层报告：executive / scientist / audit。
铁律：**黄灯（UNDETERMINED）在任何层都不能变成绿灯**。
纯标准库（脱节检查的数值判定），可独立测试。
"""

from __future__ import annotations

# 三态 → 红绿灯（机械映射，禁止 LLM 自由判断）
TRAFFIC_LIGHT = {
    "PASS": ("green", "未见风险信号，可按流程推进"),
    "FAIL": ("red", "发现风险信号，建议淘汰或结构优化"),
    "UNDETERMINED": ("yellow", "证据不足，需补实验/补源"),
    "PASSTHRU": ("yellow", "未加权弃权，方向未定"),
}

REPORT_LEVELS = {
    "executive": {
        "show": ["traffic_light", "headline", "action"],
        "vocab": "禁统计学词汇",
    },
    "scientist": {
        "show": ["per_endpoint", "confidence", "domain", "measured_vs_pred", "action"],
        "vocab": "可用置信度/适用域术语",
    },
    "audit": {
        "show": ["manifest", "evidence_dag", "claims", "redline", "tier", "provenance"],
        "vocab": "完整可复现信息",
    },
}


def _light(verdict):
    return TRAFFIC_LIGHT.get(verdict, TRAFFIC_LIGHT["UNDETERMINED"])


def render_report(level, verdict_records, manifest=None):
    """按报告层级渲染。verdict_records: {endpoint: rec}。"""
    if level not in REPORT_LEVELS:
        raise ValueError("未知 report-level: %r" % level)
    if level == "executive":
        rows = []
        for ep, rec in verdict_records.items():
            color, msg = _light(rec["verdict"])
            # executive 层绝不说"安全/低风险"；黄灯必须显式"需补实验"
            rows.append(
                {
                    "endpoint": ep,
                    "light": color,
                    "headline": msg,
                    "action": rec.get("action") or "按流程推进",
                }
            )
        # 铁律自检：executive 层不得出现"安全/低风险"
        text_blob = " ".join(r["headline"] + r["action"] for r in rows)
        forbidden = [w for w in ("安全", "低风险", "无毒", "有效") if w in text_blob]
        return {
            "level": "executive",
            "rows": rows,
            "self_check": {"forbidden_found": forbidden, "ok": not forbidden},
            "note": "executive 层只给红绿灯与行动，不含统计学术语",
        }
    if level == "scientist":
        rows = []
        for ep, rec in verdict_records.items():
            rows.append(
                {
                    "endpoint": ep,
                    "verdict": rec["verdict"],
                    "confidence": rec.get("confidence"),
                    "domain_flag": rec.get("domain_flag"),
                    "value": rec.get("value"),
                    "unit": rec.get("unit"),
                    "measured_or_predicted": rec.get("domain_flag"),
                    "action": rec.get("action", ""),
                }
            )
        return {"level": "scientist", "rows": rows}
    # audit
    return {
        "level": "audit",
        "manifest": manifest or {},
        "records": verdict_records,
        "note": "完整 manifest / evidence DAG / claims / redline 状态",
    }


# ---- 盲区6：决策脱节 ----
def decision_disjunction_check(
    admet_verdicts,
    potency_ic50_nM,
    cmax_u_uM,
    *,
    ic50_threshold_uM=10.0,
    margin_red=10.0,
):
    """ADMET 全绿但靶点活性/暴露不达标 → 强警告。

    admet_verdicts: {compound_id: {ep: rec}}
    potency_ic50_nM: {compound_id: nM}
    cmax_u_uM: {compound_id: µM}（可缺省）
    """
    warnings = []
    for cid, eps in admet_verdicts.items():
        admet_green = bool(eps) and all(r["verdict"] == "PASS" for r in eps.values())
        if not admet_green:
            continue
        ic50_nM = potency_ic50_nM.get(cid)
        if ic50_nM is None:
            continue
        ic50_uM = ic50_nM / 1000.0
        if ic50_uM > ic50_threshold_uM:
            warnings.append(
                {
                    "compound_id": cid,
                    "level": "STRONG",
                    "type": "TARGET_POTENCY_INSUFFICIENT",
                    "msg": "ADMET 全绿但靶点 IC50=%.1fµM > %.1fµM——"
                    "优秀的 ADMET profile 不能挽救薄弱的生物学假设"
                    % (ic50_uM, ic50_threshold_uM),
                }
            )
        cmax = cmax_u_uM.get(cid) if cmax_u_uM else None
        if cmax is not None and ic50_uM > 0:
            margin = cmax / ic50_uM
            if margin < margin_red:
                warnings.append(
                    {
                        "compound_id": cid,
                        "level": "STRONG",
                        "type": "EXPOSURE_MARGIN_INSUFFICIENT",
                        "msg": "暴露/靶点裕度 Margin=%.2f < %.1f——体内可能达不到有效浓度"
                        % (margin, margin_red),
                    }
                )
    return {
        "n_warnings": len(warnings),
        "warnings": warnings,
        "note": "阈值 10µM/10x 为常见先导经验值，依赖具体靶点与项目阶段，须作为参数传入",
    }
