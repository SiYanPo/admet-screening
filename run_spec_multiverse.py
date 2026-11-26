r"""A6 规格敏感性（specification multiverse）：把"分析选择"显式化，看结论能翻几次。

## 为什么必须做（次轮 A6，第三轮 §E4 重新置顶）
本包的核心负结果——"完整准入层（S4）不比朴素多数投票（S1）好"——**是一个
带分析选择的结论**：它能成立，依赖 ① 用哪个代价点、② 纳入哪些端点、
③ 跟谁比、④ 怎么跨端点聚合。只报默认规格下的一个数字，等于把
"4 维选择空间里的一个点"当成"结论"。

Steegen et al. 2016 的 multiverse 分析要求的正是：**把选择空间全部列出，
报结论在其中翻转的比例**，而不是挑一个最有利的规格。

## 为什么从 `per_run` 重算，而不是读 `cost_sweep`
`cost_sweep` 只有 4 条对照，**没有 S4−S5**（S5 只与 S1 配对过），
直接读它会让"以 S5 为基线"的一半规格变成 `no_data`——那等于用数据缺口
冒充结论稳健。`per_run` 是逐种子原始效用（2700 行），可以精确构造任意
策略对差，因此本脚本一律从 `per_run` 重算，配对 bootstrap 在同一批种子上做。

## 规格空间（写死在代码里，禁事后增删）
| 维度 | 取值 | 理由 |
|---|---|---|
| cost_point | 9 个（ref + abstain×5 + false_pass×3） | per_run 已实跑 |
| endpoint_subset | all3 / noDILI / noBBB / hERG_only | DILI 低有效性；BBB 无据；单端点对照 |
| baseline | S1 朴素多数 / S5 未校准置信度 | 只比 S1 会漏"基线过强" |
| aggregation | strict_all / majority / pooled_median | 跨端点聚合方式本身是选择 |

共 9 × 4 × 2 × 3 = **216 个规格**。对每个规格判 S4 是否优于 baseline。

## 输出
- `out_ext/keystone_spec_multiverse.json`
- `out_ext/keystone_spec_multiverse.md`

## 用法
```bash
python run_spec_multiverse.py --in out_keystone_v43/results.json
```
"""
from __future__ import annotations

import argparse
import io
import itertools
import json
import os
import statistics

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))

SUBSETS = {
    "all3": ["hERG", "DILI", "BBB_Martins"],
    "noDILI": ["hERG", "BBB_Martins"],
    "noBBB": ["hERG", "DILI"],
    "hERG_only": ["hERG"],
}
BASELINES = {"S1": "S1_naive_majority", "S5": "S5_uncalibrated_conf"}
TREATED = "S4_full_admission"
BOOT = 2000
SEED = 0


def _paired(per_run, cost_point, endpoint, base):
    """返回该规格下逐种子的 Δ(utility) = S4 − baseline。"""
    by_seed = {}
    for r in per_run:
        if r["cost_point"] != cost_point or r["endpoint"] != endpoint:
            continue
        if r["strategy"] not in (TREATED, base):
            continue
        by_seed.setdefault(r["seed"], {})[r["strategy"]] = r["utility"]
    deltas = []
    for s, v in sorted(by_seed.items()):
        if TREATED in v and base in v:
            deltas.append(v[TREATED] - v[base])
    return np.array(deltas, dtype=float)


def _summarize(deltas, reps=BOOT, seed=SEED):
    if len(deltas) < 3:
        return {"n_pairs": int(len(deltas)), "delta_median": None,
                "boot_ci95": None, "significant": False,
                "descriptive_only": True, "fwer_controlled": False,
                "effective_n_note": "216 规格共享 20 种子，有效 n=20；禁止当作 216 次独立检验（外审 A N6 / C09）"}
    rng = np.random.default_rng(seed)
    med = float(np.median(deltas))
    bs = [float(np.median(rng.choice(deltas, len(deltas), replace=True)))
          for _ in range(reps)]
    lo, hi = float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))
    return {"n_pairs": int(len(deltas)),
            "delta_median": round(med, 4),
            "boot_ci95": [round(lo, 4), round(hi, 4)],
            "significant": bool(lo > 0 or hi < 0),
            # 2026-11-04 / C09 + §5.1 复审：Holm 不修伪重复，本检出只能作描述性
            "descriptive_only": True,
            "fwer_controlled": False,
            "effective_n_note": ("216 规格共享同一批 20 种子，有效 n=20 而非 216x20；"
                                 "significant 字段仅为描述性标记，不得用于推断性结论。"
                                 "正式处理见 references/SPEC_CURVE_POLICY.md")}


