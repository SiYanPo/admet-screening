# -*- coding: utf-8 -*-
"""工作包 A：**真实外部源之间的相关性 ρ**（不是"两个基线之间"）。

### 为什么这个模块能闭环 A（2026-10-30 核实）

v3.4/v3.5 一直把 A 写成"待外部源可达"，因为当时只有两个 Ridge 基线之间的 ρ（0.298），
评审正确指出：那证明的是"不同分子表示会分歧"，**不是**"ADMETlab3 与 ADMET-AI 不独立"。

核实工作区历史产物后发现，**同一批 14 个分子的两个真实源预测已经存在**：
- `admet-pipeline/web_results/admetlab14_v5/admetlab3_raw.csv`（14 行）
- `admet-pipeline/web_results/admetai14_v23/admet_ai_raw.csv`（14 行）
实测：**14/14 SMILES 完全重合**，共享列 18 个（15 个端点 + Lipinski + QED + smiles）：
DILI、hERG、NR-AR、NR-AR-LBD、NR-AhR、NR-Aromatase、NR-ER、NR-ER-LBD、
NR-PPAR-gamma、SR-ARE、SR-ATAD5、SR-HSE、SR-MMP、SR-p53、logP。

所以 A 的真值**不需要新调用**，直接用这两份算真实源 ρ。

### 指标与解读（关键：ρ 高/低意味着相反的东西）

- **ρ 高（→1）**：两源高度冗余 → 在计票时**不应算 2 个独立方法组**（C77 的"两票半"更保守才对）。
- **ρ 低（→0）**：两源携带不同信息 → 可作为独立证据，但**分歧本身**就是弃权信号。
- 因此本模块**不预设"低 ρ 更好"**，而是把 ρ 交给下游：ρ 决定独立性分组，不决定"哪个源对"。

### 诚实边界

1. n=14（同一化学类：肉桂酰糖苷）——ρ 的置信区间很宽，必须 bootstrap CI 一起报，
   不得把单点 ρ 当精确值。这里问的是"**在本类内**两源是否独立"，不是全局独立性。
2. 二元端点的 Spearman 会因大量并列而粗糙；同时报"0.5 阈值下的一致率"作为补充。
3. 两份文件来自不同时间的网页抓取（admetlab14_v5 / admetai14_v23），
   版本可能不同；产物必须记录 file 路径与 mtime，供审计。
"""

import csv
import io
import math
import os
import random


def _f(v):
    if v is None:
        return None
    s = str(v).strip().strip('"').strip("'")
    if s in ("", "-", "nan", "NaN", "None", "N/A", "NA"):
        return None
    try:
        x = float(s)
        return x if x == x and abs(x) != float("inf") else None
    except (TypeError, ValueError):
        return None


def load_wide(path, id_candidates=("smiles", "SMILES", "raw_smiles", "compound_id")):
    """读宽表，返回 (rows, id_col)。"""
    with io.open(path, encoding="utf-8-sig") as fh:
        rdr = csv.DictReader(fh)
        rows = list(rdr)
        cols = rdr.fieldnames or []
    id_col = None
    for c in id_candidates:
        if c in cols:
            id_col = c
            break
    if id_col is None:
        raise SystemExit(
            "[source-rho] %s 找不到 id 列（试过 %s）" % (path, id_candidates)
        )
    return rows, id_col


def _ranks(vals):
    """平均秩（处理并列）。"""
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    ranks = [0.0] * len(vals)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _pearson(x, y):
    n = len(x)
    if n < 3:
        return None
    mx = sum(x) / n
    my = sum(y) / n
    sxx = sum((a - mx) ** 2 for a in x)
    syy = sum((b - my) ** 2 for b in y)
    if sxx <= 0 or syy <= 0:
        return None
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y))
    return sxy / math.sqrt(sxx * syy)


def spearman(x, y):
    return _pearson(_ranks(x), _ranks(y))


def bootstrap_ci(x, y, B=1000, seed=42, alpha=0.05):
    """对配对样本做 bootstrap，返回 (lo, hi)。"""
    n = len(x)
    if n < 4:
        return (None, None)
    rnd = random.Random(seed)
    vals = []
    for _ in range(B):
        idx = [rnd.randrange(n) for _ in range(n)]
        xx = [x[i] for i in idx]
        yy = [y[i] for i in idx]
        r = spearman(xx, yy)
        if r is not None:
            vals.append(r)
    if len(vals) < 20:
        return (None, None)
    vals.sort()
    lo = vals[int(alpha / 2 * (len(vals) - 1))]
    hi = vals[int((1 - alpha / 2) * (len(vals) - 1))]
    return (round(lo, 4), round(hi, 4))


