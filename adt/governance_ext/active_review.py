# -*- coding: utf-8 -*-
"""人机回环疲劳管理：主动学习式日志复核采样（Active Learning Sampling）。

科学家不会逐条看日志。本模块把"看全部 new_blocked_only"改成
"看最有信息量的 k 条"：
  - 边界优先：|margin| 越小（越贴近分类阈值）越优先；
  - 分歧优先：new_blocked_only / old_blocked_only / error 优先于 agree；
  - 不确定性优先：模型不确定度高、簇样本少的优先；
  - 影响加权：高价值化合物升权；
  - 多样性（MMR）：同一 reason / mol_hash / cluster 降权，避免"10 条同类"；
  - 疲劳闸门：每簇最多 N 条、trivial agree 最多 1/N；
  - 自适应：人工标签回来后按簇更新 Beta/EWMA 误报估计，高误报簇优先复看。

晋升门禁用 **Wilson 上界** 而不是朴素均值：3 条全对的样本不能证明
误报率 <5%（上界仍很高），从统计上堵住"小样本放行"。
"""

from __future__ import annotations

import math
import random
from collections import Counter, defaultdict


def wilson_interval(k, n, z=1.96):
    """二项比例 Wilson 区间；k=误报数，n=复核数。"""
    if n <= 0:
        return {"lower": 0.0, "upper": 1.0, "n": 0}
    p = k / n
    den = 1 + z * z / n
    center = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return {
        "lower": max(0.0, center - half),
        "upper": min(1.0, center + half),
        "p": p,
        "n": n,
    }


AB_PRIORITY = {
    "error": 1.30,
    "new_blocked_only": 1.00,
    "old_blocked_only": 0.80,
    "no_baseline": 0.35,
    "agree": 0.05,
}


