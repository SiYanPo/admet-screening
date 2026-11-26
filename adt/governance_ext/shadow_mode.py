# -*- coding: utf-8 -*-
"""落地问题①：影子模式（Shadow Mode）+ A/B 比对 + 切换门禁。

核心目标：新模块（textgen 拦截 / l0_guard 强校验）接入初期只记录、只告警，
**绝不阻断主流程**；积累足够的真实样本后，用 A/B 比对证明"拦截率合理、
误报率低"，才切换到 Enforce。

设计三态：
  OFF      → 只用 old，完全不跑 new
  SHADOW   → 双跑：old 的结果照常返回（主流程不变），new 的判定只记录
  ENFORCE  → 用 new 的结果

关键：SHADOW 模式下，new 抛异常也必须被吞掉（记 ERROR），绝不影响主流程。
切换门禁：样本量 ≥ min_samples 且 误报率 ≤ max_fp_rate 才允许 ENFORCE。
纯标准库。
"""

from __future__ import annotations
import hashlib
import json

OFF, SHADOW, ENFORCE = "off", "shadow", "enforce"


class ShadowChannel:
    """一个待接入模块的影子通道。

    decision_fn(input) -> dict(block=bool, reason=str, ...)
    """

    def __init__(
        self, name, decision_fn, *, mode=SHADOW, min_samples=30, max_fp_rate=0.05
    ):
        self.name = name
        self.decision_fn = decision_fn
        self.mode = mode
        self.min_samples = min_samples
        self.max_fp_rate = max_fp_rate
        self.records = []  # 每次调用的对比记录

    def run(self, payload, *, old_decision=None):
        """执行一次影子判定。

        payload: 传给 decision_fn 的输入。
        old_decision: 主流程（旧逻辑）给出的判定，用于 A/B 比对（可选）。
        返回：(effective_decision, shadow_info)
          - OFF    : 返回 old_decision（若 None 则返回 None）
          - SHADOW : 返回 old_decision；new 判定只记录
          - ENFORCE: 返回 new 判定
        """
        if self.mode == OFF:
            return old_decision, {"mode": OFF, "ran_new": False}

        # 运行 new（任何异常都被吞，绝不阻断主流程）
        new_dec, err = None, None
        try:
            new_dec = self.decision_fn(payload)
        except Exception as e:  # noqa: BLE001 - 影子模式必须吞异常
            err = "%s: %s" % (type(e).__name__, str(e)[:120])

        rec = {
            "mode": self.mode,
            "old_block": (
                bool((old_decision or {}).get("block")) if old_decision else None
            ),
            "new_block": bool((new_dec or {}).get("block")) if new_dec else None,
            "error": err,
            "payload_summary": _summ(payload),
            "new_reason": (new_dec or {}).get("reason") if new_dec else None,
            "new_dec": new_dec,  # 仅判定摘要，不含原始分子；供 ephemeral 日志消费
        }
        # A/B 归类
        if old_decision is not None and new_dec is not None:
            ob, nb = rec["old_block"], rec["new_block"]
            if nb and not ob:
                rec["ab"] = "new_blocked_only"  # new 新增拦截（潜在风险点）
            elif ob and not nb:
                rec["ab"] = "old_blocked_only"  # new 放过了旧逻辑拦的（潜在漏报）
            else:
                rec["ab"] = "agree"
        elif err:
            rec["ab"] = "error"
        else:
            rec["ab"] = "no_baseline"
        self.records.append(rec)

        if self.mode == ENFORCE:
            return (new_dec if new_dec is not None else old_decision), rec
        # SHADOW / OFF(已返回) → 主流程结果不变
        return old_decision, rec

    def stats(self):
        """A/B 统计：拦截率、误报率（需人工标注 ground truth 才有真误报率）。

        这里给出可自动算的指标：
        - n_total / n_error / error_rate
        - new_blocked_only（新增拦截数）/ old_blocked_only（放过数）/ agree
        - 由于无 ground-truth，"误报率"需通过人工复核 new_blocked_only 样本估计，
          提供 fp_rate_external 接口。
        """
        n = len(self.records)
        if n == 0:
            return {"n": 0}
        err = sum(1 for r in self.records if r["ab"] == "error")
        nbo = sum(1 for r in self.records if r["ab"] == "new_blocked_only")
        obo = sum(1 for r in self.records if r["ab"] == "old_blocked_only")
        agree = sum(1 for r in self.records if r["ab"] == "agree")
        return {
            "n": n,
            "n_error": err,
            "error_rate": round(err / n, 4),
            "new_blocked_only": nbo,
            "old_blocked_only": obo,
            "agree": agree,
            "agree_rate": round(agree / n, 4),
            "new_extra_block_rate": round(nbo / n, 4),
        }

    def can_promote(self, *, fp_rate_external):
        """切换门禁：样本量足够 + 外部复核误报率达标 + 错误率低。

        fp_rate_external: 人工复核 new_blocked_only 样本后估出的误报率。
        """
        s = self.stats()
        reasons = []
        if s["n"] < self.min_samples:
            reasons.append("样本量 %d < %d" % (s["n"], self.min_samples))
        if fp_rate_external is None:
            reasons.append("缺外部误报率复核")
        elif fp_rate_external > self.max_fp_rate:
            reasons.append("误报率 %.3f > %.3f" % (fp_rate_external, self.max_fp_rate))
        if s.get("error_rate", 0) > 0.01:
            reasons.append("错误率 %.3f > 0.01" % s["error_rate"])
        allowed = not reasons
        return {"allowed": allowed, "reasons": reasons, "stats": s}

    def promote(self, *, fp_rate_external):
        g = self.can_promote(fp_rate_external=fp_rate_external)
        if g["allowed"]:
            self.mode = ENFORCE
        return {"promoted": g["allowed"], "mode": self.mode, "gate": g}


def _summ(payload):
    """影子日志脱敏：只留指纹哈希，绝不落原始 SMILES（盲区4）。"""
    if isinstance(payload, dict):
        body = json.dumps(
            payload, sort_keys=True, ensure_ascii=False, default=str
        ).encode("utf-8")
        return {
            "mol_hash": hashlib.sha256(body).hexdigest()[:16],
            "n_fields": len(payload),
        }
    return {"mol_hash": hashlib.sha256(str(payload).encode("utf-8")).hexdigest()[:16]}
