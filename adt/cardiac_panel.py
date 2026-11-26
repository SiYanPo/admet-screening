# -*- coding: utf-8 -*-
"""心脏离子通道三联筛查（v4.15）：hERG + Cav1.2 + Nav1.5。

为什么必须做三联（本模块的存在理由）：
  skill 此前只有 hERG 一个心脏端点，且已记录 C85：**糖苷不必然是阻断剂**
  （人参皂苷 Rg3 是激动剂；taxifolin 糖苷最大抑制 36.9% 即平台；CAPE 在 AP clamp
  下反使 I_hERG 增大）。单看 hERG 会同时犯两个方向的错：
    · 假阳：亲脂碱把 hERG 堵住，但同步阻断 Cav1.2 会**抵消** APD 延长（qt shortening）；
    · 假阴：hERG 阴性但 Nav1.5 晚电流增大 / Cav1.2 抑制 → 仍可致心律失常。
  CiPA 之所以用 7 个通道 + ORd 模型，就是因为"净效应"不能由单通道外推。

**本模块只做到"证据齐全度 + 通道级裕度分档"，不预测净效应、不给概率**：
  · 不做 ORd / AP 仿真（需要 7 通道完整 + 离子流模型，本机不具备）；
  · 不把三通道合成一个"心脏毒性概率"——那是伪精度；
  · 输出的核心是 `panel_verdict` + `missing_channels` + `action`（该补哪个实验）。

判据（**惯例值，非监管阈值**）：
  裕度 Margin = IC50 / Cmax,u     <10 HIGH ｜ 10–30 INTERMEDIATE ｜ ≥30 LOW
  抑制率 Inh%@Cmax,u             ≥50% HIGH ｜ 30–50% INTERMEDIATE ｜ <30% LOW
  （裕度分档沿用 pbpk.MARGIN_TIERS / Redfern 2003 暂行边际；抑制率 50% 是膜片钳
   常规"显著阻断"工作点，不是法规线。）
"""

from __future__ import division

__all__ = [
    "CHANNELS",
    "TIER_ORDER",
    "assign_tier",
    "channel_verdict",
    "assess_compound",
    "panel",
    "limits_statement",
]

TIER_ORDER = {"LOW": 0, "INTERMEDIATE": 1, "HIGH": 2, "UNKNOWN": -1}

CHANNELS = [
    dict(
        id="herg",
        label="hERG (Kv11.1)",
        required=True,
        ic50_endpoint="cardiac_herg_ic50",
        inh_endpoint="cardiac_herg_inh_pct",
        role="复极延迟（APD 延长）主哨兵；假阳/假阴都多，单独不可判",
    ),
    dict(
        id="cav12",
        label="Cav1.2 (L-type Ca2+)",
        required=False,
        ic50_endpoint="cardiac_cav12_ic50",
        inh_endpoint="cardiac_cav12_inh_pct",
        role="平台期钙流；阻断可**抵消** hERG 的 APD 延长（qt shortening）",
    ),
    dict(
        id="nav15",
        label="Nav1.5 (peak/late Na+)",
        required=False,
        ic50_endpoint="cardiac_nav15_ic50",
        inh_endpoint="cardiac_nav15_inh_pct",
        role="峰钠流决定传导速度；**晚钠流增强**是长 QT/早后除极的另一条通路",
    ),
]

_MARGIN_TIERS = [(10.0, "HIGH"), (30.0, "INTERMEDIATE"), (float("inf"), "LOW")]


def limits_statement():
    return (
        "三通道筛查只给**通道级裕度分档 + 证据缺口**，不给净效应、不给概率；"
        "未做 ORd/AP 仿真，也未覆盖 Kv7.1(KCNQ1)/Kir2.1/Kv4.3/late-INa 等 CiPA 其余通道；"
        "「三通道全 LOW」≠ 安全，只等于「在已测通道内未见高风险」。"
    )


def assign_tier(margin=None, inh_pct=None):
    """裕度优先；无裕度时退回抑制率。两者都无 → UNKNOWN。"""
    if margin is not None and margin == margin:
        for cut, tag in _MARGIN_TIERS:
            if margin < cut:
                return tag, "margin=%.1f" % margin
        return "LOW", "margin=%.1f" % margin
    if inh_pct is not None and inh_pct == inh_pct:
        if inh_pct >= 50.0:
            return "HIGH", "inh=%.0f%%@Cmax" % inh_pct
        if inh_pct >= 30.0:
            return "INTERMEDIATE", "inh=%.0f%%@Cmax" % inh_pct
        return "LOW", "inh=%.0f%%@Cmax" % inh_pct
    return "UNKNOWN", "no_data"