class ActiveReviewSampler:
    def __init__(
        self,
        *,
        max_per_reason=2,
        agree_fraction=0.1,
        boundary_scale=2.0,
        adaptive_decay=0.8,
        exploration_fraction=0.12,
        rng_seed=20261122,
    ):
        self.max_per_reason = max_per_reason
        self.agree_fraction = agree_fraction
        self.boundary_scale = boundary_scale
        self.adaptive_decay = adaptive_decay
        # 10%-15% 探索配额：防止确认偏误与"越学越保守"的自我实现预言
        self.exploration_fraction = float(exploration_fraction)
        self.rng_seed = int(rng_seed)
        self.adaptive_enabled = True
        self.cluster_stats = defaultdict(lambda: {"fp": 0.0, "n": 0.0})
        self.reviewed = {}

    def _cluster(self, rec):
        return str(rec.get("reason") or rec.get("ab") or "unknown")

    def update_from_labels(self, labels):
        """labels: [{"id","label"}]；label=True 表示新增拦截合理（非误报）。"""
        for item in labels:
            rid = item.get("id")
            cluster = item.get("cluster") or self.reviewed.get(rid) or "unknown"
            st = self.cluster_stats[cluster]
            if self.adaptive_enabled:
                st["fp"] = self.adaptive_decay * st["fp"] + (
                    0.0 if item.get("label") else 1.0
                )
                st["n"] = self.adaptive_decay * st["n"] + 1.0
            self.reviewed[rid] = cluster
        return dict(self.cluster_stats)

    def _cluster_weight(self, cluster):
        if not self.adaptive_enabled:
            # 冷启动信任崩塌：冻结自适应降权，避免"9 个差评"把系统永久判死
            return 1.0
        st = self.cluster_stats.get(cluster)
        if not st or st["n"] < 1:
            # 未见过的簇 → 探索价值高
            return 1.35
        fp_est = st["fp"] / st["n"]
        # 样本少 → posterior 不确定 → 也值得看
        uncertainty = 1.0 / (1.0 + st["n"])
        return 0.6 + 2.0 * fp_est + 1.5 * uncertainty

    def score(self, rec):
        ab = rec.get("ab") or "no_baseline"
        base = AB_PRIORITY.get(ab, 0.3)
        margin = rec.get("margin")
        if isinstance(margin, (int, float)):
            boundary = math.exp(-abs(float(margin)) / self.boundary_scale)
        else:
            boundary = 0.30
        unc = float(rec.get("uncertainty") or 0.3)
        impact = float(rec.get("impact") or 0.5)
        cluster = self._cluster(rec)
        cw = self._cluster_weight(cluster)
        s = (0.45 * base + 0.30 * boundary + 0.15 * unc + 0.10 * impact) * cw
        return round(s, 6)

    def select(self, records, *, budget_k=10, exclude_ids=None):
        """挑出最值得看的一小批；返回 (selected, audit)。"""
        exclude = set(exclude_ids or [])
        pool = [
            r for r in records if not r.get("reviewed") and r.get("id") not in exclude
        ]
        scored = [(self.score(r), str(r.get("id") or i), r) for i, r in enumerate(pool)]
        scored.sort(key=lambda x: (-x[0], x[1]))  # 确定性 tie-break
        selected, picked = [], []
        reason_count, cluster_count = Counter(), Counter()
        agree_cap = max(1, int(budget_k * self.agree_fraction))
        agree_taken = 0
        n_explore = (
            max(1, round(budget_k * self.exploration_fraction))
            if self.exploration_fraction > 0
            else 0
        )
        exploit_target = max(1, budget_k - n_explore)
        for s, rid, rec in scored:
            if len(selected) >= exploit_target:
                break
            cluster = self._cluster(rec)
            reason = str(rec.get("reason") or "none")
            if rec.get("ab") == "agree" and agree_taken >= agree_cap:
                continue
            if reason_count[reason] >= self.max_per_reason:
                continue
            # MMR：与已选样本重复则降权，重复度过高直接跳过
            dup = 0.0
            for pr in picked:
                if pr.get("mol_hash") and pr.get("mol_hash") == rec.get("mol_hash"):
                    dup = 1.0
                    break
                if self._cluster(pr) == cluster:
                    dup = max(dup, 0.6)
                if str(pr.get("reason") or "none") == reason:
                    dup = max(dup, 0.7)
            if dup >= 1.0:
                continue
            adj = s * (1.0 - 0.55 * dup)
            selected.append(
                {
                    "id": rid,
                    "mol_hash": rec.get("mol_hash"),
                    "ab": rec.get("ab"),
                    "reason": rec.get("reason"),
                    "score": round(adj, 6),
                    "raw_score": s,
                    "why": self._explain(rec, s, dup),
                    "review_question": "该新增拦截是否属于真实风险？（是=合理，否=误报）",
                    "cluster": cluster,
                }
            )
            picked.append(rec)
            reason_count[reason] += 1
            cluster_count[cluster] += 1
            if rec.get("ab") == "agree":
                agree_taken += 1

        # 探索配额：随机/低信息样本强制占位，打破"只看争议边界"的自我强化
        selected_ids = {d["id"] for d in selected}
        remaining = [r for r in pool if str(r.get("id") or "?") not in selected_ids]
        rng = random.Random(self.rng_seed + len(records))
        rng.shuffle(remaining)
        exploration_taken = 0
        need = budget_k - len(selected)
        for rec in remaining:
            if need <= 0 or exploration_taken >= n_explore:
                break
            rid = str(rec.get("id") or "explore-%d" % exploration_taken)
            selected.append(
                {
                    "id": rid,
                    "mol_hash": rec.get("mol_hash"),
                    "ab": rec.get("ab"),
                    "reason": rec.get("reason"),
                    "score": 0.0,
                    "raw_score": self.score(rec),
                    "why": "探索配额(10%-15%)：防确认偏误与自我实现的保守化",
                    "review_question": "该样本判定是否正确？（是=合理，否=误报）",
                    "cluster": self._cluster(rec),
                    "exploration": True,
                }
            )
            reason_count[str(rec.get("reason") or "none")] += 1
            cluster_count[self._cluster(rec)] += 1
            exploration_taken += 1
            need -= 1
        # 选完再按调整分排序一次，保证输出顺序即优先级
        selected.sort(key=lambda d: (-d["score"], d["id"]))
        audit = {
            "n_pool": len(pool),
            "n_selected": len(selected),
            "reason_histogram": dict(reason_count),
            "cluster_histogram": dict(cluster_count),
            "agree_taken": agree_taken,
            "exploration_taken": exploration_taken,
            "exploration_fraction": self.exploration_fraction,
            "nontrivial": sum(1 for d in selected if d["ab"] != "agree"),
        }
        return selected, audit

    def _explain(self, rec, score, dup):
        bits = []
        if rec.get("ab") in ("new_blocked_only", "old_blocked_only", "error"):
            bits.append("新旧判定分歧")
        m = rec.get("margin")
        if isinstance(m, (int, float)) and abs(float(m)) < 1:
            bits.append("贴近分类边界(|margin|=%.2f)" % abs(float(m)))
        if float(rec.get("uncertainty") or 0) >= 0.6:
            bits.append("模型不确定度高")
        if self._cluster_weight(self._cluster(rec)) > 1.2:
            bits.append("该簇误报估计高或样本少")
        if dup > 0:
            bits.append("已做多样性降权")
        return "；".join(bits) or "常规抽样"

    def fp_bound(self, labels=None):
        """基于已复核标签给出误报率 Wilson 上界（保守）。"""
        if labels:
            k = sum(1 for x in labels if x.get("label") is False)
            n = len(labels)
        else:
            # 未给标签时，用 update_from_labels 累积的簇统计做近似
            n = int(sum(st["n"] for st in self.cluster_stats.values()))
            k = int(sum(st["fp"] for st in self.cluster_stats.values()))
        return wilson_interval(k, n)


