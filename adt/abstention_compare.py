# -*- coding: utf-8 -*-
"""模块M：结构性弃权 vs 模型依赖弃权的正面对比（与 Honest ADMET 对话）。

外部评审（2026-10-30）原话：
  "Honest ADMET 的核心发现之一是：在 cluster shift 下，最佳弃权信号是模型依赖的，
   且各端点的弃权收益与乐观偏差之间不相关（ρ=0.07，不显著）……这意味着：任何依赖
   单一模型内部不确定性信号的弃权策略，在跨端点时缺乏一致的行为保证。
   你的框架的弃权触发条件是结构性的……你真正需要展示的是：结构性弃权的 AURC 在端点
   间的方差（跨端点一致性）是否显著低于模型依赖信号。"

本模块逐端点算三种弃权信号的 AURC / risk@{80,90}：
  structural      结构性准入弃权（域外/票数/单位/分歧）—— 不依赖 exchangeability
  conformal_width 保形区间宽度（模型依赖）
  vote_confidence 校准后投票置信度 / 源间分歧（模型依赖）

并给出**跨端点 AURC 的离散度**（sd / IQR / CV）作为"一致性"的操作化度量，
直接检验可检验预测：`sd(structural) < sd(模型依赖信号)`。

诚实边界：
  - 无实测真值时用 proxy_majority 伪标签，产物标 `label_source`；这不是外部验证。
  - 端点已裁决配对 < min_pairs 时该端点的 AURC 标 `insufficient`，不参与离散度统计
    （否则小样本端点的抖动会伪装成"不一致"）。
"""

import csv
import io
import os

from . import selective as SEL


def _sd(vals):
    vals = [v for v in vals if v is not None]
    if len(vals) < 2:
        return None
    m = sum(vals) / float(len(vals))
    var = sum((v - m) ** 2 for v in vals) / float(len(vals) - 1)
    return var**0.5


def _mean(vals):
    vals = [v for v in vals if v is not None]
    return sum(vals) / float(len(vals)) if vals else None


def _iqr(vals):
    vals = sorted(v for v in vals if v is not None)
    if len(vals) < 4:
        return None
    n = len(vals)
    lo = vals[int(0.25 * (n - 1))]
    hi = vals[int(0.75 * (n - 1))]
    return hi - lo


