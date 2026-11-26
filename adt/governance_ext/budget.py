# -*- coding: utf-8 -*-
"""问题③：Fast / Rigorous 双轨 + 时间预算熔断。

核心设计（来自设计文档第三章）：
- Fast Mode 的置信度**绑定证据来源**，不是简单标"低"。
- 时间预算分层熔断：超时/预算不足 → out_of_domain，而非挂死。
- partial_execution 强制封顶 T1。
纯标准库，无依赖。
"""

from __future__ import annotations
import time

BUDGET_PROFILES = {
    "fast": {
        "total_s": 15,
        "per_api_s": 3,
        "allow_external": False,
        "tier_ceiling": "T1",
    },
    "standard": {
        "total_s": 60,
        "per_api_s": 15,
        "allow_external": True,
        "tier_ceiling": "T2",
    },
    "rigorous": {
        "total_s": 300,
        "per_api_s": 90,
        "allow_external": True,
        "tier_ceiling": "T3",
    },
}

# Fast 模式的置信度声明模板（绑定证据来源，不是模糊的"低"）
CONFIDENCE_DECLARATION = {
    "fast": {
        "level": "exploratory_only",
        "evidence_basis": "local_rdkit + offline_snapshot",
        "tier_ceiling": "T1",
        "reason": "无外部独立源、无实测、无适用域门重算",
        "what_can_be_said": "单源启发式方向提示，须 Rigorous 或湿实验确认",
        "what_cannot_be_said": ["PASS/FAIL 定论", "排序", "跨源一致性", "进入论文表"],
        "upgrade_path": "运行 --mode rigorous 或补充 ≥1 独立方法组升 T2",
    },
    "standard": {
        "level": "decision_support",
        "evidence_basis": "external_sources(<=4) + local",
        "tier_ceiling": "T2",
        "reason": "有外部源但未跑满 14 门禁与全部仲裁",
        "what_can_be_said": "项目决策级结论（多源方向一致时）",
        "what_cannot_be_said": ["论文正式结论", "申报结论"],
        "upgrade_path": "运行 --mode rigorous",
    },
    "rigorous": {
        "level": "publication_eligible",
        "evidence_basis": "full_sources + 14_gates + full_arbitration",
        "tier_ceiling": "T3",
        "reason": "全量仲裁与门禁（仍需实测+独立基准才达 T3 实质）",
        "what_can_be_said": "视 tier 与实测而定；无实测仍封顶 T2",
        "what_cannot_be_said": ["无实测时不得写'已确证/安全'"],
        "upgrade_path": "补充实测真值 + 独立基准",
    },
}


class TimeBudget:
    def __init__(self, profile="fast", *, clock=time.monotonic):
        if profile not in BUDGET_PROFILES:
            raise ValueError("未知 profile: %r" % profile)
        self.profile = profile
        self._clock = clock
        self.deadline = clock() + BUDGET_PROFILES[profile]["total_s"]
        self.completed, self.skipped = [], []

    def remaining(self):
        return self.deadline - self._clock()

    def can_call(self, source):
        p = BUDGET_PROFILES[self.profile]
        return bool(p["allow_external"]) and self.remaining() > p["per_api_s"]

    def per_api_timeout(self):
        p = BUDGET_PROFILES[self.profile]
        return max(0.0, min(p["per_api_s"], self.remaining()))

    def mark_done(self, step):
        self.completed.append(step)

    def mark_skipped(self, step, reason):
        self.skipped.append({"step": step, "reason": reason})


def out_of_domain_record(source, reason, **kw):
    """熔断产出的 out_of_domain 记录（**必须不带数值**）。"""
    rec = {
        "source": source,
        "domain_flag": "out_of_domain",
        "value": None,
        "unit": None,
        "reason": reason,
    }
    rec.update(kw)
    return rec


def guarded_call(fn, budget, source, *args, **kwargs):
    """带熔断的源调用。超时/预算不足 → out_of_domain；异常 → error。"""
    if not budget.can_call(source):
        budget.mark_skipped(source, "BUDGET_EXHAUSTED")
        return out_of_domain_record(source, "BUDGET_EXHAUSTED", partial=True)
    started = budget._clock()
    try:
        result = fn(*args, **kwargs)
    except TimeoutError:
        budget.mark_skipped(source, "TIMEOUT")
        return out_of_domain_record(source, "TIMEOUT", partial=True)
    except Exception as e:
        budget.mark_skipped(source, "ERROR")
        return out_of_domain_record(source, "ERROR", detail=str(e)[:120], partial=True)
    elapsed = budget._clock() - started
    # 若该源耗时超单源预算，标记（但仍返回结果，因已算出）
    if elapsed > BUDGET_PROFILES[budget.profile]["per_api_s"]:
        result = dict(result) if isinstance(result, dict) else {"result": result}
        result["_over_budget"] = round(elapsed, 2)
    budget.mark_done(source)
    return result


def finalize_manifest(manifest, budget):
    """把熔断状态写进 manifest；partial_execution 强制封顶 T1。"""
    p = BUDGET_PROFILES[budget.profile]
    exec_info = {
        "mode": budget.profile,
        "completed_steps": list(budget.completed),
        "skipped_steps": list(budget.skipped),
        "partial_execution": len(budget.skipped) > 0,
        "budget_total_s": p["total_s"],
        "budget_used_s": round(p["total_s"] - budget.remaining(), 3),
        "tier_ceiling": p["tier_ceiling"],
        "confidence_declaration": CONFIDENCE_DECLARATION[budget.profile],
    }
    if exec_info["partial_execution"]:
        exec_info["tier_ceiling"] = "T1"  # 部分执行一律封顶 T1
        exec_info["partial_note"] = "存在未完成/超时步骤，结论仅探索级"
    merged = dict(manifest or {})
    merged["execution"] = exec_info
    return merged


def enforce_publish_gate(mode, tier):
    """Fast 产物不得进入 publish（结构性约束，防止严谨性被产品形态废掉）。"""
    if mode == "fast":
        return {
            "allowed": False,
            "reason": "Fast 模式产物（T1 探索级）不得发布/进论文",
            "required": "运行 --mode rigorous 且达 T2+",
        }
    if tier not in ("T2", "T3"):
        return {
            "allowed": False,
            "reason": "tier=%s 不足以发布" % tier,
            "required": "T2 或 T3",
        }
    return {"allowed": True, "reason": "通过发布门禁"}