def promotion_gate(
    channel_stats: dict,
    sampler: ActiveReviewSampler,
    *,
    min_samples=30,
    max_fp_upper=0.05,
    labels=None,
) -> dict:
    """把样本量 + 错误率 + 误报上界合成为 ENFORCE 门禁。"""
    reasons = []
    n = int(channel_stats.get("n", 0))
    if n < min_samples:
        reasons.append("影子样本 %d < %d" % (n, min_samples))
    err = float(channel_stats.get("error_rate", 0))
    if err > 0.01:
        reasons.append("错误率 %.3f > 0.01" % err)
    iv = sampler.fp_bound(labels)
    if iv["n"] == 0:
        reasons.append("无任何人工复核标签")
    elif iv["upper"] > max_fp_upper:
        reasons.append(
            "误报率上界 %.3f > %.3f (n=%d, fp=%d)"
            % (
                iv["upper"],
                max_fp_upper,
                iv["n"],
                sum(1 for x in (labels or []) if x.get("label") is False),
            )
        )
    return {
        "allowed": not reasons,
        "reasons": reasons,
        "wilson": iv,
        "shadow_stats": channel_stats,
    }


class TrustGuard:
    """冷启动信任崩塌保护：前 10 条错 9 条时，不继续"自适应"把系统判死。

    状态机：NORMAL → CALIBRATION（冻结自适应、探索率提到 25%）
            → RECOVERY（探索率 15%）→ NORMAL。
    目的不是掩盖差评，而是把"模型可能整体错位"与"科学家对个别争议样本
    有分歧"区分开：冻结权重后用探索样本与控制样本重新校准。
    """

    NORMAL, CALIBRATION, RECOVERY = "NORMAL", "CALIBRATION", "RECOVERY"

    def __init__(self, *, window=10, collapse_fp_rate=0.6, recovery_n=5, normal_n=10):
        self.window = int(window)
        self.collapse_fp_rate = float(collapse_fp_rate)
        self.recovery_n = int(recovery_n)
        self.normal_n = int(normal_n)
        self.labels = []
        self.state = self.NORMAL
        self.default_exploration = None

    def update(self, labels):
        self.labels.extend(labels or [])
        recent = self.labels[-self.window :]
        fp = sum(1 for x in recent if x.get("label") is False)
        iv = wilson_interval(fp, len(recent))
        if self.state == self.NORMAL and len(recent) >= self.window:
            if fp / len(recent) >= self.collapse_fp_rate:
                self.state = self.CALIBRATION
        elif self.state == self.CALIBRATION:
            tail = self.labels[-self.recovery_n :]
            if len(tail) >= self.recovery_n and all(
                x.get("label") is True for x in tail
            ):
                self.state = self.RECOVERY
        elif self.state == self.RECOVERY:
            tail = self.labels[-self.normal_n :]
            if len(tail) >= self.normal_n and all(x.get("label") is True for x in tail):
                self.state = self.NORMAL
        return {
            "state": self.state,
            "recent_n": len(recent),
            "recent_fp": fp,
            "fp_rate": round(fp / len(recent), 4) if recent else 0.0,
            "wilson": iv,
            "actions": (
                ["freeze_adaptive_weights", "raise_exploration_quota"]
                if self.state == self.CALIBRATION
                else []
            ),
        }

    @staticmethod
    def adjust_sampler(sampler, guard_state):
        if guard_state == TrustGuard.CALIBRATION:
            if not hasattr(sampler, "_default_exploration"):
                sampler._default_exploration = sampler.exploration_fraction
            sampler.adaptive_enabled = False
            sampler.exploration_fraction = 0.25
        elif guard_state == TrustGuard.RECOVERY:
            sampler.adaptive_enabled = True
            sampler.exploration_fraction = 0.15
        else:
            sampler.adaptive_enabled = True
            sampler.exploration_fraction = getattr(
                sampler, "_default_exploration", sampler.exploration_fraction
            )
        return {
            "adaptive_enabled": sampler.adaptive_enabled,
            "exploration_fraction": sampler.exploration_fraction,
        }


class DynamicExplorationPolicy:
    """追问4：按科学家历史复核准确率 + 项目进度压力动态调整探索配额。

    复核越不准（说明模型/标签分布可能错位），越需要探索校准；
    科学家表现稳定且项目高压时，允许降到 8% 下限以避免敷衍式点击。
    任何情况下不为 0 —— 确认偏误防御不能被进度彻底关闭。
    """

    FLOOR = 0.08

    @staticmethod
    def fraction(
        reviewer_accuracy,
        n_labels,
        *,
        deadline_pressure=0.0,
        base=0.12,
        cold_start=0.15,
    ):
        if n_labels < 5:
            return cold_start
        acc = float(reviewer_accuracy)
        if acc < 0.60:
            return 0.25
        if acc < 0.80:
            return 0.15
        if acc >= 0.90 and float(deadline_pressure) >= 0.7:
            return max(DynamicExplorationPolicy.FLOOR, base - 0.04)
        return base

    @staticmethod
    def apply(sampler, *, reviewer_accuracy, n_labels, deadline_pressure=0.0):
        f = DynamicExplorationPolicy.fraction(
            reviewer_accuracy,
            n_labels,
            deadline_pressure=deadline_pressure,
            base=getattr(sampler, "_default_exploration", sampler.exploration_fraction),
        )
        sampler.exploration_fraction = f
        return {
            "exploration_fraction": f,
            "why": (
                "复核准确率低→强探索"
                if f >= 0.25
                else "高压且表现稳定→保留下限" if f <= 0.08 else "常规探索"
            ),
        }
