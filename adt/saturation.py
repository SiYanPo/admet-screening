# -*- coding: utf-8 -*-
"""全端点饱和扫描（QA gate #11）。

背景（本项目实测）：ADMETlab 的 122 列里有 12 个毒理端点我们从未读过，
读完后发现 7 个是饱和的——
  OATP1B1 0.986–0.99998（14/14 阳）、OATP1B3 0.987–0.99999（14/14 阳）、
  BCRP 0.009–0.307（0/14）、BSEP 0.0015–0.285（0/14）、MRP1 0.0008–0.042（0/14）、
  NR-ER 0.623–0.949（14/14 阳）、NR-AhR 0.003–0.155（0/14）。
只有 NR-AR-LBD / SR-p53 / SR-ARE 有区分度。
=> 饱和不是 DILI/Ames 的个例，整条安全层都可能域外。

判据（写死，不靠人肉看）：
  分类/概率列（值都在 [0,1]）：同向比例 ≥ 0.90 判 saturated；极差 < 0.05 判 saturated
  连续列：极差 / 中位数绝对值 < 0.05（相对）或极差 < 0.1（绝对）判 saturated
  另附物理越界检查（logPapp、logS、logP 的量纲常识）

**三种判定必须分开（这是本模块最重要的一条设计）**
  usable             有区分度：可用于排序，也可用于阈值
  saturated_in_set   **在本集合内无区分度**：不能排序，但**绝对阈值仍然有效**
                     （例：DILI 14/14 都 >0.5，排序无意义，但"这 14 个都该报红旗"
                      这个结论仍然成立）
  invalid            物理越界 / 数值不可能：连阈值都不能用

把 saturated 和 invalid 混为一谈会犯实质错误——本项目的 DILI 就是 saturated 而不是
invalid，第一版扫描脚本把它们合并成"不可用于决策"，会把一个正确的红旗结论一起丢掉。
"""

import csv
import io
import math

PROB_HI = 0.90  # 同向比例阈值
PROB_MIN_RANGE = 0.05  # 概率列最小极差
NUM_REL_RANGE = 0.05  # 连续列相对极差阈值
NUM_ABS_RANGE = 0.10  # 连续列绝对极差阈值

# 物理边界（超出直接判错，不做平均）
PHYS_BOUNDS = {
    "caco2": (-8.0, -3.0),
    "logpapp": (-8.0, -3.0),
    "mdck": (-8.0, -3.0),
    "logs": (-14.0, 2.0),
    "solubility": (-14.0, 2.0),
    "logp": (-5.0, 10.0),
    "clogp": (-5.0, 10.0),
}

SKIP_COLS = {
    "raw_smiles",
    "smiles",
    "name",
    "ID",
    "id",
    "compound_id",
    "mol",
    "canonical_smiles",
    "inchi",
    "inchikey",
}


def _try_float(v):
    try:
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _phys_check(col, lo, hi, median=None):
    """只在"这一列确实是该物理量、且单位对得上"时才判越界。

    坑（实测两次）：
      1) ADMETlab 的 MDCK 列单位是 1e-6 cm/s（~7e-6），而边界表按 log Papp 写，
         `hi > -3` 对 1.1e-5 成立（因为 1e-5 比 -3 大），会把正常值判成 invalid。
      2) 只删掉 MDCK 不够——任何源对同一端点用的单位都可能不同。
    所以加一条量纲守卫：**先看中位数数量级**。log 类量的典型量级 |v| ≥ 0.5，
    若 |median| < 0.5 就认为不是 log 单位族，直接跳过边界检查。
    """
    key = col.lower()
    for k, (a, b) in PHYS_BOUNDS.items():
        if k in key:
            if median is None or abs(median) < 0.5:
                return True  # 非线性/不同单位族，不做边界判定
            if lo < a or hi > b:
                return False
    return True


MIN_NUMERIC = 3  # 少于 3 个数值无法判饱和；**必须显式报告缺席，而不是静默跳过**


