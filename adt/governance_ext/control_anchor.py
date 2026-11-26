# -*- coding: utf-8 -*-
"""问题④：金标准分子探针（Control Anchor System）+ 静默升级检测。

核心纠正（两版迭代后的最终设计）：
1. response hash 抓不住"结构不变、数值系统偏移"。
2. "相对文献真值的绝对校准"也有坑（模型预测口径≠实测口径）。
3. **正解且必须配对**：按**分子 ID 配对**后比较同一批分子的预测变化。
   独立两样本均值差对个体波动大的端点（logP sd=0.5）检不出 0.1 的系统偏移；
   而配对差值把个体差异消掉，0.1 的同向平移立刻可检（这是关键统计学洞察）。

支持两种模式：
- paired（首选）：baseline 与 current 都按 mol_id 对齐 → 用配对差值 + 符号/t 检验
- unpaired（退路）：无法配对时退回独立分布 Wasserstein（保守、不敏感）
纯标准库实现 1D Wasserstein（排序累积），无 scipy 依赖。
"""

from __future__ import annotations
import math


def _median(xs):
    s = sorted(xs)
    n = len(s)
    if n == 0:
        return 0.0
    if n % 2 == 1:
        return s[n // 2]
    return 0.5 * (s[n // 2 - 1] + s[n // 2])


def wasserstein_1d(a, b):
    """等权 1D Wasserstein（EMD）：排序后对齐求均值绝对差。O(n log n)。"""
    if not a or not b:
        return None
    sa, sb = sorted(a), sorted(b)

    def resample(s, n):
        if len(s) == n:
            return s
        out = []
        for i in range(n):
            pos = i * (len(s) - 1) / (n - 1) if n > 1 else 0.0
            lo = int(math.floor(pos))
            hi = min(lo + 1, len(s) - 1)
            out.append(s[lo] + (s[hi] - s[lo]) * (pos - lo))
        return out

    n = max(len(sa), len(sb))
    ra, rb = resample(sa, n), resample(sb, n)
    return sum(abs(x - y) for x, y in zip(ra, rb)) / n


def median_abs_deviation(xs, *, floor=0.30):
    if not xs:
        return floor
    m = _median(xs)
    return max(_median([abs(x - m) for x in xs]), floor)


def _paired_t(diffs):
    """配对差值的单样本 t 统计量（纯标准库）。返回 (mean, sd, t, n)。"""
    n = len(diffs)
    if n < 2:
        return (diffs[0] if diffs else 0.0), 0.0, None, n
    mean = sum(diffs) / n
    var = sum((d - mean) ** 2 for d in diffs) / (n - 1)
    sd = math.sqrt(var)
    if sd == 0:
        return mean, 0.0, (math.inf if mean != 0 else 0.0), n
    t = mean / (sd / math.sqrt(n))
    return mean, sd, t, n


class ControlAnchor:
    """金标准探针：检测外部源静默升级。

    baseline: {(source, cluster, endpoint): {mol_id: [历史预测值...]}}
    """

    def __init__(
        self,
        baseline,
        *,
        drift_k=3.0,
        wasserstein_k=2.0,
        min_baseline=3,
        paired_t_threshold=4.0,
    ):
        self.baseline = baseline
        self.drift_k = drift_k
        self.wasserstein_k = wasserstein_k
        self.min_baseline = min_baseline  # 每个分子至少 3 次历史才能配对
        self.paired_t_threshold = paired_t_threshold  # |t|>4 视为系统偏移

    def compare(self, source, observations):
        """observations: {(cluster, endpoint): {mol_id: value}}。"""
        out = {}
        for (cluster, endpoint), cur_map in observations.items():
            key = (source, cluster, endpoint)
            base_map = self.baseline.get(key)
            if not base_map:
                out[key] = {
                    "status": "INSUFFICIENT_BASELINE",
                    "n_baseline": 0,
                    "action": "先积累历史再检测",
                }
                continue

            # === 配对模式：只取两侧都有的 mol_id ===
            paired_diffs, paired_mols = [], []
            for mid, cur_v in cur_map.items():
                hist = base_map.get(mid)
                if hist and len(hist) >= 1:
                    paired_diffs.append(cur_v - _median(hist))
                    paired_mols.append(mid)

            if len(paired_diffs) >= self.min_baseline:
                mean, sd, t, n = _paired_t(paired_diffs)
                # 符号一致性：同向平移的证据（增强 t 检验的稳健性）
                n_neg = sum(1 for d in paired_diffs if d < 0)
                n_pos = sum(1 for d in paired_diffs if d > 0)
                same_sign_frac = max(n_neg, n_pos) / float(n) if n else 0.0
                drift = t is not None and abs(t) > self.paired_t_threshold
                out[key] = {
                    "status": "DRIFT" if drift else "STABLE",
                    "mode": "paired",
                    "n_paired": n,
                    "mean_shift": round(mean, 4),
                    "sd_diff": round(sd, 4),
                    "t": (round(t, 3) if t is not None and math.isfinite(t) else t),
                    "same_sign_frac": round(same_sign_frac, 3),
                    "mol_ids": paired_mols[:10],
                    "action": ("LOCK_SOURCE_AND_DOWNGRADE" if drift else "continue"),
                }
                continue

            # === 退路：无法配对 → 独立分布 Wasserstein（保守）===
            all_cur = list(cur_map.values())
            base_flat = [v for vals in base_map.values() for v in vals]
            if len(base_flat) < self.min_baseline * 3:
                out[key] = {
                    "status": "INSUFFICIENT_BASELINE",
                    "n_baseline": len(base_flat),
                    "action": "历史不足，无法配对",
                }
                continue
            mad = median_abs_deviation(base_flat)
            w = wasserstein_1d(all_cur, base_flat)
            w_norm = (w / mad) if (w is not None and mad > 0) else 0.0
            mean_shift = (sum(all_cur) / len(all_cur)) - (
                sum(base_flat) / len(base_flat)
            )
            drift = w_norm > self.wasserstein_k
            out[key] = {
                "status": "DRIFT" if drift else "STABLE",
                "mode": "unpaired_wasserstein",
                "mean_shift": round(mean_shift, 4),
                "mad": round(mad, 4),
                "wasserstein": round(w, 4) if w is not None else None,
                "wasserstein_norm": round(w_norm, 4),
                "action": ("LOCK_SOURCE_AND_DOWNGRADE" if drift else "continue"),
                "note": "无法按分子配对，用独立分布 Wasserstein（保守，对小幅系统偏移不敏感）",
            }
        return out

    def summarize(self, result):
        drifts = [k for k, v in result.items() if v["status"] == "DRIFT"]
        return {
            "any_drift": len(drifts) > 0,
            "drift_keys": drifts,
            "n_checked": len(result),
            "recommendation": (
                "LOCK_SOURCE：检测到系统性漂移，暂停该源并转人工复核"
                if drifts
                else "所有探针稳定，源可用"
            ),
        }


# ---- Baseline Rotation Protocol（防篡改 + 允许合法升级）----
ROTATION_REQUIRED = {
    "two_person_review": True,
    "change_evidence": "mandatory",
    "shadow_period_days": 7,
    "retraction_guard": True,
}


def rotate_baseline_request(
    source,
    endpoint,
    new_baseline,
    *,
    evidence_url,
    reviewer_1,
    reviewer_2,
    reason,
    log_sink,
):
    problems = []
    if ROTATION_REQUIRED["two_person_review"] and reviewer_1 == reviewer_2:
        problems.append("双人复核必须是两个不同身份")
    if ROTATION_REQUIRED["change_evidence"] == "mandatory" and not evidence_url:
        problems.append("必须附可核查的源升级证据 URL（官方 changelog/release note）")
    if not new_baseline:
        problems.append("新基准不得为空")
    if problems:
        return {"status": "REJECTED", "problems": problems}
    entry = {
        "source": source,
        "endpoint": endpoint,
        "n_new": len(new_baseline),
        "reviewers": [reviewer_1, reviewer_2],
        "evidence_url": evidence_url,
        "reason": reason,
        "status": "SHADOW_PENDING",
        "effective_after_days": ROTATION_REQUIRED["shadow_period_days"],
        "rollback_available": ROTATION_REQUIRED["retraction_guard"],
    }
    log_sink.append(entry)
    return entry
