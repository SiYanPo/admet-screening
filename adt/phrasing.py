# -*- coding: utf-8 -*-
"""A1 措辞封顶：verdict + confidence + 独立组数 -> 允许的最高表述。

铁律（借自外部对接 skill 治理层）：**门没过不是报错，而是措辞自动降级**——
防止用好看的表述掩盖没过的门。所有面向报告/论文的句子必须从这个模块取模板，
禁止越过模板自由发挥。

绝对禁止的表述（无论证据多好）：
  - 由对接 ΔG 反推 Kd / 占有率（结合自由能的经验打分不具备该换算的物理基础）
  - 由预测值直接推断"人体剂量 / 安全窗"
  - "证明 / 无毒 / 安全"这类定论词（最高只允许"一致指向 / 未见风险信号"）
"""

import os

import io


def allowed_statement(
    verdict,
    confidence,
    n_indep=1,
    non_ranking=False,
    measured=False,
    action="",
    projection=False,
):
    """返回该行证据**允许使用的最高表述模板**与禁止项。

    返回 dict(tier=等级名, template=模板, forbidden=[禁用表述])

    projection（C9，2026-11-03 评审）：该 verdict 来自"跨源单位异构 → class_map
    类别投射"路径，**不是**原始数值共识。必须给独立模板，否则报告会把它写成
    "中位 X"——那是把一个 0/1 类别映射冒充成校准后的概率。
    """
    if verdict == "UNDETERMINED":
        return dict(
            tier="undetermined",
            template="证据不足，方向未定（行动：%s）"
            % (action or "按 action 字段执行"),
            forbidden=["任何方向性结论", "任何排名位置"],
        )

    if measured:
        tier, tmpl = "measured", "实测结果为 {value} {unit}——结论：{verdict}"
    # C58（评估 P3-16）：原 `elif confidence == "high"` 分支不可达——high 只可能
    # 来自 measured 分支，必先被上面截获；且模板里的 %d 从未被替换（report 只做
    # str.format），一旦可达就会印出裸 "%d"。**已删除**，不再留死代码。
    elif projection:
        # 投射档必须排在 medium 之前：两者 confidence 相同，靠 projection 区分
        tier, tmpl = "projected", (
            "{n_indep} 个独立方法组经**单位投射（class_map）**后"
            "方向一致指向 {verdict}（非原始数值共识）"
        )
    elif confidence == "medium" and n_indep >= 2:
        tier, tmpl = (
            "consistent_pred",
            "{n_indep} 个独立方法组预测一致指向 {verdict}（中位 {value} {unit}）",
        )
    elif confidence == "medium":
        tier, tmpl = (
            "single_group",
            "单一方法组内多源预测 {verdict}（中位 {value} {unit}；同组证据不叠加）",
        )
    else:
        tier, tmpl = "low_conf", "低置信预测 {verdict}（{value} {unit}，待实测确认）"

    forbidden = [
        "由 ΔG 换算 Kd/占有率",
        "推断人体剂量",
        "“证明/无毒/安全”等定论词",
        "把跨模型中位数当作校准后的概率（不同源的概率校准度不同，"
        "中位数只表达‘未校准输出的一致性’）",
    ]
    if projection:
        forbidden.append(
            "把类别投射结果写成『中位 X』或校准后概率"
            "（class_map 是人写的序数映射，不是概率输出）"
        )
        forbidden.append("把它当作来源间数值一致性的证据（来源间只有方向一致性）")
    if non_ranking:
        tmpl += "（该端点在本集合内无区分度：只能阈值判断，禁止排序）"
        forbidden.append("任何基于该端点的名次")
    if n_indep < 2:
        forbidden.append("跨源一致类表述（如“多个来源一致表明”）")
    return dict(tier=tier, template=tmpl, forbidden=forbidden)


# ---- P5（评审 v4.0，C2）：全材料"略优/略差"审计护栏 ----
# 凡无 95% CI 或配对检验支撑的比较词（"略优/略高/略差/略低/显著优于"等），
# 一律不得进入报告；命中即返回需改写的短语。报告生成时应逐句过此函数。
_SUPERIORITY_TERMS = (
    "略优",
    "略差",
    "略高",
    "略低",
    "显著优于",
    "明显优于",
    "小幅优于",
    "小幅劣于",
    "slightly better",
    "marginally better",
    "明显更好",
    "略胜一筹",
)


