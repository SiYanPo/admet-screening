# -*- coding: utf-8 -*-
"""盲区3：L0 → 下游的"计算预算指令"（Compute Budget Directive）。

L0 不能只打标签然后放行：400 原子分子若进入 L2 的 Tanimoto kNN，
距离矩阵 n² 会直接 OOM；若进入 L3 反事实生成会挂死。

本模块把 L0 的复杂度画像翻译成**可执行调度指令**：
  - macro / 互变枚举跳过 → L2 只用 Morgan 拓扑指纹（不构造 n×n 稠密矩阵），
    L3 关闭，只返回分子属性；
  - large → L2 有界 kNN（k≤20，距离矩阵上限受控），L3 关闭；
  - small/medium → 全量，但仍受 max_matrix_elements 硬上限约束。

指令与 LayerDispatcher 绑定：未获准的层根本不会被调用（结构切断），
而不是"调用后再判断"。这样才真正防住下游雪崩。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time

MAX_MATRIX_ELEMENTS = 1_000_000
INTERACTIVE_KEY = b"admet-interactive-compute-override-2026"


def directive_for(guard: dict, *, max_matrix_elements=MAX_MATRIX_ELEMENTS) -> dict:
    if not guard.get("pass_guard", False):
        return {
            "directive": "STOP_ALL",
            "reason": guard.get("reason") or "L0_FAIL_CLOSED",
            "l2": "disabled",
            "l3": "disabled",
            "return_properties_only": True,
            "tier_ceiling": "T0",
            "max_neighbors": 0,
            "max_matrix_elements": 0,
        }
    tier = guard.get("complexity") or "small"
    n_atoms = guard.get("n_atoms") or 0
    taut_skipped = (
        guard.get("state_sensitive") in ("skipped_oversize", "not_evaluated")
        or guard.get("taut_skipped") is True
    )
    if tier == "macro" or n_atoms >= 200:
        return {
            "directive": "TOPOLOGY_ONLY",
            "reason": "MACRO_OR_OVERSIZE",
            "l2": "topology_fingerprint",
            "fingerprint": "Morgan_r2_2048",
            "l3": "disabled",
            "return_properties_only": True,
            "tier_ceiling": "T1",
            "max_neighbors": 0,
            "max_matrix_elements": max_matrix_elements,
            "note": "只返回分子属性+拓扑指纹；禁止稠密 Tanimoto 矩阵与反事实生成",
        }
    if tier == "large" or taut_skipped:
        return {
            "directive": "BOUNDED_L2",
            "reason": "LARGE_OR_TAUT_SKIPPED",
            "l2": "bounded_knn",
            "fingerprint": "Morgan_r2_2048",
            "l3": "disabled",
            "return_properties_only": False,
            "tier_ceiling": "T1",
            "max_neighbors": 20,
            "max_matrix_elements": max_matrix_elements,
            "note": "L2 kNN k<=20；L3 关闭；互变状态未定，不得出高置信结论",
        }
    return {
        "directive": "FULL",
        "reason": "WITHIN_COMPUTE_ENVELOPE",
        "l2": "full_knn",
        "l3": "enabled",
        "return_properties_only": False,
        "tier_ceiling": "T2",
        "max_neighbors": 50,
        "max_matrix_elements": max_matrix_elements,
        "note": "常规分子，允许完整 L2/L3，但仍受矩阵上限硬约束",
    }


def matrix_size_gate(n_candidates: int, directive: dict) -> dict:
    """稠密矩阵硬闸：超限则强制切拓扑指纹，不允许"先算再说"。"""
    n = int(n_candidates)
    limit = int(directive.get("max_matrix_elements", MAX_MATRIX_ELEMENTS))
    need = n * n
    if need > limit:
        return {
            "allowed": False,
            "need_elements": need,
            "limit": limit,
            "fallback": "topology_fingerprint",
            "reason": "距离矩阵 %d 元素超过上限 %d" % (need, limit),
        }
    return {
        "allowed": True,
        "need_elements": need,
        "limit": limit,
        "reason": "within_budget",
    }


# ---- 交互式算力放行（Interactive Override）----
def request_interactive_override(
    directive, *, scientist, reason, requested_layers, gpu_ticket, ttl_s=3600, key=None
):
    """科学家明确承担算力风险后申请深算。发放**有边界**的临时票据。

    镣铐：只放开被申请的层；k 仍受 directive 上限；矩阵硬闸不解除；
    结果 tier 强制封顶 T1（算力放行不等于证据升级）。
    """
    if not scientist or not reason or len(str(reason)) < 10:
        raise ValueError("交互式放行必须填写 scientist 与 >=10 字符的理由")
    if not gpu_ticket or len(str(gpu_ticket)) < 6:
        raise ValueError("必须提供 GPU/算力资源工单号")
    layers = [str(x).upper() for x in requested_layers]
    if not layers or any(x not in ("L2", "L3") for x in layers):
        raise ValueError("只允许申请 L2/L3")
    body = {
        "directive": directive.get("directive"),
        "scientist": scientist,
        "reason": str(reason)[:200],
        "layers": sorted(layers),
        "gpu_ticket": str(gpu_ticket)[:80],
        "max_neighbors": min(20, int(directive.get("max_neighbors") or 20)),
        "max_matrix_elements": int(
            directive.get("max_matrix_elements", MAX_MATRIX_ELEMENTS)
        ),
        "tier_ceiling": "T1",
        "exp": int(time.time()) + int(ttl_s),
    }
    sig = hmac.new(
        key or INTERACTIVE_KEY,
        json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return {"token": body, "sig": sig}


def verify_interactive_grant(directive, grant, *, key=None):
    body = (grant or {}).get("token")
    if not body:
        return {"ok": False, "reason": "NO_GRANT"}
    expected = hmac.new(
        key or INTERACTIVE_KEY,
        json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, str(grant.get("sig"))):
        return {"ok": False, "reason": "SIGNATURE_INVALID"}
    if body.get("exp", 0) < int(time.time()):
        return {"ok": False, "reason": "EXPIRED"}
    if body.get("directive") != directive.get("directive"):
        return {"ok": False, "reason": "DIRECTIVE_MISMATCH"}
    return {"ok": True, "reason": "INTERACTIVE_OVERRIDE_VALID", "token": body}


class LayerDispatcher:
    """按指令调度层；被禁止的层根本不调用 handler。"""

    def __init__(self, directive: dict):
        self.directive = directive
        self.calls = []

    def run(self, layers: dict, *, n_candidates=0, context=None, override_grant=None):
        """layers: {"L1": fn, "L2": fn, "L3": fn}；返回每层结果/跳过原因。

        override_grant 为交互式算力放行票据：只能放开票据点名的层，
        k 与矩阵硬闸依旧生效，结果强制 T1。
        """
        d = dict(self.directive)
        out = {}
        if override_grant is not None:
            ov = verify_interactive_grant(self.directive, override_grant)
            if ov["ok"]:
                tok = ov["token"]
                allowed = set(tok["layers"])
                d["return_properties_only"] = False
                d["max_neighbors"] = tok["max_neighbors"]
                d["max_matrix_elements"] = tok["max_matrix_elements"]
                if "L2" in allowed:
                    d["l2"] = "bounded_knn"
                if "L3" in allowed:
                    d["l3"] = "enabled"
                d["tier_ceiling"] = "T1"
                out["_override"] = {
                    "status": "ACCEPTED",
                    "eid": tok["gpu_ticket"],
                    "scientist": tok["scientist"],
                    "tier_ceiling": "T1",
                }
            else:
                out["_override"] = {"status": "REJECTED", "reason": ov["reason"]}
        gate = matrix_size_gate(n_candidates, d)
        for name, fn in layers.items():
            key = (
                "l3" if name.upper() == "L3" else "l2" if name.upper() == "L2" else None
            )
            policy = d.get(key) if key else "enabled"
            skip = None
            if d.get("return_properties_only") and key in ("l2", "l3"):
                skip = "DISABLED_BY_DIRECTIVE:%s" % d["directive"]
            elif policy in ("disabled", None) and key:
                skip = "DISABLED_BY_DIRECTIVE:%s" % d["directive"]
            elif (
                key == "l2"
                and policy in ("bounded_knn", "full_knn")
                and not gate["allowed"]
            ):
                skip = "MATRIX_BUDGET_EXCEEDED:%d>%d" % (
                    gate["need_elements"],
                    gate["limit"],
                )
            if skip:
                out[name] = {"status": "SKIPPED", "reason": skip}
                continue
            kwargs = dict(context or {})
            if key == "l2" and policy == "bounded_knn":
                kwargs["k"] = min(
                    int(kwargs.get("k", 20)), int(d.get("max_neighbors", 20))
                )
            if key == "l2" and policy == "topology_fingerprint":
                kwargs["fingerprint"] = self.directive.get(
                    "fingerprint", "Morgan_r2_2048"
                )
                kwargs["topology_only"] = True
            try:
                out[name] = {"status": "OK", "result": fn(**kwargs)}
            except Exception as exc:
                out[name] = {
                    "status": "ERROR",
                    "reason": "%s: %s" % (type(exc).__name__, str(exc)[:120]),
                }
            self.calls.append(name)
        out["_directive"] = d["directive"]
        out["_matrix_gate"] = gate
        out["_tier_ceiling"] = d.get("tier_ceiling", "T1")
        return out


def directive_digest(directive: dict) -> str:
    """把指令哈希写入产物 manifest，便于审计"当时为何切断"。"""
    import json

    body = json.dumps(directive, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(body).hexdigest()[:16]
