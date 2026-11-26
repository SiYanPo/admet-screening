# -*- coding: utf-8 -*-
"""落地问题② + 盲区1 + 追问2：基线时效性与洗脱（Temporal Decay & Washout）。

解决的问题：
- 2019 年的历史预测基线本身是"垃圾"（旧模型），强行配对会把合法升级误判为漂移。
- 新骨架分子在历史基线里没有记录 → 无法配对。
- 弱活性/噪声历史数据污染配对。

设计四件套：
1. decay_weight(age_days, half_life)：指数时间衰减权重。
2. admit_baseline_entry()：基线准入——按时间、噪声水平、来源可信度决定是否准入。
3. select_paired_baseline()：配对基线选择——过滤 stale、按权重、返回 warmup 状态。
4. washout()：基线洗脱——用当前金标准重跑覆盖被污染的历史。

纯标准库。
"""

from __future__ import annotations
import math
from datetime import datetime, timezone

DAY = 86400.0


def _parse_ts(ts):
    """接受 ISO 字符串或 datetime，返回 epoch 秒。"""
    if isinstance(ts, datetime):
        dt = ts
    else:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def decay_weight(age_days, half_life_days=365.0):
    """指数衰减权重：age=0→1, age=half_life→0.5。half_life<=0 视为不衰减。"""
    if half_life_days <= 0:
        return 1.0
    return 0.5 ** (float(age_days) / float(half_life_days))


def is_stale(ts, now, max_age_days=365):
    """超过 max_age_days 的历史标记 stale（不参与配对）。"""
    age_days = (now - _parse_ts(ts)) / DAY
    return age_days > max_age_days, age_days


# ---- 基线准入 ----
NOISE_THRESHOLD = 0.35  # 相对噪声（SD/|mean|）超过此值视为弱活性/噪声大


def admit_baseline_entry(
    value,
    ts,
    now,
    *,
    source_noise=None,
    max_age_days=365,
    min_source_reliability=0.5,
    source_reliability=1.0,
):
    """单条基线记录的准入判定。返回 dict(admitted, reason, weight)。

    准入条件（全部满足才准入）：
      1) 未过期（age <= max_age_days）
      2) 来源可信度 >= min（如 ChEMBL 弱活性 assay 可信度低）
      3) 若给了 source_noise（SD/|mean|），不得超阈值（噪声太大）
    """
    stale, age_days = is_stale(ts, now, max_age_days)
    if stale:
        return {
            "admitted": False,
            "reason": "stale_age_%.0fd" % age_days,
            "age_days": round(age_days, 1),
            "weight": 0.0,
        }
    if source_reliability < min_source_reliability:
        return {
            "admitted": False,
            "reason": "source_reliability_low",
            "source_reliability": source_reliability,
            "weight": 0.0,
        }
    if source_noise is not None and source_noise > NOISE_THRESHOLD:
        return {
            "admitted": False,
            "reason": "noise_too_high",
            "source_noise": source_noise,
            "weight": 0.0,
        }
    w = decay_weight(age_days)
    return {
        "admitted": True,
        "reason": "ok",
        "age_days": round(age_days, 1),
        "weight": round(w, 4),
    }


def select_paired_baseline(
    baseline_map, now, *, max_age_days=365, min_total_weight=0.30, min_entries=1
):
    """为一个 (source, cluster, endpoint) 的 baseline_map 选出可用于配对的记录。

    baseline_map: {mol_id: [ (value, ts, meta), ... ]} 或 {mol_id: [{value,ts,...}]}
    返回 {mol_id: {weighted_median, total_weight, admitted_n, stale_n, status}}

    status:
      - "usable"          可用配对
      - "warmup_required" 权重不足（全是老数据/新分子）→ 需重新积累或洗脱
      - "no_data"         完全没有该分子记录
    """
    out = {}
    for mid, entries in (baseline_map or {}).items():
        admitted = []
        stale_n = 0
        for e in entries:
            val, ts, meta = _unpack(e)
            gate = admit_baseline_entry(
                val,
                ts,
                now,
                max_age_days=max_age_days,
                source_noise=meta.get("source_noise"),
                source_reliability=meta.get("source_reliability", 1.0),
            )
            if gate["admitted"]:
                admitted.append((val, gate["weight"]))
            else:
                stale_n += 1
        total_w = sum(w for _, w in admitted)
        if not admitted:
            out[mid] = {
                "status": "warmup_required",
                "total_weight": 0.0,
                "admitted_n": 0,
                "stale_n": stale_n,
                "note": "无可用基线（全过期/噪声大）",
            }
            continue
        if total_w < min_total_weight or len(admitted) < min_entries:
            out[mid] = {
                "status": "warmup_required",
                "total_weight": round(total_w, 3),
                "admitted_n": len(admitted),
                "stale_n": stale_n,
                "note": "权重不足（%0.2f<%0.2f）" % (total_w, min_total_weight),
            }
            continue
        out[mid] = {
            "status": "usable",
            "weighted_median": _wmedian(admitted),
            "total_weight": round(total_w, 4),
            "admitted_n": len(admitted),
            "stale_n": stale_n,
            "effective_n": round(total_w, 2),
        }
    return out


def _unpack(e):
    if isinstance(e, dict):
        return e["value"], e["ts"], e
    # tuple (value, ts, meta)
    val, ts = e[0], e[1]
    meta = e[2] if len(e) > 2 else {}
    return val, ts, meta


def _wmedian(pairs):
    """加权中位数。"""
    pairs = sorted(pairs, key=lambda x: x[0])
    total = sum(w for _, w in pairs)
    if total <= 0:
        return pairs[len(pairs) // 2][0]
    cum = 0.0
    for val, w in pairs:
        cum += w
        if cum >= total / 2.0:
            return round(val, 6)
    return round(pairs[-1][0], 6)


# ---- 基线洗脱（Washout）----
def washout(baseline_map, gold_runs, now, *, min_gold_agreement=0.90):
    """用当前金标准分子重跑结果覆盖被污染的历史。

    baseline_map: {mol_id: [entries]}
    gold_runs:    {mol_id: [(value, ts), ...]} 当前金标准重跑值
    返回 (new_baseline_map, report)

    逻辑：
      - 金标准里有、且多次重跑一致（CV/相对差 <= 1-min_agreement）的分子 →
        用金标准值**替换**历史（清污染）。
      - 金标准里没有的分子 → 保留历史，但标记 needs_washout=True。
    """
    new_map = {}
    replaced, kept, needs = [], [], []
    for mid, entries in (baseline_map or {}).items():
        runs = gold_runs.get(mid)
        if runs and len(runs) >= 2:
            vals = [v for v, _ in runs]
            mean = sum(vals) / len(vals)
            spread = (max(vals) - min(vals)) / (abs(mean) + 1e-9)
            if spread <= (1.0 - min_gold_agreement):
                # 金标准稳定 → 用它覆盖
                ts = max(t for _, t in runs)
                new_map[mid] = [
                    (mean, ts, {"source": "gold_washout", "source_reliability": 1.0})
                ]
                replaced.append(mid)
                continue
        # 无金标准或金标准不稳定 → 保留历史但要标记
        new_map[mid] = list(entries)
        needs.append(mid)
    report = {
        "replaced": replaced,
        "needs_washout": needs,
        "n_replaced": len(replaced),
        "n_kept": len(new_map) - len(replaced),
    }
    return new_map, report
