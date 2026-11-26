# -*- coding: utf-8 -*-
"""模块N：UNDETERMINED 的结构化弃权归因（把"一个状态"升级为"一个带归因的诊断"）。

外部评审（2026-10-30）原话：
  "当一个分子×端点被判 UNDETERMINED 时，当前的 action 告诉你'补哪个实验'，但没有
   告诉你**为什么**这个源在这个分子上不可信。是分子落在训练集化学空间之外？是源在该
   化学类上饱和了？是单位异构导致无法比较？这三种原因对应完全不同的信息获取策略，
   但在当前的 action 文本中被压缩成一个笼统的'补实验'。"

本模块只做**归因（attribution）**，不改变 verdict。归因类别：
  domain_block                 全部可用源在本化学类域外/失效
  phys_range_violation         值越出端点物理边界（模型输出无效，不是"低"）
  unit_isomerism               跨源单位不一致且无可投射 class_map
  insufficient_independent_groups  域内源够但独立方法组 < 门槛
  spread_exceeded              源间分歧过大（极差/相对极差超阈）
  saturation                   端点饱和（源在该子空间输出贴边）
  no_rule                      端点无阈值规则（role=non_ranking 或 MISSING）
  insufficient_sources         域内源数量本身不足
  other                        未归入以上

设计原则：
  - 归因是**可多重**的（一条记录可能同时单位异构 + 分歧过大），主归因按"最接近
    决策瓶颈"的优先级取一个，其余进 secondary。
  - 顺序即优先级：域外 > 物理无效 > 单位异构 > 独立组不足 > 分歧过大 > 饱和 > 无规则 > 源不足。
  - 不臆造 kNN Tanimoto：源训练集结构不在本包内。若外部提供
    `--source-structures`（source,smiles 两列），可选做最近邻相似度归因。
"""

import csv
import io
import os

ORDER = [
    "domain_block",
    "phys_range_violation",
    "unit_isomerism",
    "insufficient_independent_groups",
    "spread_exceeded",
    "saturation",
    "no_rule",
    "insufficient_sources",
    "other",
]

# ---------------------------------------------------------------------------
# 归因分类体系的**唯一真源**（C7，2026-11-03 评审）
#
# 此前 SKILL.md 两处写"六类归因（F13）"，而代码里 ORDER 已有 8 类（+ other），
# independence.py 又把 rho<0 的 source_conflict 称作"第七类归因"——
# 三个数字互不相容。根因是**没有单一真源**，数字靠人记。
#
# 现固定为两个命名空间，SKILL.md 只允许引用本常量（并有测试断言数量）：
#   弃权归因（为什么判不了）  ABSTAIN_ORDER  —— 8 类 + other
#   源可靠性归因（凭什么是同一份证据） SOURCE_RELIABILITY_REASONS —— 1 类
# 两者不可互相编号，避免再次出现"第六/第七类"这种跨命名空间计数。
ABSTAIN_ORDER = list(ORDER)
ABSTAIN_SUBSTANTIVE = [k for k in ORDER if k != "other"]  # other 是兜底，不计入类数
SOURCE_RELIABILITY_REASONS = ["source_conflict"]
TAXONOMY = dict(
    abstain_all=ABSTAIN_ORDER,
    abstain=ABSTAIN_SUBSTANTIVE,
    catch_all=["other"],
    source_reliability=SOURCE_RELIABILITY_REASONS,
    total=len(ABSTAIN_SUBSTANTIVE) + len(SOURCE_RELIABILITY_REASONS),
    sentence="九类归因：弃权归因 %d 类 + 源可靠性归因 %d 类（source_conflict）；"
    "`other` 为兜底，不计入类数"
    % (len(ABSTAIN_SUBSTANTIVE), len(SOURCE_RELIABILITY_REASONS)),
)

_LABEL = {
    "domain_block": "域外阻断：全部可用源在本化学类无资格",
    "phys_range_violation": "物理越界：模型输出不可能值，须换源或湿实验",
    "unit_isomerism": "单位异构：跨源口径不可比且缺 class_map",
    "insufficient_independent_groups": "独立方法组不足：同生态多源只算一票",
    "spread_exceeded": "源间分歧过大：方向不一致，须补实验或第三源",
    "saturation": "端点饱和：源在该子空间贴边输出",
    "no_rule": "无阈值规则：端点未定义可判 PASS/FAIL 的阈值",
    "insufficient_sources": "域内源数量不足",
    "other": "未归类（需人工看 reason 原文）",
}

_RESOLUTION = {
    "domain_block": "换一个有该化学类训练覆盖的源，或直接湿实验；补同源更多分子无效",
    "phys_range_violation": "换源/换版本；该源在此端点不可用",
    "unit_isomerism": "统一单位或补 class_map 后重跑（低成本，优先）",
    "insufficient_independent_groups": "补一个**独立生态**的源（不是同一训练生态的镜像）",
    "spread_exceeded": "补一个独立源或做一次确认性实测；不要用中位数强行裁决",
    "saturation": "改用非饱和端点/更高上限的源；该端点在此子空间无信息",
    "no_rule": "先定义阈值（分析选择，须声明），否则该端点只能做参照",
    "insufficient_sources": "补源，或把该端点降级为参照",
    "other": "人工审阅 reason 字段",
}


