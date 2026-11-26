# -*- coding: utf-8 -*-
"""端点命名规范化（评估报告 P2-9）。

问题：reliab 的跨源分歧检测要求"同一物理端点同名"。v2.1 之前只有
`reliability._match_rule()` 的子串匹配兜底——`herg` 会命中任何含 "herg" 的
端点名，既可能漏检分歧（两个源写成两个名字），也可能假分歧（不同端点被并成一个）。

本模块的顺序（**C1-c / C11，2026-11-04 起：显式优先，未映射即拒绝**）：
  1) 精确匹配 rules 的 endpoint id
  2) 别名表（references/endpoint_aliases.yaml）把源列名翻成规范 id 后再匹配
  3) **不再子串兜底**：未登记名字一律返回 (None, "unmapped_endpoint")

旧第 3 步「`k.lower() in el` 子串兜底」会把 `herg_blocking_ic50_v2`、
`bbb_martins` 这类**不同 estimand 的端点名**强行并到 `herg` / `bbb` 规则上，
既漏检跨源分歧，也把不同量纲的数值混算。外审 B 判其为「规则集没覆盖被读成
规则层已判」的同源错误。保留 `allow_substring=True` 仅为历史数据迁移的显式降级
通道，调用方必须留痕且产物标 non_evidence。
"""

import io
import os

from .alerts import two_method_verdict

_HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ALIASES = os.path.join(
    os.path.dirname(_HERE), "references", "endpoint_aliases.yaml"
)
DEFAULT_RULES = os.path.join(
    os.path.dirname(_HERE), "references", "03_endpoint_rules.yaml"
)

_CACHE = {}


def load_aliases(path=None):
    """返回 {raw_name_lower: canonical}（跨源合并的反查表）。"""
    p = path or DEFAULT_ALIASES
    key = os.path.abspath(p)
    if key in _CACHE:
        return _CACHE[key]
    idx = {}
    if os.path.exists(p):
        import yaml

        d = yaml.safe_load(io.open(p, encoding="utf-8")) or {}
        for _src, blk in (d.get("sources") or {}).items():
            for sect in ("map", "reference"):
                for raw, canon in (blk.get(sect) or {}).items():
                    idx[str(raw).strip().lower()] = canon
    _CACHE[key] = idx
    return idx


def canonical_name(name, aliases=None):
    """源列名/端点名 -> 规范 id（找不到返回 None）。大小写不敏感。"""
    idx = aliases if aliases is not None else load_aliases()
    return idx.get(str(name).strip().lower())


def unit_for(endpoint, rules_path=None):
    """端点规范单位（从 03_endpoint_rules.yaml 读，**禁止在适配器里硬编码**）。

    C72：v2.3.2 把 Clearance_Microsome_AZ（µL/min/mg）沿概率端点的代码路径写进了
    unit="probability"，量纲全错。单位必须只有**一个**真源：规则表。
    """
    p = rules_path or DEFAULT_RULES
    key = ("units", os.path.abspath(p))
    if key not in _CACHE:
        m = {}
        if os.path.exists(p):
            import yaml

            d = yaml.safe_load(io.open(p, encoding="utf-8")) or {}
            for e in d.get("endpoints") or []:
                if e.get("id"):
                    m[e["id"]] = e.get("unit", "")
        _CACHE[key] = m
    return _CACHE[key].get(endpoint, "")


def load_source_map(source, path=None):
    """读某个源自己的列名映射：返回 (map, reference) 两个 {raw: canonical}。"""
    p = path or DEFAULT_ALIASES
    if not os.path.exists(p):
        return {}, {}
    import yaml

    d = yaml.safe_load(io.open(p, encoding="utf-8")) or {}
    blk = (d.get("sources") or {}).get(source) or {}
    return (blk.get("map") or {}), (blk.get("reference") or {})


def match_rule(endpoint, rules, aliases=None, allow_substring=False):
    """返回 (rule, how)。how ∈ {exact, alias, substring, unmapped_endpoint, none}。

    **C1-c / C11（2026-11-04）**：子串兜底默认禁用。未登记端点名不得静默借用
    同前缀的其它端点规则——那是把「规则集没覆盖」误读成「规则层已判」。
    `allow_substring=True` 仅用于显式标注的历史迁移，产物必须标 non_evidence。
    """
    if not rules:
        return None, "none"
    if endpoint in rules:
        return rules[endpoint], "exact"
    can = canonical_name(endpoint, aliases)
    if can and can in rules:
        return rules[can], "alias"
    if allow_substring:
        el = str(endpoint).lower()
        cands = [k for k in rules if k.lower() in el]
        if cands:
            return rules[max(cands, key=len)], "substring"
    return None, "unmapped_endpoint"


