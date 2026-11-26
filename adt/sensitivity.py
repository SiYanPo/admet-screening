# -*- coding: utf-8 -*-
"""E3 阈值敏感性分析（评估报告 P0-1 的落地模块）。

**为什么必须有这个模块**：`03_endpoint_rules.yaml` 自声明 `threshold_source:
literature`——23 个质量端点的 pass/fail 阈值**没有一条来自本项目实测**。既然
阈值是"文献起点值"，那么"结论对这个起点有多敏感"就是结论可信度的一部分，
而不是可选项。v2.1 及更早版本只有这句话、没有这个计算。

方法（两个模式，都基于 reliability.evaluate 的同一套裁决语义，避免两套逻辑分叉）：
  1) **global**：所有端点的数值阈值同时按 (1±f) 缩放 —— 检验"整套阈值若系统性
     偏松/偏紧 20% / 50%，有多少结论会翻"；
  2) **per_endpoint**：一次只缩放一个端点 —— 找出"决策关键端点"（谁的阈值最不能错）。

判据：翻转率 > 0.20 的端点标 `fragile`，报告中必须显式声明；> 0.50 标
`threshold_critical`（该端点的结论不得进入对外结论段，只能进"待实测确认"）。

输出：sensitivity.csv
  mode, endpoint, factor, direction, n_compounds, n_decided_base, n_flipped,
  flip_rate, flag, examples
"""

import csv
import io
import os

from . import schema
from .reliability import evaluate


def _scale(v, f):
    """按 (1±f) 缩放一个阈值；None/0 原样返回（0 不缩放，避免阈值消失）。"""
    if v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return v
    if x == 0.0:
        return 0.0
    return x * (1.0 + f)


def _scale_endpoint(rule, f):
    """缩放单个端点规则里的所有数值阈值（pass/fail/window/soft）。

    注意方向语义依赖 shape：对 up 型（越大越好），pass 下调 = 放松；
    对 down 型（越小越好），pass 下调 = 收紧。故输出用客观的 lower/raise。
    """
    r = dict(rule)
    for k in ("pass", "fail"):
        if k in r:
            r[k] = _scale(r[k], f)
    if "window" in r and isinstance(r["window"], (list, tuple)):
        r["window"] = [_scale(x, f) for x in r["window"]]
    if "soft" in r and isinstance(r["soft"], (list, tuple)):
        r["soft"] = [_scale(x, f) for x in r["soft"]]
    if "tiers" in r and isinstance(r["tiers"], dict):
        r["tiers"] = {k: _scale(v, f) for k, v in r["tiers"].items()}
    return r


def _verdict_map(recs):
    """(cid, ep) -> verdict，只保留 PASS/FAIL（翻灰区也算翻转，单独计数）。"""
    return {(r["compound_id"], r["endpoint"]): r["verdict"] for r in recs}


def _flip_stats(base, pert):
    decided = [k for k, v in base.items() if v in ("PASS", "FAIL")]
    flips = [k for k in decided if pert.get(k) != base[k]]
    return len(decided), len(flips), flips


def analyze(
    measurements,
    rules,
    factors=(0.2, 0.5),
    non_ranking=None,
    saturated=None,
    source_groups=None,
):
    """返回 (rows, summary)。

    rules: {endpoint_id: rule dict}（与 reliability._load_rules 同格式）
    """
    non_ranking = non_ranking or set()
    saturated = saturated or set()
    base_recs = evaluate(measurements, rules, non_ranking, saturated, source_groups)
    base = _verdict_map(base_recs)

    quality = {
        k: v
        for k, v in rules.items()
        if (v or {}).get("role", "quality") == "quality"
        and any(x in (v or {}) for x in ("pass", "fail", "window"))
    }

    rows = []
    for f in factors:
        for direction, signed in (("lower", -abs(f)), ("raise", +abs(f))):
            # ---- global：全部端点同时缩放 ----
            grules = {
                k: (_scale_endpoint(v, signed) if k in quality else v)
                for k, v in rules.items()
            }
            grecs = evaluate(
                measurements, grules, non_ranking, saturated, source_groups
            )
            n_dec, n_flip, flips = _flip_stats(base, _verdict_map(grecs))
            rows.append(
                dict(
                    mode="global",
                    endpoint="(all)",
                    factor=f,
                    direction=direction,
                    n_compounds=len({k[0] for k in base}),
                    n_decided_base=n_dec,
                    n_flipped=n_flip,
                    flip_rate=round(n_flip / n_dec, 3) if n_dec else "",
                    flag=_flag(n_flip, n_dec),
                    examples=";".join("%s/%s" % (c, e) for c, e in flips[:5]),
                )
            )
            # ---- per_endpoint：一次只动一个 ----
            for ep in sorted(quality):
                prules = dict(rules)
                prules[ep] = _scale_endpoint(quality[ep], signed)
                precs = evaluate(
                    measurements, prules, non_ranking, saturated, source_groups
                )
                keep = {k: v for k, v in _verdict_map(precs).items() if k[1] == ep}
                sub_base = {k: v for k, v in base.items() if k[1] == ep}
                n_dec, n_flip, flips = _flip_stats(sub_base, keep)
                rows.append(
                    dict(
                        mode="per_endpoint",
                        endpoint=ep,
                        factor=f,
                        direction=direction,
                        n_compounds=len({k[0] for k in sub_base}),
                        n_decided_base=n_dec,
                        n_flipped=n_flip,
                        flip_rate=round(n_flip / n_dec, 3) if n_dec else "",
                        flag=_flag(n_flip, n_dec),
                        examples=";".join("%s" % c for c, _ in flips[:5]),
                    )
                )
    return rows, _summary(rows)


