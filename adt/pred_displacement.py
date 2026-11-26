# -*- coding: utf-8 -*-
"""工作包 C：**预测值位移**（结构扰动 → 源预测变化），并与源间分歧对照。

### 评审的核心批评（第三次核对原文）

> "你测的是'描述符标准化前后变不变'（TPSA≤11.5%、clogp≤23.7%），证明的是**标准化有效**，
> 不是'结构噪声导致源预测位移'。clogp 位移 23.7% 完全可能让一个 hERG 阈值判断翻转，
> 而你没有测这一点。"

所以本模块的输入**必须是真实源在结构变体上的预测值**，不是描述符：

    输入 long 表：compound_id, variant, endpoint, value
      - variant = original / stereo_removed / tautomer / ...
    输入参照：`source_rho` 产出的 `source_rho_by_endpoint.csv`（含 mean_abs_diff = 源间位移）

### 判据（这才是 Gate 0 必要性的证据）

对每个端点：

    struct_shift  = mean_v |pred(variant) - pred(original)|      # 结构扰动引起的位移
    source_shift  = mean |pred(sourceA) - pred(sourceB)|         # 源间本来就有的分歧
    ratio         = struct_shift / source_shift

- **ratio > 1**：结构噪声造成的预测波动**大于**两个源之间的分歧 →
  在裁决前不统一结构（Gate 0）就会把"结构歧义"误判成"源分歧"，**Gate 0 必要**。
- **ratio < 1**：结构扰动影响小于源间分歧 → Gate 0 仍然该做，但**不是最紧迫**的杠杆。
- 若某端点 struct_shift 大到跨过 PASS/FAIL 阈值（`--threshold-flip` 检查），
  单独列出——**阈值翻转比平均位移更致命**（评审原话）。

### 诚实边界

- 只比较**同一源**在变体上的预测；源间位移用的是另一份产物（source_rho），
  两者口径需一致（同端点、同单位）。单位不一致时本模块直接报错，不静默对齐。
- 变体若为 no-op（SMILES 与 original 相同），位移应为 0；非 0 说明源有随机性/缓存问题，
  会单独标出（`noop_nonzero`）。
"""

import csv
import io
import os


def _f(v):
    try:
        x = float(str(v).strip())
        return x if x == x and abs(x) != float("inf") else None
    except (TypeError, ValueError):
        return None