# ---- C1-c（2026-11-04）：显式别名 + 未映射审计 + 方向一致性静态校验 --------
def load_rules(path=None):
    """读 03_endpoint_rules.yaml → {id: rule}；供 audit_unmapped 使用。"""
    import yaml

    p = path or DEFAULT_RULES
    d = yaml.safe_load(io.open(p, encoding="utf-8")) or {}
    return {e["id"]: e for e in (d.get("endpoints") or []) if e.get("id")}


def validate_rule_direction(rules_path=None):
    """静态校验规则表的方向一致性；返回问题列表（空 = 通过）。

    检查四类（报告 C1-c + 外审 B N2）：
      * 重复 endpoint id（后者静默覆盖前者，是规则漂移的隐蔽来源）；
      * shape=up 必须 pass > fail；shape=down 必须 fail > pass；
      * shape=window 必须 window[0] < window[1]，且 soft 须包住 window；
      * class_map 的值域必须是 {PASS, FAIL}；类别投射与数值阈值同时出现、
        或 class_map 方向与 shape 相反，均判冲突（「单位投射冒充校准概率」）。
    """
    import yaml

    p = rules_path or DEFAULT_RULES
    d = yaml.safe_load(io.open(p, encoding="utf-8")) or {}
    problems = []
    seen = {}
    for i, e in enumerate(d.get("endpoints") or [], 1):
        eid = e.get("id")
        if not eid:
            problems.append("第 %d 条规则缺 id" % i)
            continue
        if eid in seen:
            problems.append(
                "重复端点 id %r（第 %d 与第 %d 条；后者会静默覆盖前者）"
                % (eid, seen[eid], i)
            )
        seen[eid] = i
        shape = e.get("shape")
        lo, hi = e.get("pass"), e.get("fail")
        if (
            shape in ("up", "down")
            and isinstance(lo, (int, float))
            and isinstance(hi, (int, float))
        ):
            if shape == "up" and not lo > hi:
                problems.append("%s: shape=up 但 pass(%s) <= fail(%s)" % (eid, lo, hi))
            if shape == "down" and not hi > lo:
                problems.append(
                    "%s: shape=down 但 fail(%s) <= pass(%s)" % (eid, hi, lo)
                )
        if shape == "window":
            w = e.get("window") or []
            if len(w) != 2 or not w[0] < w[1]:
                problems.append(
                    "%s: shape=window 的 window 必须 [lo, hi] 且 lo<hi" % eid
                )
            elif e.get("soft"):
                s = e["soft"]
                if len(s) == 2 and not (s[0] <= w[0] and s[1] >= w[1]):
                    problems.append("%s: soft %s 未包住 window %s" % (eid, s, w))
        cmap = e.get("class_map") or {}
        if cmap:
            bad_vals = sorted({str(v) for v in cmap.values()} - {"PASS", "FAIL"})
            if bad_vals:
                problems.append("%s: class_map 取值非法 %s" % (eid, bad_vals))
            if isinstance(lo, (int, float)) or isinstance(hi, (int, float)):
                problems.append(
                    "%s: class_map（类别投射）与数值 pass/fail 同时存在，"
                    "会把 0/1 类别冒充成校准概率" % eid
                )
            if shape in ("up", "down"):
                m1 = str(cmap.get("1", cmap.get(1, "")))
                if shape == "down" and m1 and m1 != "FAIL":
                    problems.append(
                        "%s: shape=down（越大越差）但 class_map['1']=%s" % (eid, m1)
                    )
                if shape == "up" and m1 and m1 != "PASS":
                    problems.append(
                        "%s: shape=up（越大越好）但 class_map['1']=%s" % (eid, m1)
                    )
    return _tag_acknowledged(problems)