def compare(
    path_a,
    path_b,
    endpoints=None,
    exclude=("smiles", "raw_smiles", "compound_id", "Lipinski", "QED"),
    label_a="source_A",
    label_b="source_B",
):
    """按 SMILES 对齐，逐端点算 ρ / 一致率 / 平均绝对差。"""
    ra, ia = load_wide(path_a)
    rb, ib = load_wide(path_b)
    mapa = {(r.get(ia) or "").strip(): r for r in ra if r.get(ia)}
    mapb = {(r.get(ib) or "").strip(): r for r in rb if r.get(ib)}
    keys = sorted(set(mapa) & set(mapb))

    cols_a = list(ra[0].keys()) if ra else []
    cols_b = list(rb[0].keys()) if rb else []
    shared = [c for c in cols_a if c in cols_b and c not in exclude]
    if endpoints:
        shared = [c for c in shared if c in endpoints]

    rows = []
    for ep in shared:
        x, y = [], []
        for k in keys:
            va, vb = _f(mapa[k].get(ep)), _f(mapb[k].get(ep))
            if va is None or vb is None:
                continue
            x.append(va)
            y.append(vb)
        if len(x) < 3:
            continue
        rho = spearman(x, y)
        lo, hi = bootstrap_ci(x, y)
        r = _pearson(x, y)
        agree = sum(1 for a, b in zip(x, y) if (a >= 0.5) == (b >= 0.5)) / float(len(x))
        mad = sum(abs(a - b) for a, b in zip(x, y)) / float(len(x))
        rows.append(
            dict(
                endpoint=ep,
                n_pairs=len(x),
                spearman=round(rho, 4) if rho is not None else None,
                ci_lo=lo,
                ci_hi=hi,
                pearson=round(r, 4) if r is not None else None,
                class_agreement=round(agree, 4),
                mean_abs_diff=round(mad, 6),
            )
        )
    rhos = [r["spearman"] for r in rows if r["spearman"] is not None]
    rhos_sorted = sorted(rhos)
    median = (
        (
            rhos_sorted[len(rhos_sorted) // 2]
            if len(rhos_sorted) % 2
            else 0.5
            * (
                rhos_sorted[len(rhos_sorted) // 2 - 1]
                + rhos_sorted[len(rhos_sorted) // 2]
            )
        )
        if rhos
        else None
    )
    return dict(
        rows=rows,
        n_shared_endpoints=len(rows),
        n_compounds=len(keys),
        n_smiles_a=len(mapa),
        n_smiles_b=len(mapb),
        median_spearman=round(median, 4) if median is not None else None,
        files=dict(a=os.path.abspath(path_a), b=os.path.abspath(path_b)),
        labels=dict(a=label_a, b=label_b),
    )


def verdict(res, high=0.8, low=0.5):
    """给一句可直接进论文的判读（不预设方向）。"""
    m = res.get("median_spearman")
    if m is None:
        return "端点不足，无法判定"
    if m >= high:
        return (
            "中位 ρ=%.3f ≥ %.2f：两源高度冗余——**计票时不应算 2 个独立方法组**，"
            "C77 的保守分组必须保留" % (m, high)
        )
    if m <= low:
        return (
            "中位 ρ=%.3f ≤ %.2f：两源携带不同信息——可作为独立证据，"
            "但源间分歧本身即是弃权信号（spread 守卫）" % (m, low)
        )
    return (
        "中位 ρ=%.3f 落在 [%.2f, %.2f] 之间：部分冗余——按端点分别决定独立性分组，"
        "不得全局一刀切" % (m, low, high)
    )


def write(outdir, res):
    os.makedirs(outdir, exist_ok=True)
    p1 = os.path.join(outdir, "source_rho_by_endpoint.csv")
    cols = [
        "endpoint",
        "n_pairs",
        "spearman",
        "ci_lo",
        "ci_hi",
        "pearson",
        "class_agreement",
        "mean_abs_diff",
    ]
    with io.open(p1, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in res["rows"]:
            w.writerow(r)
    p2 = os.path.join(outdir, "source_rho_note.md")
    L = [
        "# 真实源间相关性 ρ（工作包 A）",
        "",
        "- 源 A: %s" % res["files"]["a"],
        "- 源 B: %s" % res["files"]["b"],
        "- 对齐分子数: %d（A 有 %d / B 有 %d）"
        % (res["n_compounds"], res["n_smiles_a"], res["n_smiles_b"]),
        "- 共享端点: %d（剔除 Lipinski/QED 等聚合列）" % res["n_shared_endpoints"],
        "- **中位 Spearman ρ: %s**" % res["median_spearman"],
        "",
        "| 端点 | n | Spearman | 95%CI | Pearson | 类别一致率 | 平均绝对差 |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in res["rows"]:
        L.append(
            "| %s | %d | %s | [%s, %s] | %s | %s | %s |"
            % (
                r["endpoint"],
                r["n_pairs"],
                r["spearman"],
                r["ci_lo"],
                r["ci_hi"],
                r["pearson"],
                r["class_agreement"],
                r["mean_abs_diff"],
            )
        )
    L += [
        "",
        "**判读**",
        "",
        verdict(res),
        "",
        '> n=14（同一化学类），CI 很宽——只用于回答"**在本类内**两源是否独立"，',
        "> 不得外推为全局独立性，也不得把单点 ρ 当精确值。",
    ]
    with io.open(p2, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    return p1, p2