def load_long(path):
    """读 compound_id, variant, endpoint, value 长表。"""
    rows = []
    with io.open(path, encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            v = _f(r.get("value"))
            if v is None:
                continue
            # 2026-11-19（真值驱动实跑暴露）：ac-plan 早就把 no-op 变体标成
            # noop=Y（SMILES 与 original 完全相同，比如"互变异构规范化"后仍是原分子），
            # 但本模块从不读这一列 —— 于是一整批 no-op 变体算出 0.000000 位移，
            # 再被 verdict 解释成"结构扰动影响小于源间分歧"，一个**空转的变体集**
            # 就这样变成了一条科学结论。必须按 noop 列排除，并单独报数量。
            noop = (r.get("noop") or r.get("no_op") or "").strip().upper()
            rows.append(
                dict(
                    compound_id=(r.get("compound_id") or "").strip(),
                    variant=(r.get("variant") or "").strip(),
                    endpoint=(r.get("endpoint") or "").strip(),
                    value=v,
                    is_noop=(noop == "Y"),
                )
            )
    return rows


def load_source_shift(path):
    """读 source_rho_by_endpoint.csv -> {endpoint: mean_abs_diff}。"""
    out = {}
    if not path or not os.path.exists(path):
        return out
    with io.open(path, encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            ep = (r.get("endpoint") or "").strip()
            m = _f(r.get("mean_abs_diff"))
            rho = _f(r.get("spearman"))
            if ep:
                out[ep] = dict(
                    mean_abs_diff=m, spearman=rho, n_pairs=_f(r.get("n_pairs"))
                )
    return out


def displacement(rows, baseline_variant="original"):
    """按 (endpoint, variant) 算相对 original 的平均绝对位移。"""
    base = {}
    for r in rows:
        if r["variant"] == baseline_variant:
            base[(r["compound_id"], r["endpoint"])] = r["value"]
    agg = {}
    for r in rows:
        if r["variant"] == baseline_variant:
            continue
        b = base.get((r["compound_id"], r["endpoint"]))
        if b is None:
            continue
        key = (r["endpoint"], r["variant"])
        d = agg.setdefault(key, dict(n=0, total=0.0, maxd=0.0, nonzero=0, n_noop=0))
        if r.get("is_noop"):
            d["n_noop"] += 1  # 记数但不进位移：结构没变，位移恒为 0
            continue
        diff = abs(r["value"] - b)
        d["n"] += 1
        d["total"] += diff
        d["maxd"] = max(d["maxd"], diff)
        d["nonzero"] += 1 if diff > 1e-9 else 0
    out = []
    for (ep, var), d in sorted(agg.items()):
        out.append(
            dict(
                endpoint=ep,
                variant=var,
                n=d["n"],
                n_noop=d["n_noop"],
                noop_all=(d["n"] == 0),
                mean_abs_shift=round(d["total"] / d["n"], 6) if d["n"] else None,
                max_abs_shift=round(d["maxd"], 6),
                nonzero_frac=round(d["nonzero"] / float(d["n"]), 4) if d["n"] else None,
            )
        )
    return out


def threshold_flips(rows, thr=0.5, skip_prefixes=("logP", "logS", "logD", "Log")):
    """统计 PASS/FAIL 阈值翻转：变体把结论推到阈值的另一侧。

    评审原话："clogp 位移 23.7% 完全可能让一个 hERG 阈值判断翻转，而你没有测这一点。"
    **翻转比平均位移更致命**——平均位移 0.05 但恰好跨过阈值，结论就反了。

    返回 (per_key_count, detail_rows)；连续量纲端点（logP/logS/logD）默认跳过，
    因为对它们套 0.5 阈值没有意义（会报假翻转）。
    """
    base = {}
    for r in rows:
        if r["variant"] == "original":
            base[(r["compound_id"], r["endpoint"])] = r["value"]
    counts, detail = {}, []
    for r in rows:
        if r["variant"] == "original":
            continue
        if any(r["endpoint"].startswith(p) for p in skip_prefixes):
            continue
        if r.get("is_noop"):
            continue
        b = base.get((r["compound_id"], r["endpoint"]))
        if b is None:
            continue
        flipped = (b >= thr) != (r["value"] >= thr)
        if flipped:
            k = (r["endpoint"], r["variant"])
            counts[k] = counts.get(k, 0) + 1
            detail.append(
                dict(
                    endpoint=r["endpoint"],
                    variant=r["variant"],
                    compound_id=r["compound_id"],
                    original=round(b, 6),
                    variant_value=round(r["value"], 6),
                    delta=round(r["value"] - b, 6),
                )
            )
    return counts, detail


def compare(disp_rows, src_shift, flip_check=None):
    """把结构位移与源间位移并列，算 ratio。"""
    out = []
    for r in disp_rows:
        ep = r["endpoint"]
        s = src_shift.get(ep, {}) if src_shift else {}
        ss = s.get("mean_abs_diff")
        ratio = None
        if ss not in (None, 0) and r["mean_abs_shift"] is not None:
            ratio = r["mean_abs_shift"] / ss
        flip = None
        if flip_check:
            flip = flip_check.get((ep, r["variant"]))
        out.append(
            dict(
                r,
                source_shift=ss,
                ratio_vs_source=round(ratio, 3) if ratio is not None else None,
                threshold_flips=flip,
                **({"source_rho": s.get("spearman")} if s else {}),
            )
        )
    return out


def verdict(rows):
    """给一句可进论文的判读。"""
    if rows and all(r.get("noop_all") for r in rows):
        n_noop = sum(int(r.get("n_noop") or 0) for r in rows)
        return (
            "**没有可解释的位移**：%d 个 (端点,变体) 组合全部为 no-op 变体"
            "（SMILES 与母体相同，结构根本没变）。这不是「结构扰动不影响预测」，"
            "而是**变体没生成**——须先修变体生成（或改用 tautomer_alt），"
            "再谈 Gate 0 的紧迫性。" % len(rows)
        )
    ratios = [
        r["ratio_vs_source"] for r in rows if r.get("ratio_vs_source") is not None
    ]
    flips = [r for r in rows if r.get("threshold_flips")]
    if not ratios:
        return "缺少源间位移参照（先跑 source-rho），无法比较"
    ratios.sort()
    med = ratios[len(ratios) // 2]
    msg = "结构扰动位移 / 源间位移 的中位比 = %.2f" % med
    if med > 1:
        msg += (
            "（>1）——结构噪声造成的预测波动**大于**两源本来的分歧，"
            "不统一结构就会把「结构歧义」误读成「源分歧」，**Gate 0 必要**"
        )
    else:
        msg += "（≤1）——结构扰动的影响小于源间分歧，Gate 0 仍应做，但不是最紧迫的杠杆"
    if flips:
        msg += "；另有 %d 个 (端点,变体) 出现 **PASS/FAIL 阈值翻转**（比平均位移更致命，单独列）" % len(
            flips
        )
    return msg


def randomization_null_control(real_deltas, null_deltas, thr=0.0, z=1.96):
    """随机化零对照（评审 C9 / P8）：结构扰动位移是否显著超过随机基线。

    real_deltas：真实结构变体引起的逐分子位移（|pred(variant)-pred(original)|，
                 或描述符位移作为代理）。
    null_deltas：随机化零分布下的同期统计量（如 no-op 变体 / 标签置换 / 随机扰动）。
    阈值 thr 以上计为"发生位移/翻转"的分子占比。

    返回 rate_diff = P(真实>thr) − P(零>thr) 及其 95% Wald CI：
      CI 下界 > 0 → 结构扰动真实可检，Gate 0 必要性获统计支持；
      CI 含 0     → 与噪声无统计差异，不能据此主张 Gate 0 必要。

    诚实边界：本函数只做统计比对，不臆造源预测；真实位移须由源在变体上的
    预测值喂入（见 RISK_COVERAGE_PROTOCOL §2 / perturbation.variants）。
    """
    if not real_deltas or not null_deltas:
        return dict(
            error="real_deltas 与 null_deltas 均不可空",
            rate_diff=None,
            ci=(None, None),
            significant=None,
        )
    import math

    n_r, n_n = len(real_deltas), len(null_deltas)
    p_r = sum(1 for d in real_deltas if d > thr) / float(n_r)
    p_n = sum(1 for d in null_deltas if d > thr) / float(n_n)
    rd = p_r - p_n
    se = math.sqrt(p_r * (1 - p_r) / n_r + p_n * (1 - p_n) / n_n)
    lo, hi = rd - z * se, rd + z * se
    sig = lo > 0
    return dict(
        p_real_above=round(p_r, 4),
        p_null_above=round(p_n, 4),
        rate_diff=round(rd, 4),
        ci=(round(lo, 4), round(hi, 4)),
        significant=sig,
        n_real=n_r,
        n_null=n_n,
        conclusion=(
            "结构扰动位移显著超过随机基线（95%CI 下界>0），" "Gate 0 必要性获统计支持"
            if sig
            else "结构扰动位移与随机基线无统计差异（95%CI 含0），"
            "不能据此主张 Gate 0 必要"
        ),
    )


def write(outdir, rows, note="", flip_detail=None):
    os.makedirs(outdir, exist_ok=True)
    p1 = os.path.join(outdir, "pred_displacement.csv")
    cols = [
        "endpoint",
        "variant",
        "n",
        "mean_abs_shift",
        "max_abs_shift",
        "nonzero_frac",
        "source_shift",
        "ratio_vs_source",
        "source_rho",
        "threshold_flips",
    ]
    with io.open(p1, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    if flip_detail:
        p_flip = os.path.join(outdir, "threshold_flips.csv")
        with io.open(p_flip, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(
                fh,
                fieldnames=[
                    "endpoint",
                    "variant",
                    "compound_id",
                    "original",
                    "variant_value",
                    "delta",
                ],
                extrasaction="ignore",
            )
            w.writeheader()
            for r in flip_detail:
                w.writerow(r)
    p2 = os.path.join(outdir, "pred_displacement_note.md")
    L = [
        "# 预测值位移 vs 源间分歧（工作包 C）",
        "",
        "| 端点 | 变体 | n | 平均位移 | 最大位移 | 非零占比 | 源间位移 | 比值 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        L.append(
            "| %s | %s | %s | %s | %s | %s | %s | %s |"
            % (
                r["endpoint"],
                r["variant"],
                r["n"],
                r["mean_abs_shift"],
                r["max_abs_shift"],
                r["nonzero_frac"],
                r.get("source_shift"),
                r.get("ratio_vs_source"),
            )
        )
    if flip_detail:
        L += [
            "",
            "### 阈值翻转明细（PASS/FAIL 被推到另一侧，比平均位移更致命）",
            "",
            "| 端点 | 变体 | 化合物 | 原值 | 变体值 | Δ |",
            "|---|---|---|---|---|---|",
        ]
        for r in sorted(flip_detail, key=lambda x: -abs(x["delta"])):
            L.append(
                "| %s | %s | %s | %s | %s | %s |"
                % (
                    r["endpoint"],
                    r["variant"],
                    r["compound_id"],
                    r["original"],
                    r["variant_value"],
                    r["delta"],
                )
            )
    L += ["", "**判读**", "", verdict(rows)]
    if note:
        L += ["", note]
    with io.open(p2, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    return p1, p2