def scan(rows, cols=None, diag=None):
    """rows: list[dict]。返回 [{endpoint, n, n_numeric, min, max, frac_positive, verdict, reason}]

    diag: 传入 list 时追加"无法判定"的列（<3 个数值）——C57（评估 P1 附带）：
    此前 <3 样本直接 continue，小批量筛选时 QA gate #11 静默缺席零告警。
    """
    if not rows:
        return []
    cols = cols or [c for c in rows[0].keys() if c not in SKIP_COLS]
    out = []
    for c in cols:
        vals = [_try_float(r.get(c)) for r in rows]
        num = [v for v in vals if v is not None]
        if len(num) < MIN_NUMERIC:
            if diag is not None:
                diag.append(
                    dict(
                        endpoint=c,
                        n_numeric=len(num),
                        reason="数值 < %d 个，无法判饱和（该端点在本批缺席）"
                        % MIN_NUMERIC,
                    )
                )
            continue
        lo, hi = min(num), max(num)
        rng = hi - lo
        is_prob = all(0.0 <= v <= 1.0 for v in num)
        rec = dict(
            endpoint=c,
            n=len(vals),
            n_numeric=len(num),
            min=round(lo, 6),
            max=round(hi, 6),
            frac_positive="",
            verdict="",
            reason="",
        )

        # 物理越界优先
        med = sorted(num)[len(num) // 2]
        if "percentile" in c.lower():
            rec["verdict"] = (
                "usable"  # 百分位列是排名信息(0-100)，非物理量，跳过边界与饱和判定（C47）
            )
            continue
        if not _phys_check(c, lo, hi, med):
            rec["verdict"] = "invalid"
            rec["reason"] = "数值越出物理边界（%s）" % c
            out.append(rec)
            continue

        if is_prob:
            frac = sum(1 for v in num if v > 0.5) / len(num)
            rec["frac_positive"] = round(frac, 3)
            if frac >= PROB_HI or frac <= 1 - PROB_HI:
                rec["verdict"] = "saturated_in_set"
                rec["reason"] = (
                    "%.0f%% 同向（>0.5 占 %.0f%%）：不能排序，"
                    "绝对阈值仍有效" % (max(frac, 1 - frac) * 100, frac * 100)
                )
            elif rng < PROB_MIN_RANGE:
                rec["verdict"] = "saturated_in_set"
                rec["reason"] = "概率极差 %.3f < %.2f：不能排序" % (rng, PROB_MIN_RANGE)
            else:
                rec["verdict"] = "usable"
                rec["reason"] = "有区分度（极差 %.3f）" % rng
        else:
            mid = abs(sum(num) / len(num))
            rel = rng / mid if mid > 1e-9 else float("inf")
            if rel < NUM_REL_RANGE or rng < NUM_ABS_RANGE:
                rec["verdict"] = "saturated_in_set"
                rec["reason"] = (
                    "相对极差 %.3f（绝对 %.3f）：不能排序，"
                    "绝对阈值仍有效" % (rel, rng)
                )
            else:
                rec["verdict"] = "usable"
                rec["reason"] = "有区分度（相对极差 %.3f）" % rel
        out.append(rec)
    out.sort(key=lambda r: (r["verdict"] != "saturated_in_set", r["endpoint"]))
    return out


def load_wide(path, name_col=None):
    with io.open(path, encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    return rows


def write_report(path, recs):
    cols = [
        "endpoint",
        "n",
        "n_numeric",
        "min",
        "max",
        "frac_positive",
        "verdict",
        "reason",
    ]
    with io.open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(recs)
    return len(recs)


def blocked_endpoints(recs):
    """**连绝对阈值都不能用**的端点（只有 invalid）。"""
    return {r["endpoint"] for r in recs if r["verdict"] == "invalid"}


def non_ranking_endpoints(recs):
    """不能用于排序、但绝对阈值仍有效的端点（saturated_in_set）。"""
    return {r["endpoint"] for r in recs if r["verdict"] == "saturated_in_set"}
