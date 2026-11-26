# -*- coding: utf-8 -*-
"""问题①：确定性文本生成 + 语义拦截。

设计核心（解决"LLM 把 UNDETERMINED 说成风险较低"）：
1. 槽位投影 project_slots()：UNDETERMINED 记录的 value 字段被**结构性移除**，
   LLM 没有数值槽位可填，从源头杜绝"中位 0.2"这类伪造。
2. 确定性渲染 render_verdict()：模板来自 phrasing.allowed_statement 的等价实现；
   缺槽位直接 KeyError → fail-closed（崩溃而非静默生成错误文本）。
3. 语义拦截 semantic_interceptor()：绝对词/方向词/数值泄漏三查；
   UNDETERMINED/PASSTHRU 出现任何方向词即 reject。
4. LLM 只做"连接词"，sanitize_llm_connectors() 白名单约束。

纯标准库，无外部依赖，可独立测试。
"""

from __future__ import annotations

# ---- 与 SKILL.md phrasing.py 顶部铁律一致的绝对词表 ----
ABSOLUTE_TERMS = (
    "安全",
    "无毒",
    "有效",
    "证明",
    "低风险",
    "风险较低",
    "风险低",
    "可放心",
    "无风险",
    "通过验证",
    "无害",
    "可推进",
    "可以推进",
    "safe",
    "non-toxic",
    "proven",
    "low risk",
    "no risk",
)
# ---- 方向词：仅在非定量裁决（UNDETERMINED/PASSTHRU）时禁止 ----
DIRECTION_TERMS = (
    "优于",
    "劣于",
    "偏高",
    "偏低",
    "促进",
    "抑制",
    "降低风险",
    "升高",
    "higher",
    "lower",
    "increase",
    "decrease",
    "better",
    "worse",
    "风险可控",
    "风险较小",
    "风险更低",
    "更安全",
)
# ---- LLM 允许的连接词白名单（仅"连接器"角色）----
LLM_ALLOWED_CONNECTORS = {
    "因此",
    "然而",
    "同时",
    "据此",
    "综合上述",
    "需注意的是",
    "另外",
    "此外",
    "；",
    "。",
    "，",
    "、",
}

# ---- 槽位白名单：UNDETERMINED/PASSTHRU 根本没有 value 槽位（结构性防呆）----
SLOT_WHITELIST = {
    "UNDETERMINED": ("action", "reason", "certainty_modifier"),
    "PASSTHRU": ("action", "reason", "n_in_domain"),
    "PASS": ("verdict", "certainty_modifier", "n_indep", "value", "unit"),
    "FAIL": ("verdict", "certainty_modifier", "n_indep", "value", "unit"),
}

# ---- 确定性模板（等价于 phrasing.allowed_statement 的输出，便于独立运行）----
TEMPLATES = {
    "UNDETERMINED": "证据不足，方向未定（行动：{action}）",
    "PASSTHRU": "未加权弃权：域内源={n_in_domain}（行动：{action}）",
    "PASS": "{n_indep} 个独立方法组一致指向 PASS（中位 {value} {unit}）",
    "FAIL": "{n_indep} 个独立方法组一致指向 FAIL（中位 {value} {unit}）",
}
FORBIDDEN_GLOBAL = (
    "由 ΔG 换算 Kd/占有率",
    "推断人体剂量",
    "『证明/无毒/安全』等定论词",
)


def project_slots(rec: dict) -> dict:
    """把裁决记录投影为**只允许的槽位**；out_of_domain/saturated/error 的 value 一律抹除。"""
    verdict = rec.get("verdict", "UNDETERMINED")
    allowed = SLOT_WHITELIST.get(verdict, ("action", "reason"))
    slots = {k: rec[k] for k in allowed if k in rec}
    if rec.get("domain_flag") in ("out_of_domain", "saturated", "error"):
        slots.pop("value", None)
        slots.pop("unit", None)
    # 保证模板所需字段存在（缺失则让 format 抛错= fail-closed，但先补 action 的安全默认）
    if verdict in ("UNDETERMINED", "PASSTHRU") and "action" not in slots:
        slots["action"] = rec.get("action") or "按 action 字段执行"
    return slots


