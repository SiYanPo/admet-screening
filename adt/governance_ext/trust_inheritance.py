# -*- coding: utf-8 -*-
"""盲区2：跨系统信任继承（Trust Inheritance Protocol）。

带封印的 SDF 进入 Schrodinger/MOE 被改一个原子再存回 ELN 后，
原 HMAC/Merkle/零宽水印必然全毁。不能要求第三方软件保留我们的水印，
但可以让"可信度来源"通过独立的 lineage_id 延续：

  - 每一个原始封印生成一个全局 lineage_id（基于输入承诺+信封摘要）；
  - 派生时只传 lineage_id + child_hash + operation + actor；
  - 账本只追加，事件间哈希链；
  - 任何团队凭 lineage_id 可查祖先封印、修改链与当前允许的最高 tier。

关键规则（防止"改一个原子就继承 T2"）：
  * 派生件（结构被修改）默认封顶 T1（INHERITED_DERIVED）；
  * 祖先含 EXEMPTED / T0_STRIPPED → 封顶 T0；
  * 无 lineage_id 或链断裂 → fail-closed 到 T0_STRIPPED。
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass

DEMO_KEY = b"admet-trust-inheritance-2026"


def make_lineage_id(input_commitment, envelope_id=None, *, salt="lineage-v1"):
    body = {
        "input_commitment": input_commitment,
        "envelope_id": envelope_id,
        "salt": salt,
    }
    return (
        "LIN-"
        + hashlib.sha256(
            json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()[:24]
    )


@dataclass(frozen=True)
class LineageEvent:
    event_id: str
    lineage_id: str
    child_hash: str
    operation: str
    actor: str
    prev_hash: str
    ancestor_tier: str
    sig: str


class DerivationLedger:
    def __init__(self, key=None):
        self.key = key or DEMO_KEY
        self._events = []
        self._by_lineage = {}

    @staticmethod
    def _body(d):
        return json.dumps(
            d, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")

    def record_origin(self, *, input_commitment, envelope_id, ancestor_tier):
        lid = make_lineage_id(input_commitment, envelope_id)
        if lid in self._by_lineage:
            return lid
        body = {
            "event_id": "ORIGIN",
            "lineage_id": lid,
            "child_hash": input_commitment,
            "operation": "SEAL",
            "actor": "system",
            "prev_hash": "GENESIS",
            "ancestor_tier": ancestor_tier,
        }
        sig = hmac.new(self.key, self._body(body), hashlib.sha256).hexdigest()
        ev = LineageEvent(sig=sig, **body)
        self._events.append(ev)
        self._by_lineage.setdefault(lid, []).append(ev)
        return lid

    def derive(self, lineage_id, *, child_hash, operation, actor, ancestor_tier=None):
        chain = self._by_lineage.get(lineage_id)
        if not chain:
            raise KeyError("未知 lineage_id，拒绝建立派生关系")
        prev = chain[-1]
        base_tier = ancestor_tier or prev.ancestor_tier
        event_id = hashlib.sha256(
            ("%s|%s|%s" % (lineage_id, child_hash, operation)).encode("utf-8")
        ).hexdigest()[:16]
        body = {
            "event_id": event_id,
            "lineage_id": lineage_id,
            "child_hash": child_hash,
            "operation": str(operation)[:120],
            "actor": actor,
            "prev_hash": prev.sig,
            "ancestor_tier": base_tier,
        }
        sig = hmac.new(self.key, self._body(body), hashlib.sha256).hexdigest()
        ev = LineageEvent(sig=sig, **body)
        self._events.append(ev)
        chain.append(ev)
        return ev

    def verify_chain(self, lineage_id=None):
        chains = (
            {lineage_id: self._by_lineage[lineage_id]}
            if lineage_id
            else self._by_lineage
        )
        broken = []
        for lid, evs in chains.items():
            prev = "GENESIS"
            for i, ev in enumerate(evs):
                body = {
                    "event_id": ev.event_id,
                    "lineage_id": ev.lineage_id,
                    "child_hash": ev.child_hash,
                    "operation": ev.operation,
                    "actor": ev.actor,
                    "prev_hash": ev.prev_hash,
                    "ancestor_tier": ev.ancestor_tier,
                }
                if ev.prev_hash != prev:
                    broken.append(
                        {"lineage_id": lid, "index": i, "reason": "prev_hash_mismatch"}
                    )
                if not hmac.compare_digest(
                    hmac.new(self.key, self._body(body), hashlib.sha256).hexdigest(),
                    ev.sig,
                ):
                    broken.append(
                        {"lineage_id": lid, "index": i, "reason": "sig_mismatch"}
                    )
                prev = ev.sig
        return {
            "ok": not broken,
            "n_chains": len(chains),
            "n_events": sum(len(v) for v in chains.values()),
            "broken": broken,
        }

    def effective_trust(self, lineage_id, *, child_hash=None):
        """查询派生件可用的最高可信档位。"""
        chain = self._by_lineage.get(lineage_id)
        if not chain:
            return {
                "tier": "T0_STRIPPED",
                "allowed": False,
                "reason": "NO_LINEAGE",
                "ancestor": None,
            }
        if not self.verify_chain(lineage_id)["ok"]:
            return {
                "tier": "T0_STRIPPED",
                "allowed": False,
                "reason": "CHAIN_BROKEN",
                "ancestor": chain[0].ancestor_tier,
            }
        if child_hash is not None:
            matches = [e for e in chain if e.child_hash == child_hash]
            if not matches:
                return {
                    "tier": "T0_STRIPPED",
                    "allowed": False,
                    "reason": "CHILD_HASH_UNKNOWN",
                    "ancestor": chain[0].ancestor_tier,
                }
        origin = chain[0].ancestor_tier
        n_derive = sum(1 for e in chain if e.operation != "SEAL")
        if "EXEMPTED" in str(origin) or "T0" in str(origin):
            tier, reason = "T0", "ANCESTOR_T0_OR_EXEMPTED"
        elif n_derive > 0:
            tier, reason = "T1", "DERIVED_STRUCTURE_NOT_REVERIFIED"
        else:
            tier, reason = str(origin), "ORIGINAL_SEAL"
        return {
            "tier": tier,
            "allowed": tier in ("T2", "T3"),
            "reason": reason,
            "ancestor": origin,
            "n_derivations": n_derive,
            "events": [e.event_id for e in chain],
            "note": "信任来源可查；派生件不得自动继承高可信结论",
        }