def channel_verdict(ch, ic50_uM=None, inh_pct=None, cmax_uM=None):
    """单通道证据 -> dict。ic50 与 Cmax 同时具备才算裕度。"""
    margin = None
    if (
        ic50_uM is not None
        and ic50_uM == ic50_uM
        and ic50_uM > 0
        and cmax_uM is not None
        and cmax_uM == cmax_uM
        and cmax_uM > 0
    ):
        margin = float(ic50_uM) / float(cmax_uM)
    tier, basis = assign_tier(margin=margin, inh_pct=inh_pct)
    return dict(
        channel=ch["id"],
        label=ch["label"],
        ic50_uM="" if ic50_uM in (None, "") else ic50_uM,
        inh_pct="" if inh_pct in (None, "") else inh_pct,
        margin="" if margin is None else round(margin, 2),
        tier=tier,
        basis=basis,
        # "有数据"与"能分档"是两件事：有 IC50 但缺 Cmax,u 时
        # 数据是有的（不能报"无任何通道数据"），但分不了档。
        has_data=(ic50_uM not in (None, "") or inh_pct not in (None, "")),
        tiered=(tier != "UNKNOWN"),
    )


def assess_compound(compound_id, channel_values, cmax_uM=None):
    """channel_values: {channel_id: dict(ic50_uM=..., inh_pct=...)}"""
    rows = []
    for ch in CHANNELS:
        v = channel_values.get(ch["id"]) or {}
        rows.append(
            channel_verdict(
                ch, ic50_uM=v.get("ic50_uM"), inh_pct=v.get("inh_pct"), cmax_uM=cmax_uM
            )
        )
    have = [r for r in rows if r["has_data"]]
    missing = [ch["id"] for ch, r in zip(CHANNELS, rows) if not r["has_data"]]
    herg = rows[0]

    tiered = [r for r in have if r["tiered"]]
    worst, worst_ch = None, ""
    for r in tiered:
        if worst is None or TIER_ORDER[r["tier"]] > TIER_ORDER[worst]:
            worst, worst_ch = r["tier"], r["channel"]

    if not have:
        verdict = "undetermined_no_channel_data"
        allowed = "无任何心脏离子通道数据，不能对心脏安全性表态"
        action = "至少补 hERG 膜片钳（IC50 或 %抑制@治疗暴露）"
    elif not tiered:
        # v4.21 修正：此前"有 IC50 但缺 Cmax"会被误报成"无任何通道数据"，
        # 这句话是**事实错误**（数据有，缺的是暴露）。而且它会把用户的注意力
        # 从"去补 Cmax"引到"再去测一遍通道"，方向反了。
        verdict = "undetermined_missing_exposure"
        allowed = (
            "已有 %d/%d 通道的 IC50/抑制率，但**缺 Cmax,u**，无法算裕度 → "
            "不能对心脏风险分档" % (len(have), len(CHANNELS))
        )
        action = (
            "补该化合物的 Cmax,u（pbpk 或实测）；只给 IC50 不足以分档"
            "（IC50 单独无意义，见 cardiac_*_ic50 端点规则）"
        )
    elif not herg["has_data"]:
        verdict = "undetermined_missing_herg"
        allowed = "缺 hERG 数据；其余通道不能替代 hERG 作为复极哨兵"
        action = "补 hERG 膜片钳；再补 Cav1.2/Nav1.5"
    elif len(have) == 1:
        # 只有 hERG：这是最常见的误用场景，必须硬性拦住"清除"表述
        verdict = "herg_only_%s" % herg["tier"].lower()
        allowed = (
            "hERG 单通道 %s；**不能**据此排除多通道致心律失常风险"
            "（Cav1.2/Nav1.5 未测，两者可分别抵消或放大 hERG 效应）" % herg["tier"]
        )
        action = "补 Cav1.2 与 Nav1.5（膜片钳或经验证的多任务模型）后再下结论"
    else:
        verdict = "panel_%s" % (worst or "unknown").lower()
        if worst == "LOW":
            allowed = (
                "已测 %d/%d 通道均 LOW（裕度≥30 或抑制<30%%@Cmax）；"
                "**在已测通道内**未见高风险，不等于安全" % (len(have), len(CHANNELS))
            )
        else:
            allowed = (
                "通道级最高风险 %s（%s）；未做 ORd 净效应仿真，"
                "不得据此推断临床 QT 风险大小" % (worst, worst_ch)
            )
        action = (
            ("补 %s；或进 ORd/AP 仿真评估净效应" % "、".join(missing))
            if missing
            else "三通道齐备，可进 ORd 净效应评估"
        )

    return dict(
        compound_id=compound_id,
        cmax_uM="" if cmax_uM is None else cmax_uM,
        n_channels=len(have),
        channels_with_data=";".join(r["channel"] for r in have),
        missing_channels=";".join(missing),
        worst_tier=worst or "UNKNOWN",
        worst_channel=worst_ch,
        panel_verdict=verdict,
        allowed_statement=allowed,
        action=action,
        net_effect="not_estimated",
        limits=limits_statement(),
        **{"%s_tier" % r["channel"]: r["tier"] for r in rows},
        **{"%s_margin" % r["channel"]: r["margin"] for r in rows},
    )


def panel(channel_by_cid, cmax_by_cid=None):
    """批量：channel_by_cid = {cid: {ch: {ic50_uM/inh_pct}}}。"""
    cmax_by_cid = cmax_by_cid or {}
    return [
        assess_compound(cid, vals, cmax_uM=cmax_by_cid.get(cid))
        for cid, vals in channel_by_cid.items()
    ]