def flag_unqualified_superiority(text, has_ci_or_test=False):
    """返回命中未达标比较词的列表；已携带 CI/检验（has_ci_or_test=True）可豁免。

    例：'仅单位守卫 7.83% 略优' → 若无 CI 则返回 ['略优']，必须改写为
    '差异为 X（95% CI [a,b]，CI 含 0 → 未达可检测显著性）'。
    """
    if has_ci_or_test:
        return []
    return [t for t in _SUPERIORITY_TERMS if t in (text or "")]


# ---- R12（评审 A2/C2）：小样本"真值一致性"主张护栏 ----
# 背景：v4.0 材料曾用 n=2 的点对点核对写出"裁决与独立真值一致"，被评审判为
# 把 anecdote 当 validation。此类表述必须按样本量分级：
#   n < 20            → 禁"一致/符合真值/验证通过"，只准"未观察到矛盾"
#   20 ≤ n < 100      → 允许"点估计一致率 X%（95% CI [a,b]）"，禁"验证"
#   n ≥ 100 且有 CI   → 允许统计性效度陈述（仍禁"证明正确"）
_TRUTH_CLAIM_TERMS = (
    "与独立真值一致",
    "与真实值一致",
    "与真值一致",
    "真值一致性",
    "符合真值",
    "验证通过",
    "效度已验证",
    "agrees with ground truth",
    "validated against ground truth",
)

_TRUTH_CLAIM_ADVICE = {
    "blocked": "n=%s < 20：禁止任何一致性/效度主张；只能写"
    "「未观察到与已知药理矛盾（n=%s，不构成验证）」",
    "point_estimate": "n=%s ∈ [20,100)：只允许「点估计一致率 X%%（95%% CI [a,b]）」，"
    "不得写「验证」或「效度已建立」",
    "statistical": "n=%s ≥ 100：允许统计性效度陈述（须带 CI 与评价集合定义），"
    "仍禁「证明正确」",
}


def flag_truth_consistency_claim(text, n=None):
    """R12：拦截"与真值一致"类效度主张，并按 n 给出允许的替代表述。

    返回 dict(hits=[...], level=blocked/point_estimate/statistical/unknown, advice=str)
    无命中时 hits=[]、level="clean"。
    """
    hits = [t for t in _TRUTH_CLAIM_TERMS if t in (text or "")]
    if not hits:
        return dict(hits=[], level="clean", advice="")
    if n is None:
        return dict(
            hits=hits,
            level="unknown",
            advice="未声明 n：不得使用该表述；请先补 n 与 CI，或改写为"
            "「未观察到与已知药理矛盾」",
        )
    n = int(n)
    level = "blocked" if n < 20 else ("point_estimate" if n < 100 else "statistical")
    return dict(
        hits=hits,
        level=level,
        advice=(
            _TRUTH_CLAIM_ADVICE[level] % (n, n)
            if level == "blocked"
            else _TRUTH_CLAIM_ADVICE[level] % n
        ),
    )


# ---- C18 / 外审 A（2026-11-04）：会计恒等式措辞闸门 ----
# Δu(c)=a−q·c 是一阶线性会计恒等式（外审 A 独立复算 R²=0.9999995、q=0.8189）。
# 当 cost_sweep 各档 sha256(decided_mask) 全同（accounting_only=true）时，代价
# 只进入事后重标价、不进入决策；此时「c* / 无差异点 / 条件性优势区」是线性函数
# 零点的代数必然，不可证伪，禁止出现在任何对外文本。
# 本函数是 phrasing 层的统一出口；redlines.scan_report_text 通过它挂接闸门。
def flag_accounting_claims(text, accounting_only=True):
    """返回 dict(hits, advice, level)；accounting_only=False 时仍需报告证据状态。

    accounting_only 必须由产物字段给出（cost_decision.sweep_decision_masks），
    不允许由调用方凭印象设为 False 来绕过闸门。
    """
    from . import cost_decision as CD

    r = CD.forbid_accounting_claims(text, accounting_only=bool(accounting_only))
    return dict(
        hits=r["hits"],
        advice=r["advice"],
        level="blocked" if r["hits"] else "clean",
        accounting_only=bool(accounting_only),
    )


def load_source_groups(registry_path):
    """从 registry 读 {source: independence_group}；无 registry 时返回空 dict。"""
    import yaml

    if not registry_path or not os.path.exists(registry_path):
        return {}
    d = yaml.safe_load(io.open(registry_path, encoding="utf-8"))
    return {
        s["name"]: (s.get("independence_group") or None) for s in d.get("sources", [])
    }
