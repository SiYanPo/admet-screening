# -*- coding: utf-8 -*-
"""盲区3：首席科学家签发的带镣铐豁免权（Chained Exemption）。

绝对红线（NaN / MW<=0 / HBD>原子数 / 价键异常）不可被普通 Override 修改。
但真实的奇特天然产物或金属配位物可能触发红线；若系统只会 fail-closed，
整条研发管线会死锁。本模块允许**离线、实名、可追溯、带镣铐**的豁免：

镣铐（不可协商）：
  - 必须由首席科学家签发（+ 合规见证人），签名可验；
  - 绑定 inchikey + 具体规则 + 过期时间 + 前序豁免哈希链；
  - 一旦生效，结论强制 T0、verdict=PASSTHRU、
    certainty_modifier=low_unresolvable、发布门禁永久拒绝 T2/T3；
  - 报告带醒目红色横幅；豁免记录只追加，链断了就拒绝。

"不让流程死锁"指允许继续做探索性计算并保留计算值供内部排查，
不是允许把豁免结果包装成高可信结论。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass

DEMO_KEY = b"admet-chained-exemption-chief-scientist-2026"
RED_BANNER = (
    "⚠️ CHAINED EXEMPTION / 带镣铐豁免：本结果触发绝对红线，"
    "由首席科学家签发仅用于内部排查；强制 T0，禁止用于 T2/T3 申报包。"
)


@dataclass(frozen=True)
class ExemptionGrant:
    eid: str
    inchikey: str
    rule_id: str
    reason: str
    chief_scientist: str
    compliance_witness: str
    exp: int
    prev_hash: str
    sig: str


class ExemptionRegistry:
    def __init__(self, key=None):
        self.key = key or DEMO_KEY
        self._grants = []

    @staticmethod
    def _body(d):
        return json.dumps(
            d, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")

    def issue(
        self,
        *,
        inchikey,
        rule_id,
        reason,
        chief_scientist,
        compliance_witness,
        ttl_s=86400,
        eid=None,
    ):
        if not chief_scientist or not compliance_witness:
            raise PermissionError("带镣铐豁免必须首席科学家 + 合规见证人")
        if chief_scientist == compliance_witness:
            raise PermissionError("签发人与见证人不得为同一人")
        if not reason or len(str(reason)) < 10:
            raise ValueError("豁免理由必须 >=10 字符并写入审计链")
        prev = self._grants[-1].sig if self._grants else "GENESIS"
        eid = (
            eid
            or hashlib.sha256(
                ("%s|%s|%s|%s" % (inchikey, rule_id, chief_scientist, prev)).encode(
                    "utf-8"
                )
            ).hexdigest()[:16]
        )
        body = {
            "eid": eid,
            "inchikey": inchikey,
            "rule_id": rule_id,
            "reason": str(reason)[:300],
            "chief_scientist": chief_scientist,
            "compliance_witness": compliance_witness,
            "exp": int(time.time()) + int(ttl_s),
            "prev_hash": prev,
        }
        sig = hmac.new(self.key, self._body(body), hashlib.sha256).hexdigest()
        g = ExemptionGrant(sig=sig, **body)
        self._grants.append(g)
        return g

    def verify_chain(self):
        prev = "GENESIS"
        broken = []
        for i, g in enumerate(self._grants):
            if g.prev_hash != prev:
                broken.append({"index": i, "reason": "prev_hash_mismatch"})
            body = {
                "eid": g.eid,
                "inchikey": g.inchikey,
                "rule_id": g.rule_id,
                "reason": g.reason,
                "chief_scientist": g.chief_scientist,
                "compliance_witness": g.compliance_witness,
                "exp": g.exp,
                "prev_hash": g.prev_hash,
            }
            if not hmac.compare_digest(
                hmac.new(self.key, self._body(body), hashlib.sha256).hexdigest(), g.sig
            ):
                broken.append({"index": i, "reason": "sig_mismatch"})
            prev = g.sig
        return {"ok": not broken, "n": len(self._grants), "broken": broken}

    def validate(self, record, grant):
        chain = self.verify_chain()
        if not chain["ok"]:
            return {
                "ok": False,
                "reason": "CHAIN_BROKEN",
                "detail": chain["broken"][:2],
            }
        if not isinstance(grant, ExemptionGrant):
            return {"ok": False, "reason": "INVALID_GRANT_TYPE"}
        expected = hmac.new(
            self.key,
            self._body(
                {
                    "eid": grant.eid,
                    "inchikey": grant.inchikey,
                    "rule_id": grant.rule_id,
                    "reason": grant.reason,
                    "chief_scientist": grant.chief_scientist,
                    "compliance_witness": grant.compliance_witness,
                    "exp": grant.exp,
                    "prev_hash": grant.prev_hash,
                }
            ),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, grant.sig):
            return {"ok": False, "reason": "SIGNATURE_INVALID"}
        if grant.exp < int(time.time()):
            return {"ok": False, "reason": "EXPIRED"}
        if grant.inchikey != record.get("inchikey"):
            return {"ok": False, "reason": "INCHIKEY_MISMATCH"}
        return {"ok": True, "reason": "CHAINED_EXEMPTION_VALID", "eid": grant.eid}


def apply_exemption(record, registry, grant, *, red_line_rule="absolute_redline"):
    """豁免生效：允许继续探索，但结果被铐死在 T0。"""
    v = registry.validate(record, grant)
    if not v["ok"]:
        raise PermissionError("带镣铐豁免验证失败: %s" % v["reason"])
    out = dict(record)
    out["verdict"] = "PASSTHRU"
    out["tier_ceiling"] = "T0"
    out["certainty_modifier"] = "low_unresolvable"
    out["reason"] = "CHAINED_EXEMPTION"
    out["exempted_rule"] = grant.rule_id or red_line_rule
    out["exemption"] = {
        "eid": grant.eid,
        "chief_scientist": grant.chief_scientist,
        "compliance_witness": grant.compliance_witness,
        "exp": grant.exp,
        "banner": RED_BANNER,
    }
    out["audit_banner"] = RED_BANNER
    out["publish_allowed"] = False
    return out


def publish_gate(record) -> dict:
    """豁免结果永久不能进入 T2/T3 审计包。"""
    if (
        record.get("exemption")
        or record.get("reason") == "CHAINED_EXEMPTION"
        or str(record.get("tier_ceiling", "")).upper() == "T0"
    ):
        return {
            "allowed": False,
            "reason": "CHAINED_EXEMPTION_LOCKED_TO_T0",
            "required": "删除豁免并用合规分子重新走 Rigorous 流程",
        }
    tier = str(record.get("tier_ceiling", "")).upper()
    return {
        "allowed": tier in ("T2", "T3"),
        "reason": "publish_gate",
        "required": "T2 或 T3",
    }


def render_exempted_report(record) -> str:
    """醒目红色横幅 + 不可剥离的豁免 ID。"""
    e = record.get("exemption") or {}
    return "\n".join(
        [
            '<div style="background:#b00020;color:#fff;padding:12px;font-weight:bold">',
            RED_BANNER,
            "</div>",
            "",
            "豁免编号：%s" % e.get("eid", "UNKNOWN"),
            "签发：%s / 见证：%s"
            % (e.get("chief_scientist", "?"), e.get("compliance_witness", "?")),
            "判定级别：T0（不可升级）",
            "原始触发规则：%s" % record.get("exempted_rule", "absolute_redline"),
        ]
    )