def _load_conflict_ledger():
    """读 references/RULE_CONFLICT_LEDGER.yaml（已确认但尚未修复的规则冲突）。"""
    import yaml

    p = os.path.join(os.path.dirname(DEFAULT_RULES), "RULE_CONFLICT_LEDGER.yaml")
    if not os.path.exists(p):
        return {}
    d = yaml.safe_load(io.open(p, encoding="utf-8")) or {}
    return {str(e.get("id")): e for e in (d.get("entries") or []) if e.get("id")}


def _tag_acknowledged(problems):
    """已登记缺陷仍列出（带 [LEDGER] 前缀），但可与「新回归」机械区分。"""
    ledger = _load_conflict_ledger()
    out = []
    for x in problems:
        eid = str(x).split(":", 1)[0].strip()
        if eid in ledger and "class_map" in x:
            out.append("[LEDGER:%s] %s" % (eid, x))
        else:
            out.append(x)
    return out


def unacknowledged_rule_problems(rules_path=None):
    """返回**未在台账登记**的规则问题；CI 应断言此列表为空。

    已登记的已知缺陷由 validate_rule_direction() 原样列出（带前缀），不会因
    「登记过」就从视野里消失——这是 §7「失败可发现」的要求。本函数只回答
    「有没有新增或漏登记的冲突」。
    """
    return [
        x for x in validate_rule_direction(rules_path) if not x.startswith("[LEDGER:")
    ]


def audit_unmapped(rows, rules=None):
    """对长表逐行审计：返回未登记端点的行（供 merge 落 unmapped_endpoint_report.csv）。

    `how` 字段区分 `unmapped_endpoint`（名字未登记）与 `none`（规则表为空）。
    未映射行不得进入任何裁决、AURC/效用分母——由调用方据报告拒绝或显式降级。
    """
    rules = rules if rules is not None else load_rules()
    out = []
    for i, r in enumerate(rows, 1):
        ep = r.get("endpoint", "")
        rule, how = match_rule(ep, rules)
        if rule is None:
            out.append(
                dict(
                    row=i,
                    compound_id=r.get("compound_id", ""),
                    endpoint=ep,
                    how=how,
                    reason=("端点名未登记：禁止子串兜底借用同前缀规则（C1-c）"),
                    action=(
                        "在 references/endpoint_aliases.yaml 登记显式别名，"
                        "或在 03_endpoint_rules.yaml 定义该端点的 estimand 规则"
                    ),
                )
            )
    return out


