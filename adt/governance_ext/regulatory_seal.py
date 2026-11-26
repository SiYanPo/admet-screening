# -*- coding: utf-8 -*-
"""监管级联合封印（Regulatory Joint-Seal）+ 21 CFR Part 11 电子签名信封。

ZKP/哈希承诺只能证明"我持有能生成该承诺的输入原文"；监管审计还要求
"当时运行的代码与环境就是被批准的那一份"。本模块把四类证据绑在一起：

  1. input_commitment / merkle_root  —— 输入分子的盲化承诺（zk_audit）
  2. algorithm_hash                  —— 本包所有 .py 源文件的确定性哈希
                                         （生产用 git commit + 构建产物摘要）
  3. environment_fingerprint         —— Python/RDKit/平台/容器镜像摘要
  4. execution_manifest_digest       —— 本次执行的 tier / gates / budget 摘要

再用 HMAC 电子签名绑定 signer / meaning / reason / timestamp / record_digest，
形成可自证"算法未篡改、环境一致、输入未换、结论未被改写"的合规信封。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import platform
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class SignerCredential:
    signer_id: str
    name: str
    role: str
    key_fingerprint: str
    active: bool = True


class SignerRegistry:
    """Part 11 Attributable：签名绑定唯一 signer_id + 凭证指纹，而非共享角色账户。"""

    def __init__(self):
        self._signers = {}

    def register(self, *, signer_id, name, role, key_fingerprint, active=True):
        if not signer_id or not key_fingerprint:
            raise ValueError("signer_id 与凭证指纹必填")
        c = SignerCredential(signer_id, name, role, key_fingerprint, bool(active))
        self._signers[signer_id] = c
        return c

    def verify(self, signer_id, key_fingerprint):
        c = self._signers.get(signer_id)
        if c is None:
            return {"ok": False, "reason": "UNKNOWN_SIGNER"}
        if not c.active:
            return {"ok": False, "reason": "SIGNER_INACTIVE"}
        if not hmac.compare_digest(c.key_fingerprint, str(key_fingerprint)):
            return {"ok": False, "reason": "CREDENTIAL_MISMATCH"}
        return {"ok": True, "signer": c}


class AuditChain:
    """只追加审计链：CREATE / MODIFY / SIGN 事件，任何历史改写都会断链。"""

    def __init__(self, key=None):
        self.key = key or DEMO_KEY
        self.events = []

    @staticmethod
    def _body(d):
        return json.dumps(
            d, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")

    def append(self, event_type, *, actor, payload):
        prev = self.events[-1]["sig"] if self.events else "GENESIS"
        body = {
            "event_type": str(event_type).upper()[:20],
            "actor": str(actor)[:80],
            "payload": payload,
            "prev_hash": prev,
            "at": datetime.now(timezone.utc).isoformat(),
        }
        sig = hmac.new(self.key, self._body(body), hashlib.sha256).hexdigest()
        ev = {**body, "sig": sig}
        self.events.append(ev)
        return ev

    @property
    def head(self):
        return self.events[-1]["sig"] if self.events else "GENESIS"

    def verify(self):
        prev = "GENESIS"
        broken = []
        for i, ev in enumerate(self.events):
            body = {
                k: ev[k] for k in ("event_type", "actor", "payload", "prev_hash", "at")
            }
            if ev["prev_hash"] != prev:
                broken.append({"index": i, "reason": "prev_hash_mismatch"})
            if not hmac.compare_digest(
                hmac.new(self.key, self._body(body), hashlib.sha256).hexdigest(),
                ev["sig"],
            ):
                broken.append({"index": i, "reason": "sig_mismatch"})
            prev = ev["sig"]
        return {
            "ok": not broken,
            "n_events": len(self.events),
            "head": self.head,
            "broken": broken,
        }


@dataclass(frozen=True)
class TrustDomainConfig:
    """密钥/记录/测量三者必须可配置到不同信任域。"""

    key_store_domain: str
    record_store_domain: str
    measurement_domain: str


def trust_domain_gate(config: TrustDomainConfig):
    domains = [
        config.key_store_domain,
        config.record_store_domain,
        config.measurement_domain,
    ]
    reasons = []
    if any(not d or d == "same" for d in domains):
        reasons.append("存在未配置或共置的信任域")
    if len(set(domains)) < 3:
        reasons.append("密钥/记录/测量未分离到三个独立域")
    return {
        "ok": not reasons,
        "reasons": reasons,
        "domains": domains,
        "note": "代码只能验证配置；实际隔离强度仍取决于 KMS/不可变存储/独立测量代理",
    }


DEMO_KEY = b"admet-regulatory-joint-seal-2026-11"


def source_tree_hash(source_root=None):
    """确定性源码哈希：按相对路径排序后拼接路径+字节。"""
    root = source_root or os.path.dirname(os.path.abspath(__file__))
    h = hashlib.sha256()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d != "__pycache__")
        for fn in sorted(filenames):
            if not fn.endswith(".py"):
                continue
            path = os.path.join(dirpath, fn)
            rel = os.path.relpath(path, root).replace("\\", "/")
            h.update(rel.encode("utf-8"))
            with open(path, "rb") as fh:
                h.update(fh.read())
    return h.hexdigest()


def git_commit(source_root=None):
    """有 git 时取 HEAD；没有也不阻断（源哈希始终存在）。"""
    root = source_root or os.path.dirname(os.path.abspath(__file__))
    try:
        p = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return p.stdout.strip() if p.returncode == 0 else "unavailable"
    except Exception:
        return "unavailable"


def environment_fingerprint(extra=None):
    """环境指纹：官方镜像 digest 由 CI/容器注入，避免依赖进程环境噪声。"""
    rdkit_v = "unavailable"
    try:
        import rdkit

        rdkit_v = rdkit.__version__
    except Exception:
        pass
    parts = {
        "python": platform.python_version(),
        "rdkit": rdkit_v,
        "platform": platform.platform(),
        "image_digest": os.environ.get("CONTAINER_IMAGE_DIGEST", "unspecified"),
        "build_id": os.environ.get("BUILD_ID", "unspecified"),
        "extra": sorted(extra or []),
    }
    return hashlib.sha256(
        json.dumps(
            parts, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def record_digest(record: dict) -> str:
    """记录摘要；SMILES 等原始结构不进入信封。"""
    clean = {
        k: v
        for k, v in dict(record).items()
        if k not in ("smiles", "calc_smiles", "payload")
    }
    return hashlib.sha256(
        json.dumps(
            clean,
            sort_keys=True,
            ensure_ascii=False,
            default=str,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


class RegulatorySeal:
    def __init__(
        self,
        key=None,
        *,
        source_root=None,
        expected_algorithm_hash=None,
        expected_env_fingerprint=None,
    ):
        self.key = key or DEMO_KEY
        self.source_root = source_root
        self.expected_algorithm_hash = expected_algorithm_hash
        self.expected_env_fingerprint = expected_env_fingerprint

    @staticmethod
    def _body(d):
        return json.dumps(
            d, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")

    def seal(
        self,
        record,
        *,
        input_commitment,
        input_root,
        execution_manifest_digest,
        signer,
        meaning,
        reason,
        endpoint=None,
        tier=None,
        audit_chain=None,
        signer_registry=None,
        signer_id=None,
        key_fingerprint=None,
    ):
        """生成带电子签名的联合封印；可选写入只追加审计链。"""
        if not signer or not meaning or not reason or len(str(reason)) < 8:
            raise ValueError("电子签名必须含 signer / meaning / 具体 reason(>=8字符)")
        attribution = None
        if signer_registry is not None:
            attribution = signer_registry.verify(signer_id, key_fingerprint)
            if not attribution["ok"]:
                raise PermissionError("签名归因失败: %s" % attribution["reason"])
        algo = source_tree_hash(self.source_root)
        envfp = environment_fingerprint()
        audit_head = audit_chain.head if audit_chain is not None else None
        body = {
            "input_commitment": input_commitment,
            "input_root": input_root,
            "algorithm_hash": algo,
            "algorithm_git_commit": git_commit(self.source_root),
            "environment_fingerprint": envfp,
            "execution_manifest_digest": execution_manifest_digest,
            "record_digest": record_digest(record),
            "endpoint": endpoint,
            "tier": tier or str(record.get("tier_ceiling", "T0")),
            "signer": signer,
            "meaning": meaning,
            "signer_id": signer_id or signer,
            "signer_key_fingerprint": key_fingerprint,
            "reason": str(reason)[:300],
            "signed_at": datetime.now(timezone.utc).isoformat(),
            "protocol": "21cfr11-joint-seal-v1",
            "audit_prev_head": audit_head,
        }
        if audit_chain is not None:
            ev = audit_chain.append(
                "SIGN",
                actor=signer_id or signer,
                payload={
                    "record_digest": body["record_digest"],
                    "input_commitment": input_commitment,
                    "tier": body["tier"],
                    "meaning": meaning,
                },
            )
            body["audit_event_id"] = ev["sig"][:16]
            body["audit_head"] = audit_chain.head
        sig = hmac.new(self.key, self._body(body), hashlib.sha256).hexdigest()
        return {
            "payload": body,
            "signature": sig,
            "envelope_id": hashlib.sha256(
                (sig + body["record_digest"]).encode("utf-8")
            ).hexdigest()[:16],
        }

    def verify(
        self, envelope, *, record=None, verify_current_code=True, audit_chain=None
    ):
        body = envelope.get("payload")
        if not body:
            return {
                "ok": False,
                "status": "NO_PAYLOAD",
                "effective_class": "T0_STRIPPED",
            }
        expected = hmac.new(self.key, self._body(body), hashlib.sha256).hexdigest()
        sig_ok = hmac.compare_digest(expected, str(envelope.get("signature")))
        problems = []
        if not sig_ok:
            problems.append("signature")
        if record is not None and record_digest(record) != body.get("record_digest"):
            problems.append("record_digest")
        if self.expected_algorithm_hash and self.expected_algorithm_hash != body.get(
            "algorithm_hash"
        ):
            problems.append("algorithm_hash_not_approved")
        if self.expected_env_fingerprint and self.expected_env_fingerprint != body.get(
            "environment_fingerprint"
        ):
            problems.append("environment_fingerprint_not_approved")
        if verify_current_code and source_tree_hash(self.source_root) != body.get(
            "algorithm_hash"
        ):
            problems.append("code_changed_since_seal")
        if verify_current_code and environment_fingerprint() != body.get(
            "environment_fingerprint"
        ):
            problems.append("environment_changed_since_seal")
        if body.get("audit_head"):
            if audit_chain is None:
                problems.append("audit_chain_missing")
            else:
                chain = audit_chain.verify()
                if not chain["ok"]:
                    problems.append("audit_chain_broken")
                if chain["head"] != body.get("audit_head"):
                    problems.append("audit_head_mismatch")
        ok = not problems
        return {
            "ok": ok,
            "status": "OK" if ok else "TAMPERED_OR_DRIFTED",
            "problems": problems,
            "attribution": {
                "signer_id": body.get("signer_id"),
                "key_fingerprint": body.get("signer_key_fingerprint"),
            },
            "effective_class": body.get("tier", "T0") if ok else "T0_STRIPPED",
        }


def generate_deviation_report(record, grant, registry, *, seal=None) -> str:
    """带镣铐豁免流入申报流程前的监管偏差报告（Deviation Report）。"""
    v = registry.validate(record, grant)
    if not v["ok"]:
        raise PermissionError("无法为无效豁免生成偏差报告: %s" % v["reason"])
    e = record.get("exemption") or {}
    lines = [
        "# 偏差报告 / Deviation Report",
        "",
        "**状态：T0 — 禁止进入 IND/NDA 申报包（21 CFR Part 11 电子记录）**",
        "",
        "| 字段 | 内容 |",
        "| --- | --- |",
        "| deviation_id | %s |" % grant.eid,
        "| 触发规则 | %s |" % record.get("exempted_rule", "absolute_redline"),
        "| 触发原因 | %s |" % str(record.get("reason"))[:160],
        "| 原始红线详情 | %s |"
        % str(record.get("detail") or record.get("fast_guard"))[:300],
        "| 签发人（首席科学家） | %s |" % grant.chief_scientist,
        "| 合规见证人 | %s |" % grant.compliance_witness,
        "| 豁免理由 | %s |" % grant.reason,
        "| 有效期 | %s |"
        % datetime.fromtimestamp(grant.exp, tz=timezone.utc).isoformat(),
        "| 哈希链前序 | %s |" % grant.prev_hash[:16],
        "| 影响评估 | 结论已降为 PASSTHRU/T0；不得用于定量决策、排序或申报 |",
        "| CAPA | 需要湿实验复核 + 新锚点双人签发；重跑 Rigorous 后方可申请解除 |",
        "",
        "> 本报告由系统自动生成，签署记录与联合封印一并归档；"
        "任何手工删改都会使 envelope 校验失败。",
    ]
    if seal is not None:
        lines += [
            "",
            "## 联合封印",
            "",
            "envelope_id: %s" % seal.get("envelope_id", "N/A"),
            "signature: %s" % str(seal.get("signature"))[:32],
        ]
    return "\n".join(lines)