def _f(v):
    try:
        x = float(v)
        return x if x == x and abs(x) != float("inf") else None
    except (TypeError, ValueError):
        return None


def attribute(rec):
    """返回 (primary, secondary_list)。"""
    reason = rec.get("reason") or ""
    verdict = (rec.get("verdict") or "").upper()
    n_total = int(_f(rec.get("n_total")) or 0)
    n_dom = int(_f(rec.get("n_in_domain")) or 0)
    n_indep = int(_f(rec.get("n_indep_groups")) or 0)
    spread = _f(rec.get("spread"))
    tags = []

    if n_dom == 0 and n_total > 0:
        tags.append("domain_block")
    if "越物理边界" in reason or "物理边界" in reason:
        tags.append("phys_range_violation")
    if "单位异构" in reason or "单位不一致" in reason:
        tags.append("unit_isomerism")
    if "独立方法组仅" in reason or "独立组" in reason:
        tags.append("insufficient_independent_groups")
    if "分歧过大" in reason:
        tags.append("spread_exceeded")
    if "饱和" in reason:
        tags.append("saturation")
    if "无阈值规则" in reason or "不裁决" in reason:
        tags.append("no_rule")
    if n_dom > 0 and n_dom < 2 and "源" in reason and not tags:
        tags.append("insufficient_sources")
    # spread 字段本身也作为证据（reason 文本可能没写）
    if (
        spread is not None
        and spread > 0.30
        and "spread_exceeded" not in tags
        and verdict == "UNDETERMINED"
    ):
        tags.append("spread_exceeded")
    if not tags:
        tags.append("other")
    prim = min(tags, key=lambda t: ORDER.index(t))
    sec = [t for t in tags if t != prim]
    return prim, sec


def annotate(recs):
    """就地给每条记录加 abstention_reason_attribution / *_label / *_resolution / *_secondary。"""
    for r in recs:
        if (r.get("verdict") or "").upper() != "UNDETERMINED":
            r["abstention_reason_attribution"] = ""
            r["abstention_reason_label"] = ""
            r["abstention_resolution"] = ""
            r["abstention_reason_secondary"] = ""
            continue
        prim, sec = attribute(r)
        r["abstention_reason_attribution"] = prim
        r["abstention_reason_label"] = _LABEL.get(prim, prim)
        r["abstention_resolution"] = _RESOLUTION.get(prim, "")
        r["abstention_reason_secondary"] = ";".join(sec)
    return recs


def distribution(recs, by="primary"):
    """统计归因分布。by='primary' 或 'endpoint'。"""
    n_und = sum(1 for r in recs if (r.get("verdict") or "").upper() == "UNDETERMINED")
    if by == "primary":
        cnt = {}
        for r in recs:
            if (r.get("verdict") or "").upper() != "UNDETERMINED":
                continue
            k = r.get("abstention_reason_attribution") or "other"
            cnt[k] = cnt.get(k, 0) + 1
        rows = [
            dict(
                abstention_reason=k,
                n=v,
                share=round(v / float(n_und), 4) if n_und else None,
            )
            for k, v in sorted(cnt.items(), key=lambda kv: -kv[1])
        ]
        return dict(n_undetermined=n_und, rows=rows)
    # by endpoint
    per = {}
    for r in recs:
        if (r.get("verdict") or "").upper() != "UNDETERMINED":
            continue
        ep = r.get("endpoint", "")
        d = per.setdefault(ep, {})
        k = r.get("abstention_reason_attribution") or "other"
        d[k] = d.get(k, 0) + 1
    rows = []
    for ep, d in sorted(per.items()):
        tot = sum(d.values())
        row = dict(endpoint=ep, n_undetermined=tot)
        row["dominant"] = max(d.items(), key=lambda kv: kv[1])[0]
        for k in ORDER:
            if k in d:
                row[k] = round(d[k] / float(tot), 4)
        rows.append(row)
    return dict(n_undetermined=n_und, rows=rows)


def write(outdir, recs, dist_primary, dist_ep):
    os.makedirs(outdir, exist_ok=True)
    p1 = os.path.join(outdir, "reliability_with_attribution.csv")
    cols1 = [
        "compound_id",
        "endpoint",
        "verdict",
        "confidence",
        "reason",
        "abstention_reason_attribution",
        "abstention_reason_label",
        "abstention_reason_secondary",
        "abstention_resolution",
    ]
    with io.open(p1, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols1, extrasaction="ignore")
        w.writeheader()
        for r in recs:
            w.writerow(r)
    p2 = os.path.join(outdir, "abstention_attribution_distribution.csv")
    with io.open(p2, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(
            fh, fieldnames=["abstention_reason", "n", "share"], extrasaction="ignore"
        )
        w.writeheader()
        for r in dist_primary["rows"]:
            w.writerow(r)
    p3 = os.path.join(outdir, "abstention_attribution_by_endpoint.csv")
    cols3 = ["endpoint", "n_undetermined", "dominant"] + ORDER
    with io.open(p3, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols3, extrasaction="ignore")
        w.writeheader()
        for r in dist_ep["rows"]:
            w.writerow(r)
    return p1, p2, p3
