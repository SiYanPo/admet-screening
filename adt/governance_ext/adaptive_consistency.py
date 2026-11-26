# -*- coding: utf-8 -*-
"""追问④：Fast Mode 硬编码阈值的自适应改造 + 人为放行（Override）通道。

原实现 `logp>6 且 MW<200 → critical` 会把"含异常杂原子的新型类药分子"
误杀。改造为规则引擎：
  - 绝对物理不变量（NaN、MW<=0、HBD>原子数、环数>原子数/2）仍 0 容忍、
    不可 override——这是"太蠢"与"太松"的分界线；
  - 经验阈值（LogP/MW、TPSA/LogP）由描述符上下文自适应调整：
    局部校准密度高 → 严格 critical；新化学空间（密度低/杂原子多/
     explicitly novel_scaffold）→ 带宽放大，降为 warn + 开放 override；
  - override 不是"放行成高可信"：签名令牌带审批人、理由、有效期；
    生效后 tier_ceiling 强制 T1、certainty_modifier=human_override、
    并由合规水印模块打上 T1 标签——永远不能借 override 升级到 T2/T3。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import time
from dataclasses import dataclass
from typing import Callable

DEMO_KEY = b"admet-adaptive-consistency-override-2026"

# 小型校准云：真实部署应来自版本化的内部化合物库（带 git/数据版本）
CALIBRATION = [
    (1.2, 180.2, 63.0),
    (2.5, 320.0, 75.0),
    (3.8, 410.0, 90.0),
    (0.5, 240.0, 110.0),
    (4.5, 380.0, 45.0),
    (2.0, 260.0, 70.0),
]


@dataclass
class Rule:
    rid: str
    predicate: Callable[[dict, dict], bool]
    severity: str  # critical / adaptive
    overridable: bool
    detail: str


def _novelty(record: dict) -> dict:
    logp, mw, tpsa = record.get("logp"), record.get("mol_wt"), record.get("tpsa")
    dmin = None
    if all(isinstance(x, (int, float)) for x in (logp, mw, tpsa)):
        dmin = min(
            math.sqrt(
                ((logp - c[0]) / 4.0) ** 2
                + ((mw - c[1]) / 200.0) ** 2
                + ((tpsa - c[2]) / 80.0) ** 2
            )
            for c in CALIBRATION
        )
    n_hetero = int(record.get("n_hetero") or 0)
    n_halogen = int(record.get("n_halogen") or 0)
    explicit = bool(record.get("novel_scaffold"))
    sparse = dmin is not None and dmin > 1.8
    novel = explicit or sparse or n_hetero >= 8
    return {
        "novel": novel,
        "explicit": explicit,
        "sparse": sparse,
        "nearest_calibration_distance": round(dmin, 3) if dmin is not None else None,
        "n_hetero": n_hetero,
        "n_halogen": n_halogen,
    }


def adaptive_threshold(record: dict, novelty: dict = None) -> dict:
    """由化学上下文推导本次允许的 LogP 上界，而不是固定 6.0。"""
    nv = novelty or _novelty(record)
    mw = float(record.get("mol_wt") or 0)
    tpsa = float(record.get("tpsa") or 0)
    n_halogen = nv["n_halogen"]
    band = 2.2 if nv["novel"] else 0.35
    ceiling = (
        6.0
        + 0.012 * max(0.0, mw - 150)
        + 0.45 * n_halogen
        - 0.008 * max(0.0, tpsa - 60)
        + band
    )
    return {
        "logp_ceiling": round(ceiling, 3),
        "band": band,
        "novel": nv["novel"],
        "rationale": (
            ("新化学空间：校准稀疏/杂原子多，带宽 %.2f" % band)
            if nv["novel"]
            else "校准空间内：使用严格带宽 %.2f" % band
        ),
    }


class AdaptiveConsistencyEngine:
    def __init__(self, key=None):
        self.key = key or DEMO_KEY
        self.red_lines = [
            Rule(
                "nonfinite",
                lambda r, c: any(
                    isinstance(r.get(k), float)
                    and (r[k] != r[k] or r[k] in (float("inf"), float("-inf")))
                    for k in ("mol_wt", "logp", "tpsa")
                ),
                "critical",
                False,
                "非有限数值（缓存/子进程异常）",
            ),
            Rule(
                "mw_nonpositive",
                lambda r, c: isinstance(r.get("mol_wt"), (int, float))
                and r["mol_wt"] <= 0,
                "critical",
                False,
                "MW<=0",
            ),
            Rule(
                "hbd_gt_atoms",
                lambda r, c: isinstance(r.get("hbd"), (int, float))
                and isinstance(r.get("n_atoms"), (int, float))
                and r["hbd"] > r["n_atoms"],
                "critical",
                False,
                "HBD>原子数",
            ),
            Rule(
                "hba_gt_atoms",
                lambda r, c: isinstance(r.get("hba"), (int, float))
                and isinstance(r.get("n_atoms"), (int, float))
                and r["hba"] > r["n_atoms"],
                "critical",
                False,
                "HBA>原子数",
            ),
            Rule(
                "rings_gt_half",
                lambda r, c: isinstance(r.get("n_rings"), (int, float))
                and isinstance(r.get("n_atoms"), (int, float))
                and r["n_atoms"] > 0
                and r["n_rings"] > r["n_atoms"] / 2.0,
                "critical",
                False,
                "环数>原子数/2",
            ),
        ]
        self.adaptive_rules = [
            Rule(
                "logp_mw",
                lambda r, c: isinstance(r.get("logp"), (int, float))
                and r["logp"] > c["logp_ceiling"],
                "adaptive",
                True,
                "LogP 超出自适应上界",
            ),
            Rule(
                "tpsa_logp",
                lambda r, c: isinstance(r.get("tpsa"), (int, float))
                and isinstance(r.get("logp"), (int, float))
                and r["tpsa"] > 140
                and r["logp"] > 4.0 + c["band"],
                "adaptive",
                True,
                "高 TPSA 与高 LogP 并存",
            ),
        ]

    def check(self, record: dict) -> dict:
        nv = _novelty(record)
        th = adaptive_threshold(record, nv)
        ctx = dict(th)
        crit, warn, overridable = [], [], []
        for rule in self.red_lines:
            if rule.predicate(record, ctx):
                crit.append(
                    {"rule": rule.rid, "detail": rule.detail, "overridable": False}
                )
        for rule in self.adaptive_rules:
            if rule.predicate(record, ctx):
                msg = "%s（LogP=%.2f, 上界=%.2f, MW=%.0f）" % (
                    rule.detail,
                    float(record.get("logp") or 0),
                    th["logp_ceiling"],
                    float(record.get("mol_wt") or 0),
                )
                if nv["novel"] and rule.overridable:
                    warn.append(
                        {
                            "rule": rule.rid,
                            "detail": msg,
                            "override_available": True,
                            "requires_second_approver": False,
                        }
                    )
                    overridable.append(rule.rid)
                else:
                    crit.append({"rule": rule.rid, "detail": msg, "overridable": False})
        refuse = bool(crit)
        return {
            "consistent": not refuse,
            "refuse_t1": refuse,
            "critical": crit,
            "warnings": warn,
            "overridable_rules": overridable,
            "novelty": nv,
            "threshold": th,
            "action": (
                "数据矛盾，拒绝 T1"
                if refuse
                else ("新化学空间：可 T1 提示，支持签名放行" if warn else "通过")
            ),
        }

    # ---- 人为放行 ----
    def request_override(
        self,
        record,
        rule_id,
        *,
        scientist,
        reason,
        approver2=None,
        tier="T1",
        ttl_s=86400,
    ):
        if rule_id not in self.check(record)["overridable_rules"]:
            raise PermissionError(
                "规则 %s 当前不可放行（绝对红线或校准空间内）" % rule_id
            )
        if not scientist or not reason or len(str(reason)) < 5:
            raise ValueError("放行必须填写 scientist 与具体 reason(>=5字符)")
        if tier in ("T2", "T3") and not approver2:
            raise PermissionError("T2/T3 放行必须第二审批人")
        body = {
            "inchikey": record.get("inchikey"),
            "rule_id": rule_id,
            "scientist": scientist,
            "reason": str(reason)[:200],
            "approver2": approver2,
            "target_tier": "T1" if tier in ("T1", "T2", "T3") else "T1",
            "exp": int(time.time()) + int(ttl_s),
        }
        sig = hmac.new(
            self.key,
            json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return {"token": dict(body), "sig": sig}

    def apply_override(self, record, grant):
        body, sig = grant.get("token"), grant.get("sig")
        expected = (
            hmac.new(
                self.key,
                json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
            if body
            else ""
        )
        if not body or not hmac.compare_digest(expected, str(sig)):
            raise PermissionError("放行令牌签名无效")
        if body["exp"] < int(time.time()):
            raise PermissionError("放行令牌已过期")
        out = dict(record)
        out["tier_ceiling"] = "T1"  # override 永远不能升档
        out["verdict"] = (
            out.get("verdict") if out.get("verdict") in ("PASS", "FAIL") else "PASSTHRU"
        )
        out["certainty_modifier"] = "human_override"
        out["reason"] = "ADAPTIVE_OVERRIDE"
        out["override"] = {
            "scientist": body["scientist"],
            "reason": body["reason"],
            "rule": body["rule_id"],
            "expires": body["exp"],
        }
        return out
