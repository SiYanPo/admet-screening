# -*- coding: utf-8 -*-
"""s5：可靠性裁决（共识 + 弃权 + 三态输出）。

输入是长表（多个源、多个端点），输出每个 分子×端点 的判定：
    PASS / FAIL / UNDETERMINED      —— 只有这三种，禁止输出"综合分 0.73"这种话

裁决顺序（顺序不能调）：
  1) 有实测 -> 实测优先，阈值判定，confidence=high
  2) 域内源数 = 0 -> UNDETERMINED（所有源都拒绝/越界）
  3) 域内源之间分歧超阈值 -> UNDETERMINED（**不取平均**）
  4) 域内源数 = 1 且该端点要求 >=2 源 -> UNDETERMINED（单源）
  5) 否则按阈值判定；端点若在"集合内无区分度"名单里，
     阈值判定仍有效但 confidence=low 且 明确写"不能排序"

为什么"分歧不取平均"：本项目 DILI 上四个源给出四种失效
（ADMETlab 14/14 阳 0.643-0.914、ADMET-AI 0/14 阳 0.226-0.322、
ProTox 13/14 阴、vNN 13/14 拒绝预测），取平均会把"四个都不可用"变成一个看似中性的数。
"""

import math

PROB_SPREAD_MAX = 0.30  # 概率类端点：极差 > 0.30 判分歧
# 原来设 0.5，实测放过了一个真实分歧：hERG 三个源给 0.014 / 0.409 / 0，
# 极差 0.369 < 0.5 被判"一致"，还取了均值 0.139 —— 30 倍差异不能算一致。
RATIO_SPREAD_MAX = 3.0  # 连续类端点：max/min > 3 判分歧

# P1（评审 v4.0，C1/C10 致命修复）第七类归因：源间 ρ<0（方向/语义冲突）。
# 当某端点存在 source_conflict（Fisher z 95%CI 下界 < 0 或点估计 < 0）时，
# 该端点默认 UNDETERMINED，reason=SOURCE_CONFLICT_REASON，action 指向第三源/实测仲裁。
# 触发逻辑由 independence.rho_contraction_weight 经 source_rho 的逐端点 ρ/CI 喂入（数据依赖，见 P1）。
SOURCE_CONFLICT_REASON = "source_conflict"

# C63（写回 saturated 时发现）：`saturated` 必须仍然算"域内有值"——
# 它的语义是"不能排序、但绝对阈值仍有效"。若把它排除在 in_domain 之外，
# 就会把"14 个全报红旗"这种正确结论退化成"全部源域外"。
IN_DOMAIN_FLAGS = {"predicted", "measured", "saturated"}


