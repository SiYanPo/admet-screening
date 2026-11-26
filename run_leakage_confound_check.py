# -*- coding: utf-8 -*-
r"""E2 复核：近邻泄漏归因代理的负值从哪来，以及这个代理到底能不能用。

## 评审的质问（第三轮 §E2）
> "BBB 的 Δ=**−0.212**（近邻组共享误差反而更低）目前无解释——这个负值本身
>   需要一个假设与检验，否则它会成为『代理不可解释』的反证。"

这一条问得对。本文档给三件事：
1. 把 v4.3 没报的两个对比补齐（close−novel、close−near_dup），不只看 near_dup−novel；
2. 提出并检验一个**替代假设** H2（不是记忆驱动，而是"源间一致率"驱动）；
3. 据此重判该代理的**可用性**——这比解释单个负值更要紧。

## 两个竞争假设
- **H1 记忆驱动**：越靠近训练集，共享误差越强 → `ρ_error(close) > ρ_error(novel)`。
- **H2 一致率驱动**：`ρ_error` 是把三源误差当三条序列算相关；三源**同时答对**时误差
  三项相同，天然抬高 ρ。因此 `ρ_error` 主要由 `all_agree_rate` 决定，
  与"是否记忆"无关。→ `ρ_error` 应与 `all_agree_rate` 同向，而与距离无关。

## 判据（写在代码里）
- H1 成立需：close−novel > 0 且在 ≥2/3 端点同号。
- H2 成立需：跨"端点×分层"的所有可用点上，`ρ_error` 与 `all_agree_rate`
  的 Spearman > 0.8 且 p < 0.05（H2 预测强正相关）。
- 若 H1 被否、H2 成立 → 该代理**不能**用来判定记忆假说，归因项必须**重新置为未关闭**，
  而不是"部分关闭、方向不支持"。

## 输出
`out_ext/tdc/leakage_confound_check.json`

## 用法
```bash
python run_leakage_confound_check.py
```
"""
from __future__ import annotations