def render_verdict(rec: dict) -> dict:
    """确定性渲染。缺槽位 → KeyError（fail-closed）。"""
    slots = project_slots(rec)
    verdict = rec.get("verdict", "UNDETERMINED")
    tmpl = TEMPLATES.get(verdict, TEMPLATES["UNDETERMINED"])
    try:
        text = tmpl.format(**slots)
    except KeyError as e:
        # fail-closed：宁可报错，也不静默生成错误文本
        raise ValueError(
            "模板渲染缺槽位 %s（verdict=%s）——已 fail-closed，"
            "请检查该 verdict 是否被错误地赋予了数值槽位" % (e, verdict)
        )
    return {
        "text": text,
        "verdict": verdict,
        "slots": slots,
        "forbidden": list(FORBIDDEN_GLOBAL),
        "tier": "undetermined" if verdict == "UNDETERMINED" else "quantitative",
    }


def semantic_interceptor(text: str, rec: dict) -> dict:
    """生成后双向语义拦截：绝对词 / 方向词 / 数值泄漏。"""
    v = rec.get("verdict", "UNDETERMINED")
    hits_abs = [t for t in ABSOLUTE_TERMS if t in text]
    hits_dir = (
        [] if v in ("PASS", "FAIL") else [t for t in DIRECTION_TERMS if t in text]
    )
    # 数值泄漏：文本里出现数字，但槽位里没有对应 value（抓 LLM 编造数值）
    value = rec.get("value")
    has_digit = any(ch.isdigit() for ch in text)
    value_leak = bool(has_digit and value is None)
    ok = not hits_abs and not hits_dir and not value_leak
    return {
        "ok": ok,
        "hits_absolute": hits_abs,
        "hits_direction": hits_dir,
        "value_leak": value_leak,
        "verdict": v,
        "action": "pass" if ok else "reject_and_fallback_to_deterministic_template",
    }


def sanitize_llm_connectors(llm_output: str) -> str:
    """LLM 输出必须逐 token 属于连接词白名单，否则整段丢弃（fail-closed）。"""
    if not llm_output:
        return ""
    toks = llm_output.strip().split()
    if not toks:
        return ""
    if all(t in LLM_ALLOWED_CONNECTORS for t in toks):
        return llm_output
    return ""  # 含白名单外内容 → 丢弃


def safe_render(rec: dict, llm_text: str = "") -> dict:
    """完整管线：确定性渲染 → 叠加（合规的）LLM 连接词 → 语义拦截 → 决定最终文本。

    intercepted=True 的两种情况（都属于"LLM 越界被拦"）：
      (a) LLM 连接词含白名单外内容 → 整段丢弃；
      (b) 叠加后文本触发语义拦截 → 回退确定性模板。
    两者都必须让调用方知道"LLM 的输入没有被采纳"，故 intercepted 统一为 True。
    """
    base = render_verdict(rec)
    final = base["text"]
    llm_dropped = False
    if llm_text:
        clean = sanitize_llm_connectors(llm_text)
        if clean:
            final = final + " " + clean
        else:
            llm_dropped = True  # LLM 文本含白名单外内容，被丢弃

    check = semantic_interceptor(final, rec)
    if not check["ok"]:
        # 拦截失败 → 回退纯确定性文本，并再拦一次（纯模板必须过）
        final = base["text"]
        check = semantic_interceptor(final, rec)
        return {
            "text": final,
            "intercepted": True,
            "check": check,
            "fallback_reason": "LLM 文本触发语义拦截，已回退确定性模板",
        }

    if llm_dropped:
        return {
            "text": final,
            "intercepted": True,
            "check": check,
            "fallback_reason": "LLM 输出含白名单外内容（如'综合来看/风险较低'），已整段丢弃",
        }
    return {"text": final, "intercepted": False, "check": check, "fallback_reason": ""}
