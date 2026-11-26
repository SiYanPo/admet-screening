# -*- coding: utf-8 -*-
"""模块L：跨数据集可迁移性测试（证明准入逻辑不是 OpenADMET 特调）。

外部评审（2026-10-30）原话：
  "如果换一个完全独立 curation 的数据集，你的弃权率、decided_accuracy、域外触发模式
   是否还成立？……关键不是'数字接近'，而是弃权行为是否随数据集 curation 质量的变化而
   按预期方向移动：OneADMET 经过严格 curation，如果其域外触发率显著低于 OpenADMET，
   这本身就是对准入逻辑敏感性的一个可检验证据。如果触发率没有差异，则需要解释为什么
   ——可能是 class block 规则过于刚性，不随数据质量变化。"

本模块是**通用**的：输入任意多个"长表测量集"（同一个 schema：
compound_id,endpoint,value,unit,source,domain_flag,...），各自跑一遍 reliability，
输出弃权行为画像并检验方向性预测。

它不绑定 OneADMET——这样 OneADMET 一到手就能直接跑；在那之前可以用"同一数据集里
curation 程度不同的两个子集"做**代理运行**（产物必须标 `proxy=true`，并写明代理
不等于外部效度）。
"""

import csv
import io
import os

from . import reliability as REL


def _f(v):
    try:
        x = float(v)
        return x if x == x and abs(x) != float("inf") else None
    except (TypeError, ValueError):
        return None


def profile(name, measurements, rules, groups=None):
    """对一个数据集跑 reliability，输出弃权行为画像。"""
    recs = REL.evaluate(
        measurements or [], rules=rules or {}, source_groups=groups or {}
    )
    n = len(recs)
    n_und = sum(1 for r in recs if (r.get("verdict") or "").upper() == "UNDETERMINED")
    n_dec = n - n_und
    n_dom0 = sum(1 for r in recs if int(_f(r.get("n_in_domain")) or 0) == 0)
    n_unit = sum(
        1
        for r in recs
        if "单位异构" in (r.get("reason") or "")
        or "单位不一致" in (r.get("reason") or "")
    )
    n_indep = sum(
        1
        for r in recs
        if "独立方法组仅" in (r.get("reason") or "")
        or "独立组" in (r.get("reason") or "")
    )
    n_gray = sum(1 for r in recs if "灰区" in (r.get("reason") or ""))
    return dict(
        name=name,
        n_pairs=n,
        n_decided=n_dec,
        n_undetermined=n_und,
        abstention_rate=round(n_und / float(n), 4) if n else None,
        domain_block_rate=round(n_dom0 / float(n), 4) if n else None,
        unit_conflict_rate=round(n_unit / float(n), 4) if n else None,
        independence_shortfall_rate=round(n_indep / float(n), 4) if n else None,
        gray_zone_rate=round(n_gray / float(n), 4) if n else None,
        n_sources=len({r.get("source") for r in (measurements or [])}),
        n_compounds=len({r.get("compound_id") for r in (measurements or [])}),
        # v3.6.1：值级准入拒绝率（OneADMET 方向性检验暴露对级统计太粗：
        # 越界值与合法值同组共存时，对级 domain_block_rate 恒为 0，
        # 方向性信号必须看值级）
        n_values=sum(int(_f(r.get("n_total")) or 0) for r in recs),
        n_values_rejected=sum(
            int(_f(r.get("n_total")) or 0) - int(_f(r.get("n_in_domain")) or 0)
            for r in recs
        ),
    )


def decided_accuracy(profile_name, measurements, truth_rows, rules, groups=None):
    """可选：有实测真值时算 decided_accuracy。"""
    recs = REL.evaluate(
        measurements or [], rules=rules or {}, source_groups=groups or {}
    )
    tmap = {}
    for t in truth_rows or []:
        cls = (t.get("truth_class") or "").strip().upper()
        if cls in ("PASS", "FAIL"):
            tmap[(t.get("compound_id", ""), t.get("endpoint", ""))] = cls
    dec = ok = 0
    for r in recs:
        key = (r.get("compound_id", ""), r.get("endpoint", ""))
        if key not in tmap:
            continue
        v = (r.get("verdict") or "").upper()
        if v in ("PASS", "FAIL"):
            dec += 1
            ok += 1 if v == tmap[key] else 0
    return dict(
        name=profile_name,
        n_eval=dec,
        decided_accuracy=round(ok / float(dec), 4) if dec else None,
    )