import argparse
import io
import json
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
STRATA = ("novel", "near_dup", "close")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default=os.path.join(
        HERE, "out_ext/tdc/leakage_attribution.json"))
    ap.add_argument("--out", dest="out", default=os.path.join(
        HERE, "out_ext/tdc/leakage_confound_check.json"))
    a = ap.parse_args(argv)

    d = json.load(io.open(a.inp, encoding="utf-8"))

    # ---- 1. 补齐 pairwise 对比（v4.3 只报了 near_dup−novel）-----------------
    pairwise, points = {}, []
    for ep, v in d.items():
        g = v.get("by_group") or {}
        pairwise[ep] = {}
        for s1, s2 in (("close", "novel"), ("close", "near_dup"), ("near_dup", "novel")):
            r1 = (g.get(s1) or {}).get("r_error_median")
            r2 = (g.get(s2) or {}).get("r_error_median")
            pairwise[ep]["%s_minus_%s" % (s1, s2)] = (
                None if (r1 is None or r2 is None) else round(r1 - r2, 4))
        for s in STRATA:
            x = g.get(s) or {}
            rho = x.get("r_error_median")
            agree = x.get("all_agree_rate")
            if rho is None or agree is None:
                continue
            points.append({"endpoint": ep, "stratum": s, "n_median": x.get("n_median"),
                           "r_error": rho, "all_agree_rate": agree,
                           "all_agree_and_wrong": x.get("all_agree_and_wrong_rate")})

    # ---- 2. H1：记忆驱动（越近 ρ 越高）------------------------------------
    from scipy.stats import spearmanr
    h1 = {}
    for ep, v in pairwise.items():
        cv = v.get("close_minus_novel")
        h1[ep] = {
            "close_minus_novel": cv,
            "supports_memory": None if cv is None else bool(cv > 0),
            "readable": cv is not None,
        }
    readable = [k for k, v in h1.items() if v["readable"]]
    n_support = sum(1 for k in readable if h1[k]["supports_memory"])
    h1_verdict = ("supported" if readable and n_support >= max(2, len(readable) - 1)
                  else "contradicted" if readable and n_support == 0
                  else "mixed" if readable else "untestable")

    # ---- 3. H2：一致率驱动（ρ_error 由 all_agree_rate 决定）----------------
    h2 = {"n_points": len(points)}
    if len(points) >= 4:
        xs = np.array([p["all_agree_rate"] for p in points], dtype=float)
        ys = np.array([p["r_error"] for p in points], dtype=float)
        rho, pval = spearmanr(xs, ys)
        # 端点内（去掉跨端点水平差）的偏相关版本：先按端点去均值再算
        dev_x, dev_y = [], []
        for ep in {p["endpoint"] for p in points}:
            sub = [p for p in points if p["endpoint"] == ep]
            if len(sub) < 2:
                continue
            mx = np.mean([q["all_agree_rate"] for q in sub])
            my = np.mean([q["r_error"] for q in sub])
            dev_x += [q["all_agree_rate"] - mx for q in sub]
            dev_y += [q["r_error"] - my for q in sub]
        rho_w, p_w = (spearmanr(dev_x, dev_y) if len(dev_x) >= 4
                      else (float("nan"), float("nan")))
        h2.update({
            "spearman_agree_vs_rho_pooled": round(float(rho), 3),
            "p_value_pooled": float(pval),
            "spearman_agree_vs_rho_within_endpoint": (None if np.isnan(rho_w)
                                                      else round(float(rho_w), 3)),
            "p_value_within": (None if np.isnan(p_w) else float(p_w)),
            "supported": bool(rho > 0.8 and pval < 0.05),
        })
    else:
        h2.update({"supported": False, "why": "可用点不足 4 个，不能检验"})

    # ---- 4. 重判该代理的可用性 --------------------------------------------
    #  三种结局都要能说清，不许"哪个好看用哪个"：
    if h1_verdict == "supported":
        usability = {
            "code": "proxy_supports_memory",
            "statement": ("H1 在多数可读端点上成立（close > novel），代理可作支持性证据，"
                          "但仍只覆盖本框架三源，不覆盖外部三家。"),
        }
    elif h2.get("supported"):
        usability = {
            "code": "proxy_confounded_by_agreement",
            "statement": ("H1 被否，且 H2（一致率驱动）成立（ρ=%.2f, p=%.3g）："
                          "ρ_error 主要由『三源同时答对的比例』决定，"
                          "BBB 的 −0.212 是一致率下行的算术后果，"
                          "**不是**『记忆不起作用』的证据。该代理不得用于判定记忆假说。"
                          % (h2["spearman_agree_vs_rho_pooled"], h2["p_value_pooled"])),
        }
    elif h1_verdict in ("contradicted", "mixed"):
        usability = {
            "code": "proxy_unvalidated_and_negative_unexplained",
            "statement": ("**两个候选机制都不成立。** H1（记忆驱动：越近 ρ 越高）"
                          "在 %d/%d 个可读端点上**方向相反**（close−novel：%s）；"
                          "H2（一致率驱动）也不成立（ρ=%.2f, p=%.2f）。"
                          "因此 BBB 的 −0.212 **确实仍未得到解释**——"
                          "本复核**不冒充**已经解释它。"
                          "可下的唯一结论是：该代理**不具备判定力**，"
                          "归因项必须**重新置为未关闭**（而不是 v4.3 写的"
                          "『部分关闭、方向不支持』——那句把『测不出』写成了『没有』）。"
                          % (len(readable) - n_support, len(readable),
                             {k: h1[k]["close_minus_novel"] for k in readable},
                             h2.get("spearman_agree_vs_rho_pooled", float("nan")),
                             h2.get("p_value_pooled", float("nan")))),
        }
    else:
        usability = {"code": "proxy_inconclusive",
                     "statement": "证据不足以判定代理可用性；维持降级表述并标注不确定性。"}

    payload = {
        "source": os.path.relpath(a.inp, HERE).replace("\\", "/"),
        "question": ("第三轮评审 §E2：BBB 的 Δ=ρ(near_dup)−ρ(novel)=−0.212 无解释，"
                     "需要一个假设与检验"),
        "hypotheses": {
            "H1_memory_driven": "越靠近训练集，源间误差相关越高（close > novel）",
            "H2_agreement_driven": ("ρ_error 由『三源同时答对的比例』决定："
                                    "全对时三项误差相同，天然抬高 ρ"),
        },
        "points": points,
        "pairwise_delta": pairwise,
        "H1": {"per_endpoint": h1, "verdict": h1_verdict},
        "H2": h2,
        "usability": usability,
        "consequence": {
            "unresolved_closeout_v4_3": ("§4 现写『部分关闭、方向不支持原担忧』；"
                                         "本复核认为应改为『代理无效、该项仍未关闭』"),
            "allowed_phrasing": ("✅ 『近邻分层代理与源间一致率高度相关（ρ=…），"
                                 "故它不能单独区分记忆与一致率两种成因』"),
            "forbidden_phrasing": ("❌ 『已证明共享误差与数据重叠无关』；"
                                   "❌ 『Δ=−0.212 说明近邻组记忆更少』"),
        },
    }

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with io.open(a.out, "w", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False, indent=2))

    print("[e2] H1 verdict=%s  per-endpoint close−novel=%s"
          % (h1_verdict, {k: v["close_minus_novel"] for k, v in h1.items()}))
    print("[e2] H2 spearman(agree, rho)=%s p=%s -> supported=%s"
          % (h2.get("spearman_agree_vs_rho_pooled"), h2.get("p_value_pooled"),
             h2.get("supported")))
    print("[e2] usability=%s" % usability["code"])
    print("[e2] -> %s" % a.out)
    return payload


if __name__ == "__main__":
    main()
