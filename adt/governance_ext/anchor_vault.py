# -*- coding: utf-8 -*-
"""自噬悖论闭环：Reference Anchor Vault with Expiry（带有效期的参考锚点库）。

术语（同行评审 §4 分歧 4，2026-11-22）：旧材料称"绝对锚点"，但锚点会随认知
更新变错；改称 **reference anchor with expiry**。类名 AnchorVault 为兼容保留。
每个锚点绑定科学半衰期（scientific_half_life_days）+ 认知截止日（knowledge_cutoff），
超期只告警不自动更新；更新=新增锚点+双人签发。锚点不是"绝对真理"，是"当前
有有效期、需湿实验复测与双人签发才能更新的参考值"。

问题：washout() 用"当前金标准重跑值"覆盖历史。若金标准本身被 API
污染/漂移，洗脱就是把污染当基准——越洗越脏（自噬）。

闭环方案：
  - Vault 只追加（append-only），无 update/delete API；
  - 每条锚点绑定湿实验证据（plate/run/protocol + evidence_hash），
    双人审批 + HMAC 签名 + 前一条记录哈希的链式结构；
  - washout 前必须 validate：金标准值落在锚点容差内，否则拒绝该分子
    的洗脱（保留历史并标 NEEDS_WASHOUT），fail-closed；
  - 锚点超期只告警，不自动更新；更新必须新增一条新锚点并双人审批。

结论：外部 API 可以漂，洗脱基准永不漂；即便湿实验室自身换了批次，
也是"新增锚点 + 双人签字"，而不是静默覆盖。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone

DEMO_KEY = b"admet-absolute-anchor-vault-2026-11"


@dataclass(frozen=True)
class Anchor:
    mol_id: str
    endpoint: str
    value: float
    unit: str
    protocol: str
    wet_run_id: str
    evidence_hash: str
    measured_at: str
    approver1: str
    approver2: str
    prev_hash: str
    sig: str
    scientific_half_life_days: int = 365
    knowledge_cutoff: str = ""


class AnchorVault:
    def __init__(self, key=None):
        self.key = key or DEMO_KEY
        self._anchors = []
        self._by_key = {}

    @staticmethod
    def _body(d):
        return json.dumps(
            d, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")

    def add(
        self,
        *,
        mol_id,
        endpoint,
        value,
        unit,
        protocol,
        wet_run_id,
        evidence_hash,
        measured_at,
        approver1,
        approver2,
        scientific_half_life_days=365,
        knowledge_cutoff=None,
    ):
        """追加锚点。双人审批必填；同 (mol_id,endpoint) 只允许新增，不覆盖。

        knowledge_cutoff：该锚点所依据的科学认知版本日期（文献/指南更新日），
        若未提供则用 wet 测量日。scientific_half_life_days 控制科学时效性衰减。
        """
        if not approver1 or not approver2 or approver1 == approver2:
            raise ValueError(
                "参考锚点（reference anchor with expiry）必须双人审批且审批人不同"
            )
        if not evidence_hash or len(str(evidence_hash)) < 8:
            raise ValueError("必须绑定湿实验证据哈希")
        prev = self._anchors[-1].sig if self._anchors else "GENESIS"
        body = {
            "mol_id": mol_id,
            "endpoint": endpoint,
            "value": float(value),
            "unit": unit,
            "protocol": protocol,
            "wet_run_id": wet_run_id,
            "evidence_hash": evidence_hash,
            "measured_at": measured_at,
            "approver1": approver1,
            "approver2": approver2,
            "prev_hash": prev,
            "scientific_half_life_days": int(scientific_half_life_days),
            "knowledge_cutoff": knowledge_cutoff or measured_at,
        }
        sig = hmac.new(self.key, self._body(body), hashlib.sha256).hexdigest()
        a = Anchor(sig=sig, **body)
        self._anchors.append(a)
        self._by_key.setdefault((mol_id, endpoint), []).append(a)
        return a

    def verify_chain(self):
        prev = "GENESIS"
        broken = []
        for i, a in enumerate(self._anchors):
            if a.prev_hash != prev:
                broken.append({"index": i, "reason": "prev_hash_mismatch"})
            body = {
                "mol_id": a.mol_id,
                "endpoint": a.endpoint,
                "value": a.value,
                "unit": a.unit,
                "protocol": a.protocol,
                "wet_run_id": a.wet_run_id,
                "evidence_hash": a.evidence_hash,
                "measured_at": a.measured_at,
                "approver1": a.approver1,
                "approver2": a.approver2,
                "prev_hash": a.prev_hash,
                "scientific_half_life_days": a.scientific_half_life_days,
                "knowledge_cutoff": a.knowledge_cutoff,
            }
            if not hmac.compare_digest(
                hmac.new(self.key, self._body(body), hashlib.sha256).hexdigest(), a.sig
            ):
                broken.append({"index": i, "reason": "sig_mismatch"})
            prev = a.sig
        return {"ok": not broken, "n": len(self._anchors), "broken": broken}

    def latest(self, mol_id, endpoint):
        arr = self._by_key.get((mol_id, endpoint), [])
        return arr[-1] if arr else None

    def validate(self, mol_id, endpoint, value, *, rel_tol=0.05, abs_tol=1e-6):
        a = self.latest(mol_id, endpoint)
        if a is None:
            return {
                "ok": False,
                "reason": "ANCHOR_MISSING",
                "detail": "该分子/端点没有有效的湿实验参考锚点（with expiry），禁止洗脱",
            }
        delta = abs(float(value) - a.value)
        limit = max(abs_tol, rel_tol * abs(a.value))
        if delta > limit:
            return {
                "ok": False,
                "reason": "ANCHOR_MISMATCH",
                "detail": "金标准=%.6g 锚点=%.6g 差=%.6g > 容差 %.6g"
                % (float(value), a.value, delta, limit),
                "anchor": a.sig[:12],
            }
        return {
            "ok": True,
            "reason": "ANCHOR_MATCH",
            "anchor": a.sig[:12],
            "value": a.value,
            "unit": a.unit,
            "protocol": a.protocol,
        }

    def health(self, now=None, *, max_age_days=365):
        """锚点老化只告警，绝不自动洗脱。"""
        now = now or datetime.now(timezone.utc)
        stale = []
        for a in self._anchors:
            dt = datetime.fromisoformat(str(a.measured_at).replace("Z", "+00:00"))
            age = (now - dt).days
            if age > max_age_days:
                stale.append(
                    {
                        "mol_id": a.mol_id,
                        "endpoint": a.endpoint,
                        "age_days": age,
                        "sig": a.sig[:12],
                    }
                )
        return {
            "ok": not stale,
            "stale": stale,
            "note": "超期锚点需安排湿实验复测并新增锚点，不得就地更新",
        }

    def scientific_health(self, now=None):
        """科学时效性衰减：锚点不只是"旧"，还会因认知更新而变错。

        置信度 = 0.5^(scientific_age_days / half_life_days)；
        ACTIVE>=0.70，AGING>=0.40，EXPIRED<0.40。
        """
        now = now or datetime.now(timezone.utc)
        out = []
        for a in self._anchors:
            base = a.knowledge_cutoff or a.measured_at
            dt = datetime.fromisoformat(str(base).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            age = max(0, (now - dt).days)
            half = max(1, int(a.scientific_half_life_days or 365))
            conf = 0.5 ** (age / float(half))
            status = (
                "ACTIVE" if conf >= 0.70 else "AGING" if conf >= 0.40 else "EXPIRED"
            )
            out.append(
                {
                    "mol_id": a.mol_id,
                    "endpoint": a.endpoint,
                    "sig": a.sig[:12],
                    "scientific_age_days": age,
                    "half_life_days": half,
                    "effective_confidence": round(conf, 5),
                    "status": status,
                }
            )
        return out

    def decision_gate(self, mol_id, endpoint, now=None):
        """老化锚点不是静默使用：锁预测并降级 UNDETERMINED。"""
        a = self.latest(mol_id, endpoint)
        if a is None:
            return {
                "action": "LOCK_AND_UNDETERMINED",
                "status": "NO_ANCHOR",
                "reason": "无有效参考锚点（with expiry），禁止给出定量结论",
            }
        h = [x for x in self.scientific_health(now) if x["sig"] == a.sig[:12]]
        st = h[0] if h else {"status": "EXPIRED", "effective_confidence": 0.0}
        if st["status"] == "EXPIRED":
            return {
                "action": "LOCK_AND_UNDETERMINED",
                "status": "EXPIRED",
                "reason": "锚点科学时效性过期（认知半衰期 %.0f天，置信度 %.3f）"
                % (st["half_life_days"], st["effective_confidence"]),
                "required": "安排湿实验复测 + 双人签发新锚点",
            }
        if st["status"] == "AGING":
            return {
                "action": "DOWNGRADE_T1",
                "status": "AGING",
                "reason": "锚点老化，仅保留探索级提示",
                "effective_confidence": st["effective_confidence"],
            }
        return {
            "action": "ALLOW",
            "status": "ACTIVE",
            "effective_confidence": st["effective_confidence"],
        }


def anchored_washout(
    baseline_map,
    gold_runs,
    now,
    vault,
    *,
    endpoint,
    min_gold_agreement=0.90,
    rel_tol=0.05,
):
    """带有效期参考锚点守护的洗脱。返回 (new_map, report)。

    gold_runs: {mol_id: [(value, ts), ...]} —— 必须逐个过 Vault 校验。
    """
    from .baseline_governance import washout

    chain = vault.verify_chain()
    if not chain["ok"]:
        raise RuntimeError("锚点库链完整性校验失败，禁止洗脱: %s" % chain["broken"][:2])
    approved_gold = {}
    rejected = []
    for mid, runs in (gold_runs or {}).items():
        vals = [v for v, _ in runs]
        mean = sum(vals) / len(vals)
        gate = vault.decision_gate(mid, endpoint, now)
        if gate["action"] == "LOCK_AND_UNDETERMINED":
            rejected.append(
                {"mol_id": mid, "reason": gate["status"], "detail": gate["reason"]}
            )
            continue
        v = vault.validate(mid, endpoint, mean, rel_tol=rel_tol)
        if v["ok"]:
            approved_gold[mid] = runs
        else:
            rejected.append(
                {"mol_id": mid, "reason": v["reason"], "detail": v["detail"]}
            )
    new_map, base_report = washout(
        baseline_map, approved_gold, now, min_gold_agreement=min_gold_agreement
    )
    report = dict(base_report)
    report.update(
        {
            "anchor_rejected": rejected,
            "n_anchor_rejected": len(rejected),
            "chain": chain,
            "note": "被拒分子保留历史并标 needs_washout；不得用污染金标准覆盖",
        }
    )
    return new_map, report