# ---- R21（评审 R2-2）：端点三级清单 -----------------------------------------
# 评审原话："DILI 计算预测本身就是学界公认的全域外端点……为什么还要出现在默认端点
# 清单里？建议：端点清单分级为'可裁决 / 仅定性 / 不推荐计算'，DILI/Ames 直接列第三类，
# 而不是每次跑完再诚实地弃权——诚实的正确姿势是事先不承诺。"
ENDPOINT_TIER = {
    # 可裁决：有公开实测基准、跨源一致性可检验
    "herg": ("adjudicable", "TDC hERG 有实测标签；本框架 TDC 真值 6 对一致"),
    "logd": ("adjudicable", "多源可测、单位统一为 log"),
    "solubility": ("adjudicable", "logS 可测；注意 pH 依赖需声明"),
    "bbb": ("adjudicable", "分类端点，公开数据充分"),
    "pgp": ("adjudicable", "分类端点，公开数据充分"),
    "cyp1a2_inhibition": ("adjudicable", "分类端点（Veith 数据集）"),
    "cyp2c9_inhibition": ("adjudicable", "分类端点（Veith 数据集）"),
    "cyp2d6_inhibition": ("adjudicable", "分类端点（Veith 数据集）"),
    "cyp3a4_inhibition": ("adjudicable", "分类端点（Veith 数据集）"),
    # 仅定性：可算但跨实验室/跨方法方差大，只作方向判断
    "caco2_papp_ab": ("qualitative_only", "跨实验室 Papp 方差常达 1 个数量级"),
    "clint_microsome": (
        "qualitative_only",
        "HLM CLint 跨实验室差异大（C90 已排除跨源映射）",
    ),
    "ppb_fu": ("qualitative_only", "fu 测定方法依赖强（超滤/平衡透析不一致）"),
    "protox_ld50": ("qualitative_only", "LD50 外推跨度大，只作量级"),
    # 不推荐计算：计算侧全域外（公认），启用须显式承担低有效性
    "dili": (
        "not_recommended",
        "本框架实测四源四失效（14/14 阳、0/14 阳、13/14 阴、13/14 拒）",
    ),
    "carcinogenicity": (
        "not_recommended",
        "长期终点；CPDB 121 组重复实验一致率仅 57%（Gottmann 2001 EHP 109:509）",
    ),
    "nr_ar_lbd": (
        "not_recommended",
        "单测定标签噪声高（Huang 2011 EHP 119:1142；Klimenko 2020）；"
        "多测定通路模型才达 PPV 100%（Kleinstreuer 2018 Reprod Toxicol 81:272），"
        "本框架无多测定聚合能力，故仍不推荐——**不得**再表述为"
        "「与计算表征脱节」（该说法已被 PPV 100% 反驳）",
    ),
    # 仅定性（2026-11-01 改档）：ICH M7(R2) 明确允许 (Q)SAR 双方法替代细菌回复突变试验，
    # 但要求「专家规则 + 统计」互补。本框架提供 `adt/alerts.py` 专家规则层，
    # 并由 `reliab --enable-alerts`（默认开）在管线内调用它做 ICH M7 双方法合成；
    # 判定须走 `adt/alerts.two_method_verdict()`（统计结论 × 结构警示命中），且禁止推导任何限量数值
    # （详见 references/ENDPOINT_TIER_EVIDENCE.md §5）。
    # 注意（v4.4 关键澄清）：**未启用专家规则层时 ames 仍维持 UNDETERMINED**——
    # 即若 `reliab` 未传 --enable-alerts 或找不到 compounds.csv（无 SMILES 可扫），
    # 则统计结论再充分也不出二值结论（ICH M7：两法中任一缺失不得判 Class 5）。
    # v4.3 曾把 TDC 基准上的放行错误率 0.269→0.177 写成"已补专家规则层"，
    # 但彼时该层并未接入生产管线——这是文档声称与实际行为脱节的教训，v4.4 已补齐接线。
    "ames": (
        "qualitative_only",
        "ICH M7(R2) §6 允许双 (Q)SAR 替代 Ames；reliab --enable-alerts 调用 adt/alerts.py "
        "做双方法合成后满足双方法要求，但只许出方向（Class 5 方向 / 需复核），禁止限量",
    ),
    # ---- v4.15–v4.20 新增端点（全部 role=reference，这里登记分级是为了 tier 表完整）----
    "cardiac_herg_ic50": (
        "qualitative_only",
        "IC50 单独无意义：须与 Cmax,u 算裕度；且无 ORd 不能判净效应",
    ),
    "cardiac_cav12_ic50": ("qualitative_only", "需与 hERG/Nav1.5 并列读，单通道不可判"),
    "cardiac_nav15_ic50": ("qualitative_only", "同上；峰钠流 IC50 不能代替晚钠流"),
    "cardiac_herg_inh_pct": ("qualitative_only", "单一浓度点抑制率，非全曲线"),
    "cardiac_cav12_inh_pct": ("qualitative_only", "同上"),
    "cardiac_nav15_inh_pct": ("qualitative_only", "同上"),
    "pgp_substrate": (
        "qualitative_only",
        "目前唯一可批量取的源是 SwissADME 回填；方向依赖适应症"
        "（CNS 要避底物，系统暴露要低外排），单源不得下判决",
    ),
    "bbb_permeant": ("qualitative_only", "类别判据，与 bbb 概率端点不同量纲，不可混算"),
    "hia_absorption": ("qualitative_only", "High/Low 类别，与 hia 概率不同量纲"),
    "microbiome_metabolite_count": (
        "qualitative_only",
        "规则引擎计数；0 不可读作'无代谢'（须先过阳性对照）",
    ),
}


def endpoint_tier(name):
    key = canonical_name(name) or str(name).lower()
    return ENDPOINT_TIER.get(
        key, ("adjudicable", "未登记，按可裁决处理（须在报告中声明）")
    )


def tier_table():
    return [
        {"endpoint": k, "tier": v[0], "reason": v[1]}
        for k, v in sorted(ENDPOINT_TIER.items())
    ]


