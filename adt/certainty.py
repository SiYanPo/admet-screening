# -*- coding: utf-8 -*-
"""工作包 I：GRADE 式证据确定性修饰符（把三态升级为可比较的确定性语言）。

外部评审意见（2026-10-29）指出：三态 PASS/FAIL/UNDETERMINED 在信息粒度上对称，
但"证据的确定性本身是分层的"。UNDETERMINED 至少有两类，决策含义完全不同：
  - 低确定性-可解决：分歧来自单位异构/版本漂移/少一个独立源 -> 补低成本信息即可裁决
  - 低确定性-不可解决：全部源在本化学类域外且无实验可补 -> 只能湿实验或放弃计算推进
  - 中确定性-需实验锚定：有域内方向信号但未过计票门槛 -> 一个确认性实验即可

本模块只做**标注**，不改变 verdict。映射到 GRADE 的四个维度
（indirectness / inconsistency / imprecision / risk of bias，
GRADE Guidelines 30 对模型证据的适用性讨论），但不声称"实现了完整 GRADE"。
"""

CERTAINTY_LEVELS = (
    "high",
    "moderate",
    "low_resolvable",
    "low_unresolvable",
    "medium_needs_experiment",
)

# 方向C（2026-10-30 第三次评审）：把确定性分级从"描述性修饰符"升级为**与决策阈值挂钩**
# 的映射。GRADE 2025 手册强调"确定性评级必须与决策阈值挂钩"——这里把该逻辑迁移到
# 计算 ADMET 裁决：确定性等级直接规定下游决策的**允许范围**，而不只是形容词。
DECISION_TRIGGER = {
    "high": "可进入 go/no-go 与 T2/T3 结论（数值仍受措辞封顶约束）",
    "moderate": "可用于 go/no-go 筛选，但**不得**用于排序或精确数值决策",
    "medium_needs_experiment": "补一个指定确认性实验即可升级为 moderate；"
    "在此之前不给方向词，优先分配该实验预算",
    "low_resolvable": "补一个独立生态源/统一单位/补版本后可重判；当前不进入任何采购决策",
    "low_unresolvable": "不得基于计算推进；只能湿实验或放弃该端点（计算路径到此为止）",
}

# 每个等级"下一步该做什么"的一句话（给 action 字段用，避免笼统的"补实验"）
DECISION_NEXT_STEP = {
    "high": "直接用于筛选决断，记录证据来源备审计",
    "moderate": "仅作方向性判断；不得据此排序或报精确值",
    "medium_needs_experiment": "执行一个确认性实验（端点见 action）后重跑裁决",
    "low_resolvable": "补齐缺失信息（独立源/单位统一/版本）后重跑，成本低、优先做",
    "low_unresolvable": "转湿实验或终止该端点的计算路径，不要继续加源",
}

# 可直接由"补信息"解决的 UNDETERMINED 原因关键词
_RESOLVABLE_HINTS = (
    "单位异构",
    "独立方法组仅",
    "独立组",
    "版本",
    "class_map",
    "灰区",
    "落在关注带",
    "至少一个源落在灰区",
)
# 只能靠湿实验/换源解决的
_UNRESOLVABLE_HINTS = (
    "全部源域外",
    "越物理边界",
    "无阈值规则",
    "全部 %d 个值越物理边界",
)
_EXPERIMENT_HINTS = (
    "落在关注带",
    "不足以判 PASS/FAIL",
    "补实测",
    "分歧过大",
    "方向相反",
)


def _contains(reason, hints):
    return any(h.replace("%d", "") in (reason or "") for h in hints)


def _version_index(measurements):
    """预建 {(compound_id, endpoint): {source_version}} —— 避免逐记录全表扫描（O(n²)）。

    v3.5.0 修复：旧实现在 grade_dimensions 里对每条 rec 遍历整个 measurements，
    20k rec × 41k 行 = 8×10^8 次比较，certainty 命令在真实 OpenADMET 面板上直接超时。
    """
    idx = {}
    for r in measurements or []:
        v = r.get("source_version")
        if not v:
            continue
        key = (r.get("compound_id"), r.get("endpoint"))
        idx.setdefault(key, set()).add(v)
    return idx