def compare_by_endpoint(
    recs,
    truth_rows=None,
    measurements=None,
    rules=None,
    proxy="none",
    conformal=None,
    vote_table=None,
    min_pairs=10,
):
    """逐端点算 AURC，并汇总跨端点离散度。"""
    eps = sorted({r.get("endpoint", "") for r in recs or []})
    per = {}
    for ep in eps:
        sub = [r for r in recs if r.get("endpoint", "") == ep]
        st = [t for t in (truth_rows or []) if t.get("endpoint", "") == ep]
        sm = [m for m in (measurements or []) if m.get("endpoint", "") == ep]
        res = SEL.evaluate(
            sub,
            truth_rows=st or None,
            measurements=sm or None,
            rules=rules,
            proxy=proxy,
            vote_table=vote_table,
            conformal=conformal,
        )
        methods = {}
        for name, m in (res.get("methods") or {}).items():
            ok = m.get("n", 0) >= min_pairs and m.get("aurc") is not None
            methods[name] = dict(
                aurc=m.get("aurc") if ok else None,
                n=m.get("n"),
                risk80=m.get("risk80") if ok else None,
                risk90=m.get("risk90") if ok else None,
                status="ok" if ok else "insufficient",
            )
        per[ep] = dict(
            methods=methods,
            label_source=res.get("label_source"),
            error=res.get("error", ""),
            evidence_grade=res.get("evidence_grade", "unknown"),
            n_all=res.get("n_all"),
            abstention_rate=res.get("abstention_rate"),
            comparable_for_prediction_check=res.get(
                "comparable_for_prediction_check", False
            ),
        )

    # 跨端点离散度
    names = set()
    for v in per.values():
        names |= set(v["methods"])
    spread = {}
    for name in sorted(names):
        vals = [
            per[ep]["methods"][name]["aurc"]
            for ep in per
            if name in per[ep]["methods"]
            and per[ep]["methods"][name]["aurc"] is not None
        ]
        sd = _sd(vals)
        mean = _mean(vals)
        spread[name] = dict(
            n_endpoints=len(vals),
            mean_aurc=mean,
            sd=sd,
            iqr=_iqr(vals),
            cv=(sd / mean) if (sd is not None and mean) else None,
        )

    # 可检验预测：结构性弃权的跨端点一致性优于模型依赖信号
    check = ""
    sd_struct = spread.get("structural", {}).get("sd")
    rivals = {
        k: v["sd"]
        for k, v in spread.items()
        if k != "structural" and v["sd"] is not None
    }
    if sd_struct is None:
        check = "结构性信号的端点方差不可估（可裁决端点不足）"
    elif not rivals:
        check = "缺少模型依赖信号的端点方差，无法对比"
    else:
        best = min(rivals.items(), key=lambda kv: kv[1])
        if sd_struct < best[1]:
            check = (
                "支持预测：sd(structural)=%.4f < 最低模型依赖信号 %s=%.4f，"
                "结构性弃权的跨端点 AURC 更集中" % (sd_struct, best[0], best[1])
            )
        else:
            check = (
                "⚠ 不支持预测：sd(structural)=%.4f >= %s=%.4f——"
                "本数据上结构性弃权并不比模型依赖信号更一致，须如实报告，"
                "不得写成'结构性弃权一致性优势'" % (sd_struct, best[0], best[1])
            )
    # 2026-11-04 / C06 + §5.1 复审：循环标签或弃权率不可比时，
    # 不得用这批 AURC 下「结构性弃权跨端点更一致」的结论。
    reasons = []
    bad_grade = [
        ep for ep, v in per.items() if v.get("evidence_grade") == "non_evidence"
    ]
    if bad_grade:
        reasons.append(
            "proxy_majority 伪标签与 verdict 同源（循环论证），"
            "涉及端点：%s" % ", ".join(bad_grade)
        )
    rates = sorted(
        {
            v.get("abstention_rate")
            for v in per.values()
            if v.get("abstention_rate") is not None
        }
    )
    if len(rates) > 1:
        reasons.append(
            "各端点弃权率不同 %s：AURC 已含弃权代价，" "跨端点 sd 不可直接比较" % rates
        )
    if reasons:
        return dict(
            per_endpoint=per,
            spread=spread,
            prediction_check="不可判：" + "；".join(reasons),
            prediction_check_excluded=True,
            exclusion_reasons=reasons,
            min_pairs=min_pairs,
        )
    return dict(
        per_endpoint=per,
        spread=spread,
        prediction_check=check,
        prediction_check_excluded=False,
        min_pairs=min_pairs,
    )


def write(outdir, result):
    os.makedirs(outdir, exist_ok=True)
    p1 = os.path.join(outdir, "abstention_compare_by_endpoint.csv")
    cols = [
        "endpoint",
        "signal",
        "aurc",
        "n",
        "risk80",
        "risk90",
        "status",
        "label_source",
    ]
    with io.open(p1, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for ep, v in sorted(result["per_endpoint"].items()):
            for name, m in sorted(v["methods"].items()):
                row = dict(endpoint=ep, signal=name, label_source=v.get("label_source"))
                row.update(m)
                w.writerow(row)
    p2 = os.path.join(outdir, "abstention_compare_spread.csv")
    cols2 = ["signal", "n_endpoints", "mean_aurc", "sd", "iqr", "cv"]
    with io.open(p2, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols2, extrasaction="ignore")
        w.writeheader()
        for name, v in sorted(result["spread"].items()):
            row = dict(signal=name)
            row.update(v)
            w.writerow(row)
    p3 = os.path.join(outdir, "abstention_compare_note.md")
    lines = [
        "# 结构性 vs 模型依赖弃权（模块M）",
        "",
        "min_pairs: %d（低于此的端点标 insufficient，不进离散度统计）"
        % result["min_pairs"],
        "",
        "| 信号 | 端点数 | mean AURC | sd | IQR | CV |",
        "|---|---|---|---|---|---|",
    ]
    for name, v in sorted(result["spread"].items()):
        lines.append(
            "| %s | %s | %s | %s | %s | %s |"
            % (name, v["n_endpoints"], v["mean_aurc"], v["sd"], v["iqr"], v["cv"])
        )
    lines += ["", "**可检验预测**", "", result["prediction_check"]]
    with io.open(p3, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return p1, p2, p3