def _f(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _match_rule(endpoint, rules, aliases=None, log=None):
    """端点 -> 规则。顺序：精确 > 显式别名表 > **拒绝**（C1-c / C11）。

    旧的子串兜底会把 `herg` 匹配到任何含 herg 的端点名（如
    `herg_blocking_ic50_v2`），把不同 estimand 的数值并到同一规则上。
    2026-11-04 起默认禁用；log 现在记录的是**未登记端点**，调用方须据此
    拒绝裁决或在别名表补显式登记，而不是统计"靠兜底救回来多少行"。
    """
    from .endpoints import match_rule

    rule, how = match_rule(endpoint, rules, aliases)
    if how in ("unmapped_endpoint", "substring") and log is not None:
        log.append(endpoint)
    return rule


def _median(vals):
    s = sorted(vals)
    n = len(s)
    if n == 0:
        return None
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def _judge(value, rule):
    """按阈值判 PASS/FAIL；没有规则返回 None。"""
    if rule is None or value is None:
        return None
    shape = rule.get("shape", "down")
    p, f = rule.get("pass"), rule.get("fail")
    if shape == "up":
        if p is not None and value >= p:
            return "PASS"
        if f is not None and value < f:
            return "FAIL"
        return None  # 灰区：交给调用方标 UNDETERMINED 并写 action
    if shape == "down":
        if p is not None and value <= p:
            return "PASS"
        if f is not None and value > f:
            return "FAIL"
        return None  # 灰区
    if shape == "step":
        if f is not None and value > f:
            return "FAIL"
        return "PASS"
    if shape == "window":
        lo, hi = rule.get("window", [-1, 3])
        return "PASS" if lo <= value <= hi else "FAIL"
    return None


def apply_class_blocks(rows, registry, chemical_class):
    """把 registry 里登记的"本化学类域外端点"真正落到数据上（C82）。

    C82（2026-10-29 复核）：`blocked_endpoints_in_class` 在 registry 里登记得很完整
    （ADMETlab 的 DILI 14/14 0.643–0.914、Ames 14/14 0.830–0.990 等），
    但**没有任何代码读取它**——于是这些"整类全阳、无区分度"的源仍在参与裁决，
    把 DILI/Ames 污染成"源间分歧"，而不是正确的"域外"。

    返回 (rows, detail)：detail = [{source, endpoint, n, evidence}]。
    """
    from .endpoints import canonical_name

    classes = (registry or {}).get("chemical_classes") or {}
    # 本类的 blocked 列表在两处：sources[].blocked_endpoints_in_class[cls]
    #                          与 chemical_classes[cls].blocked_endpoints
    blocked = {}
    for src in (registry or {}).get("sources") or []:
        name = src.get("name", "")
        for item in (src.get("blocked_endpoints_in_class") or {}).get(
            chemical_class
        ) or []:
            ep = (
                canonical_name(item.get("endpoint", ""))
                or str(item.get("endpoint", "")).lower()
            )
            blocked[(name, ep)] = item.get("evidence", "")
    for item in (classes.get(chemical_class) or {}).get("blocked_endpoints") or []:
        raw = str(item)
        if ":" in raw:  # 形如 "admetlab3.DILI"
            src, ep = raw.split(":", 1)
        elif "." in raw:
            src, ep = raw.split(".", 1)
        else:
            continue
        blocked[(src.strip(), canonical_name(ep) or ep.strip().lower())] = (
            "chemical_classes 登记"
        )

    if not blocked:
        return rows, []

    detail = {}
    out = []
    for r in rows:
        key = (r.get("source", ""), r.get("endpoint", ""))
        if key in blocked:
            r = dict(r)
            r["domain_flag"] = "out_of_domain"
            note = (r.get("note") or "").strip()
            r["note"] = (
                note
                + " | 该源在本化学类此端点无区分度（registry blocked：%s）"
                % (blocked[key] or "未给证据")
            ).strip(" |")
            d = detail.setdefault(
                key, dict(source=key[0], endpoint=key[1], n=0, evidence=blocked[key])
            )
            d["n"] += 1
        out.append(r)
    return out, sorted(detail.values(), key=lambda x: (x["source"], x["endpoint"]))


def in_phys_range(value, rule):
    """数值是否落在端点声明的物理边界内（无声明则视为通过）。

    C80：模型会输出物理不可能值（ADMET-AI 的 CLint 在 APAP 上给 −4.3）。
    裁决层与下游计算（PBPK/暴露估计）必须共用同一个判定，避免"裁决挡掉、
    下游照用"的两套标准。
    """
    if value is None or not rule:
        return True
    rng = rule.get("phys_range")
    if not rng or len(rng) != 2:
        return True
    try:
        return float(rng[0]) <= float(value) <= float(rng[1])
    except (TypeError, ValueError):
        return True


def evaluate(
    measurements,
    rules=None,
    non_ranking=None,
    saturated=None,
    source_groups=None,
    match_log=None,
):
    """返回判定列表。measurements: list[dict]（长表行）。

    source_groups: {source_name: independence_group}。同组多源同向只记 1 独立票
    （"两票半"原则：ADMETlab 与 ADMET-AI 共享描述符-ML 训练生态，不能算 2 个独立证据）。
    None 时退回"每源一票"的旧行为（向后兼容，旧测试不改）。
    match_log: 传入 list 时，把**未登记端点**（how="unmapped_endpoint"）追加进去
    （C1-c 留痕；这些行不得进入裁决，须补显式别名后重跑）。
    """
    non_ranking = non_ranking or set()
    saturated = saturated or set()
    rules = rules or {}
    source_groups = source_groups or {}

    groups = {}
    for r in measurements:
        key = (r["compound_id"], r["endpoint"])
        groups.setdefault(key, []).append(r)

    out = []
    for (cid, ep), rows in sorted(groups.items()):
        vals_all = [(r, _f(r.get("value"))) for r in rows]
        in_dom = [
            (r, v)
            for r, v in vals_all
            if r.get("domain_flag") in IN_DOMAIN_FLAGS and v is not None
        ]
        rule = _match_rule(ep, rules, log=match_log)
        # C80（2026-10-29 实测）：模型可能输出**物理不可能值**——ADMET-AI 的
        # Clearance_Microsome_AZ 在 APAP 上给 −4.3、甘氨酸 −31.4（负清除率）。
        # 这类值不是"低"，是"无效"，必须挡在裁决之外，否则会算出 Fh=1.0 之类的假象。
        phys = (rule or {}).get("phys_range")
        n_phys_bad = 0
        if phys and len(phys) == 2:
            lo, hi = float(phys[0]), float(phys[1])
            keep = []
            for r, v in in_dom:
                if lo <= v <= hi:
                    keep.append((r, v))
                else:
                    n_phys_bad += 1
            in_dom = keep
        # v3.6.1 修复（2026-10-30，OneADMET 实测暴露）：phys_range 此前只过滤 in_dom，
        # `measured` 在过滤之前构建，导致**实测路径绕过物理边界守卫**——OpenADMET raw 的
        # MLM CLint 10,354 µL/min/mg（phys 上限 5000）被直接判 FAIL 而不是按无效值弃权。
        # C80 的意图是"物理不可能值一律无效"，不分实测/预测。现改为
        # measured ⊆ phys 过滤后的 in_dom：越界的实测值同样挡在裁决之外，
        # 若某 (cid,ep) 的全部值越界 → 走"全部越物理边界"域外分支（可被 transfer 检验）。
        measured = [(r, v) for r, v in in_dom if r.get("domain_flag") == "measured"]
        n_total = len(rows)
        srcs = sorted({r.get("source", "") for r in rows})
        role = (rule or {}).get("role", "quality")
        if role in ("applicability", "reference"):
            # 参照/适用域端点：只透传，不裁决、不进轴聚合（v2.1，试点暴露的
            # 问题：chembl 参照分位被当质量端点裁决，每分子刷屏且稀释覆盖率）
            out.append(
                dict(
                    compound_id=cid,
                    endpoint=ep,
                    n_total=len(rows),
                    n_in_domain=0,
                    n_measured=0,
                    sources=";".join(srcs),
                    n_indep_groups=0,
                    indep_groups="",
                    value_used="",
                    unit="",
                    spread="",
                    verdict="PASSTHRU",
                    confidence="",
                    reason="role=%s 端点：不裁决" % role,
                    action="",
                    allowed_statement="（适用域/真值参照数据，直接引用数值）",
                )
            )
            continue
        # C77（v2.3.5）：默认必须是 **2 个独立方法组**——文档写的是"两票半"原则，
        # 原实现默认 1，导致未显式声明 require_sources 的端点（nr_ar_lbd/sr_p53/sr_are 等）
        # 仅凭单组就被判 PASS/FAIL，与"单组不下判决"的严化口径自相矛盾。
        # 确需单组可判的端点，必须在规则里显式写 require_sources: 1。
        need = int((rule or {}).get("require_sources", 2))

        # 独立方法组计数：同组多源合并为 1 票
        indep = sorted(
            {
                source_groups.get(r.get("source", ""), r.get("source", ""))
                or r.get("source", "")
                for r, _ in in_dom
            }
        )
        n_indep = len(indep)

        rec = dict(
            compound_id=cid,
            endpoint=ep,
            n_total=n_total,
            n_in_domain=len(in_dom),
            n_measured=len(measured),
            sources=";".join(srcs),
            value_used="",
            unit="",
            spread="",
            verdict="UNDETERMINED",
            confidence="low",
            reason="",
            action="",
            n_indep_groups=n_indep,
            indep_groups=";".join(indep),
        )

        # 1) 实测优先
        # C59（评估 P3-19）：多个实测源时原实现直接取第一条（measured[0]），
        # 对"两个实验室结论冲突"视而不见。现取中位数并把冲突写进 reason。
        if measured:
            r0 = measured[0][0]
            vals = [v for _, v in measured]
            v0 = _median(vals) if len(vals) > 1 else vals[0]
            clash = (
                len(vals) > 1
                and (max(vals) - min(vals)) > 0
                and len({round(v, 6) for v in vals}) > 1
            )
            rec.update(
                value_used=round(v0, 4), unit=r0.get("unit", ""), confidence="high"
            )
            vd = _judge(v0, rule)
            rec["verdict"] = vd or "UNDETERMINED"
            rec["reason"] = ("有实测值（n=%d）" % len(vals)) + (
                "；多实测值不一致（极差 %.3f），按中位数取值" % (max(vals) - min(vals))
                if clash
                else ""
            )
            if vd is None:
                rec["action"] = (
                    "实测值落在关注带或该端点无阈值规则——"
                    "按 04_decision_funnel §5 补实验/加同向源，"
                    "不得用方向词"
                )
            out.append(rec)
            continue

        # 2) 全部域外 / 全部越物理边界
        if not in_dom:
            if n_phys_bad:
                lo, hi = float(phys[0]), float(phys[1])
                rec["reason"] = (
                    "全部 %d 个值越物理边界（允许 %g~%g）：模型输出不可信"
                    % (n_phys_bad, lo, hi)
                )
                rec["action"] = "换源或补实测；越界值不得换算/不得用于 PBPK 等下游计算"
            else:
                flags = sorted({r.get("domain_flag") for r in rows})
                rec["reason"] = "全部源域外/失效（flags=%s）" % ",".join(flags)
                rec["action"] = "换源或补实测；不得在此端点下结论"
            out.append(rec)
            continue

        # 2.5) 单位不一致 → 不取中位数（C78）
        # 实测发现：hERG 上 vNN 给的是**类别 0/1**、ADMET-AI 给的是**概率**，
        # 直接算中位数会把"没有心脏风险(0)"当成"概率 0"，本地版数值偏低时
        # 恰好躲过 spread 守卫，于是产出一个假的 PASS。
        # 类别与概率不可换算 —— 遇到异构单位只能不判。
        units = {str(r.get("unit", "")).strip().lower() for r, _ in in_dom}
        units.discard("")
        mixed_units = len(units) > 1
        proj = None
        if mixed_units:
            # 异构单位（如 class 0/1 + probability）：**不算中位数**，改为逐源投射到
            # 规则的序数尺度再比方向。类别必须靠 rule["class_map"] 投射，
            # 否则"类别 1"会被当成"概率 1.0"、或"类别 0"被当成"概率 0"（方向都对不上）。
            cmap = (rule or {}).get("class_map") or {}
            proj = []
            for r, v in in_dom:
                u = str(r.get("unit", "")).strip().lower()
                if u == "class":
                    proj.append(cmap.get(str(int(round(v)))))
                else:
                    proj.append(_judge(v, rule))
            if not cmap:
                rec["reason"] = "跨源单位不一致（%s）且规则无 class_map" % "/".join(
                    sorted(units)
                )
                rec["action"] = "在规则里补 class_map（类别→PASS/FAIL）后再判"
                out.append(rec)
                continue
            if any(x is None for x in proj):
                rec["reason"] = "跨源单位不一致（%s）且至少一个源落在灰区：%s" % (
                    "/".join(sorted(units)),
                    proj,
                )
                rec["action"] = "补概率输出或补实测；当前只能作定性参照"
                out.append(rec)
                continue
            if len(set(proj)) > 1:
                rec["reason"] = "跨源单位不一致（%s）且方向相反：%s" % (
                    "/".join(sorted(units)),
                    proj,
                )
                rec["action"] = "逐源复核适用域；禁止取平均或多数票"
                out.append(rec)
                continue
            # 投射后方向一致。**但独立组门控必须照常生效**：
            # v3.0.0 实测（AD 阈值摄动时暴露）：本分支此前直接落 PASS 并 continue，
            # 绕过了下面第 4 步的 `n_indep < need` 检查——把 require_sources 调成 3
            # MMP 仍判 PASS，等于"两票半"原则在异构单位端点上完全失效。
            if n_indep < max(1, need):
                rec["value_used"] = in_dom[0][1]
                rec["unit"] = in_dom[0][0].get("unit", "")
                rec["reason"] = (
                    "单位异构（%s）按类别映射后方向一致（%s），"
                    "但独立方法组仅 %d 个 < 要求的 %d"
                    % ("/".join(sorted(units)), proj, n_indep, max(1, need))
                )
                rec["action"] = "再找一个方法学独立的源，或补实测（同族源不叠加证据）"
                out.append(rec)
                continue
            rec["verdict"] = proj[0]
            same = [
                v
                for (r, v) in in_dom
                if str(r.get("unit", "")).strip().lower() == "probability"
            ]
            if same:
                rec["value_used"] = round(_median(same), 4)
                rec["unit"] = "probability"
            rec["confidence"] = "medium" if n_indep >= 2 else "low"
            # C9（2026-11-03 评审）：投射路径此前与"同构中位数"路径共享同一置信度档，
            # 产物里看不出"这个 verdict 来自类别→PASS/FAIL 的人工映射，而不是原始数值共识"。
            # 现显式打标，并由 phrasing 走独立措辞档（不得写成"中位 X"）。
            rec["projection_used"] = True
            rec["reason"] = (
                "%d 个域内源（%d 个独立方法组），单位异构（%s）"
                "按 class_map 类别投射后方向一致：%s（**投射结果，非原始数值共识**）"
                % (len(in_dom), n_indep, "/".join(sorted(units)), proj)
            )
            out.append(rec)
            continue

        # 3) 分歧
        vv = [v for _, v in in_dom]
        lo, hi = min(vv), max(vv)
        is_prob = all(0.0 <= x <= 1.0 for x in vv)
        if is_prob:
            spread = hi - lo
            disagree = spread > PROB_SPREAD_MAX
        else:
            mid = abs(sum(vv) / len(vv))
            spread = (hi - lo) / mid if mid > 1e-9 else float("inf")
            disagree = spread > RATIO_SPREAD_MAX
        rec["spread"] = round(spread, 3)
        if len(vv) >= 2 and disagree:
            rec["reason"] = "源间分歧过大（%s=%s）" % (
                "极差" if is_prob else "相对极差",
                rec["spread"],
            )
            rec["action"] = "逐源复核适用域；必要时补实测，禁止取平均"
            out.append(rec)
            continue

        # 4) 独立组不足（"要求 2 源"的语义收紧为"2 个独立方法组"）
        if n_indep < max(1, need):
            rec["value_used"] = in_dom[0][1]
            rec["unit"] = in_dom[0][0].get("unit", "")
            rec["reason"] = "域内源 %d 个但独立方法组仅 %d 个 < 要求的 %d" % (
                len(in_dom),
                n_indep,
                max(1, need),
            )
            if n_phys_bad:
                rec["reason"] += "；另有 %d 个值越物理边界已剔除" % n_phys_bad
            rec["action"] = "再找一个方法学独立的源，或补实测（同族源不叠加证据）"
            out.append(rec)
            continue

        # 5) 阈值判定（用中位数而非均值：源数少时均值会被单源极值拉走）
        val = _median(vv)
        rec["value_used"] = round(val, 4)
        rec["unit"] = in_dom[0][0].get("unit", "")
        vd = _judge(val, rule)
        rec["verdict"] = vd or "UNDETERMINED"
        rec["confidence"] = "medium" if n_indep >= 2 else "low"
        rec["reason"] = "%d 个域内源（%d 个独立方法组）一致（中位数）" % (
            len(vv),
            n_indep,
        )
        if n_phys_bad:
            rec["reason"] += "；另有 %d 个值越物理边界已剔除" % n_phys_bad
        flagged_sat = any(r.get("domain_flag") == "saturated" for r, _ in in_dom)
        if ep in non_ranking or ep in saturated or flagged_sat:
            rec["confidence"] = "low"
            rec["reason"] += "；该端点在本集合内无区分度，**只能按阈值判、不能排序**"
        if vd is None:
            if rule is None:
                rec["action"] = "该端点无阈值规则，仅报告数值"
            else:
                rec["action"] = (
                    "值 %.3f 落在关注带（pass=%s / fail=%s），"
                    "不足以判 PASS/FAIL；需实测或增加同向源"
                    % (val, rule.get("pass"), rule.get("fail"))
                )
        out.append(rec)
    # 深水区 2.2：BBB 双层机制激活——BBB 端点 UNDETERMINED 强制指向 P-gp 底物评估
    # C2（2026-11-03 评审）：原先 `except Exception: pass` 会把"会改写 verdict 的
    # 决策层失败"静默吞掉——用户拿到的是一个**看起来正常、实际少了 BBB 机制**的
    # 裁决表，且日志里没有任何痕迹。这与红线精神（不静默放行）直接矛盾。
    # 现改为：失败必须留痕（bbb_layer 列）+ 置信度降级，绝不静默。
    try:
        from . import bbb as _bbb

        out = _bbb.postprocess(out)
    except Exception as _exc:  # noqa: BLE001（必须捕获，但要留痕）
        _why = type(_exc).__name__
        for _r in out:
            _r["bbb_mechanism"] = "layer_failed:%s" % _why
            _r["reason"] = (
                "%s；BBB 双层机制未运行（%s），本行 BBB 相关 action 缺失"
                % (_r.get("reason", ""), _why)
            ).strip("；")
            if _r.get("confidence") in ("high", "medium"):
                _r["confidence"] = "low"
    return out


def can_rank(n_compounds, max_cluster_frac, max_spread):
    """排名三条件（本项目 MPO Spearman=0.024 的反例催生）。

    返回 (ok, reasons)。三者必须同时满足。
    """
    reasons = []
    if n_compounds < 30:
        reasons.append("候选数 %d < 30" % n_compounds)
    if max_cluster_frac >= 0.30:
        reasons.append("最大同类簇占比 %.0f%% >= 30%%" % (max_cluster_frac * 100))
    if max_spread is not None and max_spread > PROB_SPREAD_MAX:
        reasons.append("跨源极差 %.2f 过大" % max_spread)
    return (not reasons), reasons


def summarize(recs):
    """按 verdict 计数，便于报告里一句话引用。"""
    c = {"PASS": 0, "FAIL": 0, "UNDETERMINED": 0}
    for r in recs:
        c[r["verdict"]] = c.get(r["verdict"], 0) + 1
    return c