def _verdict_strict(rows):
    if not rows:
        return "no_data"
    if all(r["significant"] and r["delta_median"] > 0 for r in rows):
        return "better"
    if all(r["significant"] and r["delta_median"] < 0 for r in rows):
        return "worse"
    return "mixed"


def _verdict_majority(rows):
    if not rows:
        return "no_data"
    b = sum(1 for r in rows if r["significant"] and r["delta_median"] > 0)
    w = sum(1 for r in rows if r["significant"] and r["delta_median"] < 0)
    if b > len(rows) / 2.0:
        return "better"
    if w > len(rows) / 2.0:
        return "worse"
    return "mixed"


def _verdict_pooled(rows):
    if not rows:
        return "no_data"
    m = statistics.median([r["delta_median"] for r in rows])
    if m > 0:
        return "better"
    if m < 0:
        return "worse"
    return "mixed"


AGG = {"strict_all": _verdict_strict,
       "majority": _verdict_majority,
       "pooled_median": _verdict_pooled}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default=os.path.join(HERE, "out_keystone_v43/results.json"))
    ap.add_argument("--out-json", dest="out_json",
                    default=os.path.join(HERE, "out_ext/keystone_spec_multiverse.json"))
    ap.add_argument("--out-md", dest="out_md",
                    default=os.path.join(HERE, "out_ext/keystone_spec_multiverse.md"))
    a = ap.parse_args(argv)

    d = json.load(io.open(a.inp, encoding="utf-8"))
    per_run = d["per_run"]
    cost_points = list(d["cost_sweep"].keys())

    # 先算逐规格逐端点的配对差（缓存，避免 O(n^2) 重复扫描）
    cache = {}
    for cp, ep, b in itertools.product(cost_points, SUBSETS["all3"], BASELINES):
        cache[(cp, ep, b)] = _summarize(_paired(per_run, cp, ep, BASELINES[b]))

    specs, counts = [], {"better": 0, "worse": 0, "mixed": 0, "no_data": 0}
    for cp, sub, base, agg in itertools.product(cost_points, SUBSETS, BASELINES, AGG):
        rows = []
        for ep in SUBSETS[sub]:
            s = cache[(cp, ep, base)]
            if s["delta_median"] is None:
                continue
            rows.append({"endpoint": ep, **s})
        v = AGG[agg](rows)
        counts[v] = counts.get(v, 0) + 1
        specs.append({"cost_point": cp, "endpoint_subset": sub, "baseline": base,
                      "aggregation": agg, "n_endpoints": len(rows), "verdict": v,
                      "deltas": {r["endpoint"]: r["delta_median"] for r in rows}})

    n = len(specs)
    nonmix = n - counts.get("mixed", 0) - counts.get("no_data", 0)
    flip_rate = (min(counts["better"], counts["worse"]) / float(nonmix)
                 if nonmix else None)

    directional = [s for s in specs if s["verdict"] in ("better", "worse")]
    by_base, by_subset, by_cost = {}, {}, {}
    for b in BASELINES:
        sel = [s for s in directional if s["baseline"] == b]
        by_base[b] = {"n_directional": len(sel),
                      "pct_worse": (round(100.0 * sum(1 for s in sel if s["verdict"] == "worse")
                                          / len(sel), 1) if sel else None)}
    for s_name in SUBSETS:
        sel = [s for s in directional if s["endpoint_subset"] == s_name]
        by_subset[s_name] = {"n_directional": len(sel),
                             "pct_worse": (round(100.0 * sum(1 for x in sel if x["verdict"] == "worse")
                                                 / len(sel), 1) if sel else None)}
    for cp in cost_points:
        sel = [s for s in directional if s["cost_point"] == cp]
        by_cost[cp] = {"n_directional": len(sel),
                       "pct_worse": (round(100.0 * sum(1 for x in sel if x["verdict"] == "worse")
                                           / len(sel), 1) if sel else None)}

    # ref 代价点上的三端点 S4−S5 精确值（核对评审报告引用的 −0.133/−0.115/−0.219）
    ref_check = {ep: cache[("ref", ep, "S5")] for ep in SUBSETS["all3"]}

    payload = {
        "source": os.path.relpath(a.inp, HERE).replace("\\", "/"),
        "recomputed_from": "per_run（逐种子原始效用），非 cost_sweep 聚合值",
        "design": ("multiverse：9 cost_point × 4 endpoint_subset × 2 baseline × 3 aggregation "
                   "= %d 规格；配对 bootstrap 在同一批种子上做（20 种子）" % n),
        "reference": ("Steegen S, Tuerlinckx F, Gelman A, Vanpaemel W. 2016. "
                      "Increasing Transparency Through a Multiverse Analysis. "
                      "Perspect Psychol Sci 11(5):702–712."),
        "claim_under_test": "S4 完整准入层优于 baseline",
        "multiplicity_policy": {
            "status": "descriptive_only",
            "fwer_controlled": False,
            "effective_n": 20,
            "n_nominal_specs": n,
            "reason": ("外审 A N6：216 规格共享 20 种子，run6/selective 三法 AURC "
                       "全等 0.3397(n=8)。Holm 只能作描述性附加，不产生族错误率控制；"
                       "正式处理为按种子聚类的 specification-curve permutation test。"),
            "holm_applied_as": "descriptive_annotation_only",
            "binding_item": "B6 / references/SPEC_CURVE_POLICY.md",
        },
        "counts": counts,
        "flip_rate": None if flip_rate is None else round(flip_rate, 3),
        "by_baseline": by_base,
        "by_endpoint_subset": by_subset,
        "by_cost_point": by_cost,
        "ref_s4_minus_s5": ref_check,
        "specifications": specs,
        "verdict": None,
    }

    if flip_rate is not None and flip_rate >= 0.20:
        payload["verdict"] = {"code": "specification_fragile",
                              "statement": ("结论**对分析规格脆弱**：在有方向的 %d 个规格里，"
                                            "少数派占 %.1f%%（阈值 20%%）。"
                                            "任何『准入层无优势』的表述都必须同时给出规格分布，"
                                            "且不得写成无条件结论。" % (nonmix, 100 * flip_rate))}
    else:
        payload["verdict"] = {"code": "specification_robust",
                              "statement": ("结论对规格**稳健**：在有方向的 %d 个规格里，"
                                            "方向翻转仅占 %s%%。可写『在全部 %d 个规格中 S4 均不优于"
                                            " baseline』，但仍须注明依赖 cost_point 网格。"
                                            % (nonmix,
                                               "0" if flip_rate is None else "%.1f" % (100 * flip_rate),
                                               n))}

    os.makedirs(os.path.dirname(a.out_json), exist_ok=True)
    with io.open(a.out_json, "w", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False, indent=2))

    L = ["# 规格敏感性（multiverse）：『准入层』结论有多结实（A6）\n",
         "> 数据源：`%s`（%s）；设计：%s\n" % (payload["source"],
                                          payload["recomputed_from"], payload["design"]),
         "**受检命题**：%s\n" % payload["claim_under_test"],
         "| 维度 | 取值 |", "|---|---|"]
    L.append("| cost_point | %s |" % " / ".join(cost_points))
    L.append("| endpoint_subset | %s |" % " / ".join(SUBSETS))
    L.append("| baseline | %s |" % " / ".join(BASELINES))
    L.append("| aggregation | %s |" % " / ".join(AGG))
    L.append("")
    L.append("## 计数\n")
    L.append("| 判定 | 规格数 | 占比 |")
    L.append("|---|---|---|")
    for k in ("better", "worse", "mixed", "no_data"):
        L.append("| %s | %d | %.1f%% |" % (k, counts.get(k, 0), 100.0 * counts.get(k, 0) / n))
    L.append("")
    L.append("## 分维度：判定为「更差」的比例\n")
    for label, blk in (("按 baseline", by_base), ("按端点子集", by_subset),
                       ("按代价点", by_cost)):
        L.append("### %s\n" % label)
        L.append("| 取值 | 有方向规格数 | 判『更差』占比 |")
        L.append("|---|---|---|")
        for k, v in blk.items():
            L.append("| %s | %d | %s |" % (k, v["n_directional"],
                                          "—" if v["pct_worse"] is None
                                          else "%.1f%%" % v["pct_worse"]))
        L.append("")
    L.append("## ref 代价点上的 S4−S5（核对报告引用的 −0.133/−0.115/−0.219）\n")
    L.append("| 端点 | Δ 中位 | 95%CI | 显著 |")
    L.append("|---|---|---|---|")
    for ep, s in ref_check.items():
        L.append("| %s | %s | %s | %s |"
                 % (ep,
                    "—" if s["delta_median"] is None else "%+.4f" % s["delta_median"],
                    s["boot_ci95"], s["significant"]))
    L.append("")
    L.append("## 判定\n")
    L.append("**%s** — %s\n" % (payload["verdict"]["code"], payload["verdict"]["statement"]))
    L.append("> 复现：`python run_spec_multiverse.py`。逐规格明细见 JSON 的 `specifications`。\n")
    with io.open(a.out_md, "w", encoding="utf-8") as f:
        f.write("\n".join(L))

    print(json.dumps({"counts": counts, "flip_rate": payload["flip_rate"],
                      "ref_s4_minus_s5": {k: v["delta_median"] for k, v in ref_check.items()},
                      "verdict": payload["verdict"]["code"]}, ensure_ascii=False, indent=1))
    print("[multiverse] -> %s" % a.out_json)
    return payload


if __name__ == "__main__":
    main()