# 需要"专家规则 + 统计"双方法的定性端点（ICH M7 口径）。
# 若记录里没有 `expert_rule_layer=True`（即结构警示层未参与），不得给出二值结论。
QUALITATIVE_NEEDS_EXPERT = {"ames"}
QUALITATIVE_MIN_SOURCES = 2


def apply_tier_policy(recs, accept_low_validity=False, alert_cache=None):
    """R21/R37：不推荐计算的端点默认降为 UNDETERMINED，除非显式 --i-accept-low-validity。

    v4.3 新增 `qualitative_only` 的**可执行约束**（此前它只是个标签、没有任何行为差异）：
      · 至少 2 个独立源（单方法不得出二值结论）；
      · `QUALITATIVE_NEEDS_EXPERT` 里的端点还要求 `expert_rule_layer=True`
        （ICH M7 要求专家规则 + 统计互补，三个统计模型不构成"两种互补方法"）；
      · 放行的判定打 `qualitative=True` 与禁止限量说明。

    返回 (recs, log)；log 逐条记录被拦下的判定，供留痕归档。
    """
    log = []
    for r in recs:
        tier, reason = endpoint_tier(r.get("endpoint", ""))
        if tier == "not_recommended" and not accept_low_validity:
            if r.get("verdict") in ("PASS", "FAIL"):
                log.append(
                    {
                        "compound_id": r.get("compound_id"),
                        "endpoint": r.get("endpoint"),
                        "original_verdict": r.get("verdict"),
                        "new_verdict": "UNDETERMINED",
                        "reason": "endpoint_not_recommended: " + reason,
                    }
                )
                r["verdict"] = "UNDETERMINED"
                r["reason"] = (r.get("reason") or "") + " | endpoint_not_recommended"
                r["action"] = (
                    "该端点计算不推荐；如确需使用请加 --i-accept-low-validity 并留痕"
                )
            continue
        if tier == "qualitative_only" and r.get("verdict") in ("PASS", "FAIL"):
            srcs = {
                s.strip() for s in str(r.get("sources") or "").split(";") if s.strip()
            }
            need_expert = (
                canonical_name(r.get("endpoint", ""))
                or str(r.get("endpoint", "")).lower()
            ) in QUALITATIVE_NEEDS_EXPERT
            if len(srcs) < QUALITATIVE_MIN_SOURCES:
                why = "qualitative_requires_two_methods: 仅 %d 个源，定性端点须 ≥%d" % (
                    len(srcs),
                    QUALITATIVE_MIN_SOURCES,
                )
            elif need_expert and not r.get("expert_rule_layer"):
                why = (
                    "qualitative_requires_expert_rules: ICH M7 要求专家规则+统计互补，"
                    "本记录未启用结构警示层（adt/alerts.py）"
                )
            else:
                why = None
            if why:
                log.append(
                    {
                        "compound_id": r.get("compound_id"),
                        "endpoint": r.get("endpoint"),
                        "original_verdict": r.get("verdict"),
                        "new_verdict": "UNDETERMINED",
                        "reason": "endpoint_qualitative_only: " + why,
                    }
                )
                r["verdict"] = "UNDETERMINED"
                r["reason"] = (r.get("reason") or "") + " | " + why.split(":")[0]
                r["action"] = (
                    "定性端点：补齐第二种互补方法后再出结论；" "禁止取平均/多数票绕过"
                )
                continue
            r["qualitative"] = True
            r["tier_note"] = (
                "qualitative_only：只可作方向判断（有无致突变关注），"
                "不得据此推导限量/概率阈值/剂量"
            )
            # ICH M7 双方法合成（v4.4 接入 adt/alerts.py 专家规则层）。
            # 仅当该端点要求 expert 层且记录已标记 expert_rule_layer=True（由 reliab
            # --enable-alerts 调用 alerts.py 扫描 SMILES 后设置）时才进入；
            # 否则已在上面的 `elif need_expert and not expert_rule_layer` 分支降为 UNDETERMINED。
            if need_expert and r.get("expert_rule_layer"):
                alert_hit = bool((alert_cache or {}).get(r["compound_id"], False))
                combined, cwhy = two_method_verdict(
                    r["verdict"], alert_hit, in_domain=True
                )
                r["verdict"] = combined
                r["alert_hit"] = "Y" if alert_hit else "N"
                r["reason"] = (r.get("reason") or "") + " | ich_m7_two_method:" + cwhy
    return recs, log