def compare(profiles, expected_order=None, proxy=False):
    """检验方向性预测：curation 越好 → 域外触发率越低。

    expected_order: (better_name, worse_name)；给出后按方向判定。
    """
    per = {p["name"]: p for p in profiles}
    notes = []
    if len(profiles) < 2:
        return dict(
            per_profile=per,
            prediction_check="需要至少两个数据集才能检验",
            proxy=proxy,
            notes=notes,
        )
    if expected_order and len(expected_order) == 2:
        better, worse = expected_order
        b, w = per.get(better), per.get(worse)
        if not b or not w:
            return dict(
                per_profile=per,
                prediction_check="expected-order 里的名字不在数据集中",
                proxy=proxy,
                notes=notes,
            )
        db, dw = b.get("domain_block_rate"), w.get("domain_block_rate")
        ab, aw = b.get("abstention_rate"), w.get("abstention_rate")
        if db is None or dw is None:
            check = "域外触发率不可估"
        elif db < dw:
            check = (
                "符合预期：curation 更好的 %s 域外触发率 %.3f < %s 的 %.3f"
                "（差 %.3f）——准入行为随数据质量按预期方向移动"
                % (better, db, worse, dw, dw - db)
            )
        else:
            check = (
                "⚠ 未观察到位移：%s 域外触发率 %.3f >= %s 的 %.3f。"
                "这不是'框架错'，而是提示 class block 规则可能过于刚性、"
                "不随 curation 质量变化——须在论文中作为可定位的局限报告"
                % (better, db, worse, dw)
            )
        # v3.6.1：值级准入拒绝率的方向性（对级统计太粗时的有效粒度，
        # OneADMET vs OpenADMET_raw 实测：对级双 0，值级 0.000% vs 0.130% 方向成立）
        vb = (b.get("n_values_rejected") or 0) / float(b.get("n_values") or 1)
        vw = (w.get("n_values_rejected") or 0) / float(w.get("n_values") or 1)
        if vb < vw:
            notes.append(
                "值级准入拒绝率方向符合预期：%s %.4f%% < %s %.4f%%（越界值/全部值）"
                % (better, vb * 100, worse, vw * 100)
            )
        else:
            notes.append(
                "值级准入拒绝率未观察到位移：%s %.4f%% >= %s %.4f%%"
                % (better, vb * 100, worse, vw * 100)
            )
        notes.append(
            "abstention_rate: %s=%.3f vs %s=%.3f" % (better, ab or 0, worse, aw or 0)
        )
    else:
        order = sorted(profiles, key=lambda p: (p.get("domain_block_rate") or 0))
        check = (
            "未给 expected-order：按域外触发率升序排列为 %s；"
            "方向性检验需要显式声明哪个数据集 curation 更好"
            % " < ".join(p["name"] for p in order)
        )
    if proxy:
        notes.append(
            "proxy=true：数据来自同一来源的不同 curation 子集，"
            "仅验证敏感性方向，不等于外部效度（OneADMET 到位后须复跑）"
        )
    return dict(per_profile=per, prediction_check=check, proxy=proxy, notes=notes)


def write(outdir, result):
    os.makedirs(outdir, exist_ok=True)
    p1 = os.path.join(outdir, "transfer_profiles.csv")
    cols = [
        "name",
        "n_pairs",
        "n_decided",
        "n_undetermined",
        "abstention_rate",
        "domain_block_rate",
        "unit_conflict_rate",
        "independence_shortfall_rate",
        "gray_zone_rate",
        "n_values",
        "n_values_rejected",
        "n_sources",
        "n_compounds",
    ]
    with io.open(p1, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in result["per_profile"].values():
            w.writerow(r)
    p2 = os.path.join(outdir, "transfer_note.md")
    lines = [
        "# 跨数据集可迁移性（模块L）",
        "",
        "proxy: %s" % result.get("proxy"),
        "",
        "| 数据集 | pairs | 弃权率 | 域外触发率 | 单位冲突率 | 独立组不足率 |",
        "|---|---|---|---|---|---|",
    ]
    for r in result["per_profile"].values():
        lines.append(
            "| %s | %s | %s | %s | %s | %s |"
            % (
                r.get("name"),
                r.get("n_pairs"),
                r.get("abstention_rate"),
                r.get("domain_block_rate"),
                r.get("unit_conflict_rate"),
                r.get("independence_shortfall_rate"),
            )
        )
    lines += ["", "**方向性检验**", "", result["prediction_check"]]
    for n in result.get("notes") or []:
        lines.append("- " + n)
    with io.open(p2, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return p1, p2