def grade_dimensions(rec, measurements=None, ver_index=None):
    """把一条 reliability 记录映射到 GRADE 四维度（low/moderate/high）。

    - indirectness：域内源占比 + 是否整类 blocked（域外 = 高间接性）
    - inconsistency：源间极差是否超阈值（spread 字段）
    - imprecision：独立组数是否不足 / 是否只有 1 个域内源
    - risk_of_bias：同 (cid, ep, source) 是否出现多版本（版本漂移 = 高偏倚风险）
    """
    n_total = int(rec.get("n_total") or 0)
    n_dom = int(rec.get("n_in_domain") or 0)
    n_indep = int(rec.get("n_indep_groups") or 0)
    frac = (n_dom / float(n_total)) if n_total else 0.0

    if n_dom == 0:
        indirect = "high"
    elif frac < 0.5:
        indirect = "moderate"
    else:
        indirect = "low"

    try:
        spread = float(rec.get("spread") or 0.0)
    except (TypeError, ValueError):
        spread = 0.0
    inconsistency = (
        "high" if spread > 0.30 else ("moderate" if spread > 0.15 else "low")
    )

    if n_indep < 2:
        imprecision = "high"
    elif n_indep < 3:
        imprecision = "moderate"
    else:
        imprecision = "low"

    rob = "not_assessed"
    if ver_index is not None:
        vers = ver_index.get((rec.get("compound_id"), rec.get("endpoint")), set())
        if len(vers) > 1:
            rob = "high(version_drift)"
    elif measurements:
        vers = {
            r.get("source_version")
            for r in measurements
            if r.get("compound_id") == rec.get("compound_id")
            and r.get("endpoint") == rec.get("endpoint")
            and r.get("source_version")
        }
        if len(vers) > 1:
            rob = "high(version_drift)"

    return dict(
        indirectness=indirect,
        inconsistency=inconsistency,
        imprecision=imprecision,
        risk_of_bias=rob,
    )


def classify(rec, dims=None):
    """返回 (certainty_modifier, rationale)。"""
    dims = dims or grade_dimensions(rec)
    verdict = rec.get("verdict", "")
    conf = (rec.get("confidence") or "").lower()
    reason = rec.get("reason") or ""
    n_dom = int(rec.get("n_in_domain") or 0)
    n_indep = int(rec.get("n_indep_groups") or 0)
    dimstr = "indirectness=%s; inconsistency=%s; imprecision=%s; RoB=%s" % (
        dims["indirectness"],
        dims["inconsistency"],
        dims["imprecision"],
        dims["risk_of_bias"],
    )

    if verdict in ("PASS", "FAIL"):
        if conf == "high" and dims["risk_of_bias"] != "high(version_drift)":
            return "high", "实测/多组一致且无版本漂移：" + dimstr
        highs = sum(
            1
            for k in ("indirectness", "inconsistency", "imprecision")
            if dims[k] == "high"
        )
        if highs >= 2:
            return "moderate", "方向可判但两维以上为高不确定：" + dimstr
        return "moderate", "预测一致但非实测：" + dimstr

    # UNDETERMINED：区分可解决 / 不可解决 / 需实验
    if n_dom == 0 or _contains(reason, _UNRESOLVABLE_HINTS):
        return "low_unresolvable", "所有可用源在本化学类域外/无效：" + dimstr
    if _contains(reason, _RESOLVABLE_HINTS):
        return (
            "low_resolvable",
            "信息缺口可低成本补齐（补源/统一单位/补版本）：" + dimstr,
        )
    if _contains(reason, _EXPERIMENT_HINTS):
        return (
            "medium_needs_experiment",
            "有方向信号但未过门槛，需一个确认性实验：" + dimstr,
        )
    if n_indep >= 1 and n_dom >= 1:
        return "low_resolvable", "域内有信号但票数不足，可补一个独立源：" + dimstr
    return "low_unresolvable", "无足够域内证据：" + dimstr


def annotate(recs, measurements=None):
    """给 reliability 记录列表就地加 certainty_modifier / certainty_rationale。"""
    ver_index = _version_index(measurements) if measurements else {}
    for r in recs:
        dims = grade_dimensions(r, ver_index=ver_index)
        mod, why = classify(r, dims)
        r["certainty_modifier"] = mod
        r["certainty_rationale"] = why
        r["decision_trigger"] = DECISION_TRIGGER.get(mod, "")
        r["decision_next_step"] = DECISION_NEXT_STEP.get(mod, "")
        r["grade_indirectness"] = dims["indirectness"]
        r["grade_inconsistency"] = dims["inconsistency"]
        r["grade_imprecision"] = dims["imprecision"]
        r["grade_rob"] = dims["risk_of_bias"]
    return recs


def mapping_table():
    """写进文档/论文的映射表（不参与计算）。"""
    return [
        dict(
            modifier="high",
            grade="高",
            decision="可直接进入 T2/T3 结论（仍需措辞封顶）",
            decision_trigger=DECISION_TRIGGER["high"],
        ),
        dict(
            modifier="moderate",
            grade="中",
            decision="可作方向性结论，禁止精确数值与排名",
            decision_trigger=DECISION_TRIGGER["moderate"],
        ),
        dict(
            modifier="medium_needs_experiment",
            grade="中（需实验锚定）",
            decision="一个确认性实验即可定档；在此之前不给方向词",
            decision_trigger=DECISION_TRIGGER["medium_needs_experiment"],
        ),
        dict(
            modifier="low_resolvable",
            grade="低（可解决）",
            decision="补一个独立源/统一单位/补版本后可重判；暂不采购决策",
            decision_trigger=DECISION_TRIGGER["low_resolvable"],
        ),
        dict(
            modifier="low_unresolvable",
            grade="低（当前不可解决）",
            decision="计算路径到此为止；只能湿实验或放弃该端点",
            decision_trigger=DECISION_TRIGGER["low_unresolvable"],
        ),
    ]
