# -*- coding: utf-8 -*-
"""bootstrap 名次区间 + 并列集合（移植自 reverse-molecular-docking E7c）。

为什么需要它
------------
本 skill 的 `reliability.can_rank()` 已经给出"什么时候才允许排名"的三条硬条件；
但**允许排名之后**，直接报"第 1/第 2/第 3"仍然过度自信——源/端点一换，名次就动。
反向 skill 的做法是：报**名次区间**，并把"胜率<0.6 的相邻候选"强制并成一个**并列集合**，
不指定单一冠军。

本模块只做后半段（区间 + 并列）；前半段（是否允许排名）由 can_rank 负责，此处复核。

方法
----
- 输入：每个分子在若干"轴/端点"上的分数（越高越好，如 desirability 的 geo_mean）。
- composite = 各轴分数的**几何平均**（与 04_decision_funnel §2 一致：几何平均被最差项主导，
  对应"不能有致命短板"的决策语义；加权和会被长板补偿）。
- 对"轴"做 bootstrap（有放回重采样轴），每个 replicate 重算 composite 并排名；
  名次分布 → 5%/95% 分位区间。
- 成对胜率：replicate 中 A 优于 B 的比例；落在 [thr_low, thr_high]（默认 0.4–0.6）
  → 判并列。

重要边界
--------
- **bootstrap 的是"轴/端点的选择不确定性"，不是"分子抽样"**。它回答"换一批端点，
  名次稳不稳"，不回答"换一批分子"。后者需要外部候选集。
- 默认 **refuse**：n<30 或未提供可信簇占比时拒绝排名（`--force` 才计算，且产物标 OVERRIDE）。
"""

import csv
import io
import os
import random

EPS = 1e-6


def _f(v):
    try:
        x = float(v)
        return x if x == x and x not in (float("inf"), float("-inf")) else None
    except (TypeError, ValueError):
        return None


def _median(vals):
    s = sorted(vals)
    n = len(s)
    if n == 0:
        return None
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def _pct(vals, q):
    s = sorted(vals)
    if not s:
        return None
    k = (len(s) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def _geo(vals):
    if not vals:
        return None
    v = [max(EPS, x) for x in vals]
    p = 1.0
    for x in v:
        p *= x
    return p ** (1.0 / len(v))


def build(
    rows,
    id_col="compound_id",
    group_col="axis",
    score_col="score",
    bootstrap=2000,
    thr_low=0.40,
    thr_high=0.60,
    seed=42,
    max_cluster_frac=1.0,
    max_spread=None,
):
    """返回 (result_rows, pairs_rows, status)。

    status: {"ok": bool, "reasons": [...], "n_compounds": int, "n_groups": int,
             "mode": "ranked"|"refused"|"override"}
    """
    # 透视
    table = {}
    groups_seen = set()
    for r in rows:
        cid = r.get(id_col)
        g = r.get(group_col)
        v = _f(r.get(score_col))
        if not cid or not g or v is None:
            continue
        table.setdefault(cid, {})[g] = v
        groups_seen.add(g)

    cids = sorted(table)
    groups = sorted(groups_seen)
    n_c = len(cids)
    n_g = len(groups)

    # can_rank 三条件复核（与 reliability.can_rank 同口径）
    reasons = []
    if n_c < 30:
        reasons.append("候选数 %d < 30" % n_c)
    if max_cluster_frac >= 0.30:
        reasons.append(
            "最大同类簇占比 %.0f%% >= 30%%（未提供可信值则默认 100%%）"
            % (max_cluster_frac * 100)
        )
    if max_spread is not None and max_spread > 0.30:
        reasons.append("跨源极差 %.2f 过大" % max_spread)
    allowed = not reasons
    status = dict(
        ok=allowed,
        reasons=reasons,
        n_compounds=n_c,
        n_groups=n_g,
        mode="ranked" if allowed else "refused",
    )

    if n_g < 2:
        status["mode"] = "refused"
        status["reasons"].append("可用轴数 %d < 2，无法 bootstrap" % n_g)
        return [], [], status

    rng = random.Random(seed)
    ranks = {c: [] for c in cids}
    comps = {c: [] for c in cids}
    rep_comps = []
    for _ in range(bootstrap):
        pick = [rng.choice(groups) for _ in range(n_g)]
        # 每个分子的 composite（只用该分子有值的被选轴）
        scores = {}
        for c in cids:
            vals = [table[c][g] for g in pick if g in table[c]]
            scores[c] = _geo(vals)
        rep_comps.append(scores)
        # 排名（高分=1）；None 排最后
        order = sorted(
            cids,
            key=lambda c: (
                scores[c] is None,
                -(scores[c] if scores[c] is not None else 0),
            ),
        )
        for i, c in enumerate(order, 1):
            ranks[c].append(i)
            if scores[c] is not None:
                comps[c].append(scores[c])

    out = []
    for c in cids:
        rr = ranks[c]
        cc = comps[c]
        out.append(
            dict(
                compound_id=c,
                n_groups=len(table[c]),
                mean_composite=round(sum(cc) / len(cc), 4) if cc else "",
                median_rank=round(_median(rr), 2) if rr else "",
                rank_p05=round(_pct(rr, 0.05), 2) if rr else "",
                rank_p95=round(_pct(rr, 0.95), 2) if rr else "",
                note="",
            )
        )
    out.sort(key=lambda r: (r["median_rank"] if r["median_rank"] != "" else 1e9))

    # 成对胜率 -> 并列集合（union-find）。**按每 replicate 的 composite 算**，
    # 相等记 0.5 胜——否则两个完全相同的分子会因排序位置不同被误判为非并列。
    parent = {c: c for c in cids}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    pairs = []
    for i in range(len(cids)):
        for j in range(i + 1, len(cids)):
            a, b = cids[i], cids[j]
            wins = 0.0
            nrep = 0
            for sc in rep_comps:
                ca, cb = sc.get(a), sc.get(b)
                if ca is None or cb is None:
                    continue
                nrep += 1
                if ca > cb:
                    wins += 1.0
                elif ca == cb:
                    wins += 0.5
            win = wins / nrep if nrep else 0.0
            tie = thr_low <= win <= thr_high
            pairs.append(
                dict(a=a, b=b, win_rate=round(win, 3), tie="Y" if tie else "N")
            )
            if tie:
                parent[find(a)] = find(b)
    # 并列组标号
    groups_map = {}
    for c in cids:
        root = find(c)
        groups_map.setdefault(root, []).append(c)
    tie_id = {}
    idx = 1
    for root, mem in groups_map.items():
        if len(mem) > 1:
            for c in mem:
                tie_id[c] = "T%d" % idx
            idx += 1
    for r in out:
        r["tie_group"] = tie_id.get(r["compound_id"], "")
        if r["tie_group"]:
            r["note"] = "与同业并列（胜率<%.2f），不得指定单一冠军" % thr_high

    return out, pairs, status


def write_result(path, rows):
    cols = [
        "compound_id",
        "n_groups",
        "mean_composite",
        "median_rank",
        "rank_p05",
        "rank_p95",
        "tie_group",
        "note",
    ]
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with io.open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return len(rows)


def write_pairs(path, rows):
    cols = ["a", "b", "win_rate", "tie"]
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with io.open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return len(rows)