def _flag(n_flip, n_dec):
    if not n_dec:
        return "no_decided"
    rate = n_flip / float(n_dec)
    if rate > 0.50:
        return "threshold_critical"
    if rate > 0.20:
        return "fragile"
    return "robust"


def _summary(rows):
    """汇总：最脆弱的端点（取每端点各方向的最大翻转率）+ 全局最大翻转率。"""
    per_ep = {}
    for r in rows:
        if r["mode"] != "per_endpoint" or r["flip_rate"] == "":
            continue
        per_ep[r["endpoint"]] = max(per_ep.get(r["endpoint"], 0.0), r["flip_rate"])
    glob = [
        r["flip_rate"] for r in rows if r["mode"] == "global" and r["flip_rate"] != ""
    ]
    return dict(
        worst_endpoints=sorted(per_ep.items(), key=lambda x: -x[1])[:8],
        max_global_flip=max(glob) if glob else None,
        n_endpoints=len(per_ep),
    )


def write(path, rows):
    cols = [
        "mode",
        "endpoint",
        "factor",
        "direction",
        "n_compounds",
        "n_decided_base",
        "n_flipped",
        "flip_rate",
        "flag",
        "examples",
    ]
    with io.open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return len(rows)


def load(path):
    if not os.path.exists(path):
        return []
    with io.open(path, encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


# ---------------------------------------------------------------------------
# U6：适用域阈值摄动（Sahigara 2012, Molecules 17:4791-4810）
# ---------------------------------------------------------------------------
# 论文的原话大意：AD 的"定义与阈值"本身决定了把化合物判为内插还是外推，
# 所以 AD 阈值必须以**敏感性**方式报告，而不是当常数。
# 本 skill 里 AD 的两个可调旋钮是：
#   (a) 票数门控 require（1/2/3 个独立方法组）——收紧=更少端点可判；
#   (b) 域外行的处置（严格剔除 vs 宽松当作可用）——这正是"AD 放宽"的等效操作。
# 二者都能用同一条 evaluate 语义重算，避免两套逻辑分叉。
def ad_analyze(
    measurements,
    rules,
    non_ranking=None,
    saturated=None,
    source_groups=None,
    require_grid=(1, 2, 3),
    domain_modes=("strict", "loose"),
):
    """返回 (rows, summary)：AD 旋钮对结论翻转的影响。"""
    non_ranking = non_ranking or set()
    saturated = saturated or set()
    base_recs = evaluate(measurements, rules, non_ranking, saturated, source_groups)
    base = _verdict_map(base_recs)
    rows = []

    def _run(ms, rl):
        recs = evaluate(ms, rl, non_ranking, saturated, source_groups)
        return _verdict_map(recs)

    for mode in domain_modes:
        for req in require_grid:
            rl = {}
            for k, v in rules.items():
                v2 = dict(v or {})
                if v2.get("role", "quality") == "quality":
                    # 键名必须与 reliability 一致：require_sources（不是 require）
                    v2["require_sources"] = req
                rl[k] = v2
            ms = measurements
            if mode == "loose":
                # 模拟"AD 放宽"：把域外/错误行当作普通预测行（等价于 AD 阈值放到无穷宽）
                ms = [
                    (
                        dict(r, domain_flag="predicted")
                        if r.get("domain_flag") in ("out_of_domain", "error")
                        else r
                    )
                    for r in measurements
                ]
            pert = _run(ms, rl)
            n_dec, n_flip, flips = _flip_stats(base, pert)
            # AD 旋钮改的往往不是"翻向"，而是"判不判"：
            #   放松 → 原本 UNDETERMINED 变成有判定（新增）
            #   收紧 → 原本有判定变成 UNDETERMINED（丢失）
            # 只统计翻转会完全漏掉这两类，必须分开报。
            n_new = sum(
                1
                for k, v in pert.items()
                if v in ("PASS", "FAIL") and base.get(k) not in ("PASS", "FAIL")
            )
            n_lost = sum(
                1
                for k, v in base.items()
                if v in ("PASS", "FAIL") and pert.get(k) not in ("PASS", "FAIL")
            )
            rows.append(
                dict(
                    variant="domain=%s,require=%d" % (mode, req),
                    n_decided_base=n_dec,
                    n_flipped=n_flip,
                    n_new_decided=n_new,
                    n_lost_decided=n_lost,
                    flip_rate=round(n_flip / n_dec, 3) if n_dec else "",
                    flag=_flag(n_flip + n_lost, n_dec),
                    examples=";".join("%s/%s" % (c, e) for c, e in flips[:6]),
                )
            )

    rates = [
        (r["n_flipped"] + r["n_lost_decided"] + r["n_new_decided"])
        / float(max(1, r["n_decided_base"]))
        for r in rows
    ]
    changes = [r["n_flipped"] + r["n_lost_decided"] + r["n_new_decided"] for r in rows]
    worst_i = max(range(len(rows)), key=lambda i: rates[i]) if rows else None
    summ = dict(
        max_flip=max(rates) if rates else None,
        max_changes=max(changes) if changes else None,
        worst_variant=rows[worst_i]["variant"] if worst_i is not None else "",
        n_variants=len(rows),
    )
    return rows, summ


def ad_write(path, rows):
    cols = [
        "variant",
        "n_decided_base",
        "n_flipped",
        "n_new_decided",
        "n_lost_decided",
        "flip_rate",
        "flag",
        "examples",
    ]
    with io.open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return len(rows)
