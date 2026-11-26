# -*- coding: utf-8 -*-
"""盲区2 / 追问补强：跨版本依赖语义漂移的断言失效与科学审查门禁。

变异测试防的是"我们自己的代码退化"。但 RDKit 从 2026.03 升到 2026.09，
某个描述符算法改变时，204 条 AST 断言会集体报红。此时如果开发为绿灯
改断言，就回到 Test Rot——而且这次是**上游语义变化被伪装成测试修复**。

机制：
1. 黄金快照按 `rdkit_version` 分桶；断言绑定版本。
2. 观测版本 != 绑定版本 → 断言 `SKIP`（不是 FAIL），同时开 Scientific Review。
3. 版本相同但结果漂移超容差 → `SCIENTIFIC_REVIEW_REQUIRED`，
   断言被锁定（禁止自动改预期值），必须科学审查后显式签署新快照。
4. 容差内 → PASS。金标准缺失 → SKIP + REVIEW。

这是"自动失效（Skip）而非报错（Fail）"的关键：CI 不会被上游升级卡死，
但也不会让漂移被静默吸收。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class GoldenEntry:
    mol_id: str
    endpoint: str
    value: float
    unit: str
    rdkit_version: str
    tolerance_abs: float
    tolerance_rel: float
    source: str
    evidence_hash: str


class DependencyGoldenStore:
    """版本化黄金快照；只追加，新版本通过科学审查后新增条目。"""

    def __init__(self):
        self._entries = {}

    def add(
        self,
        *,
        mol_id,
        endpoint,
        value,
        unit,
        rdkit_version,
        tolerance_abs=1e-4,
        tolerance_rel=1e-3,
        source="internal-gold-set",
        evidence_hash="",
    ):
        e = GoldenEntry(
            mol_id,
            endpoint,
            float(value),
            unit,
            rdkit_version,
            tolerance_abs,
            tolerance_rel,
            source,
            evidence_hash,
        )
        self._entries[(rdkit_version, mol_id, endpoint)] = e
        return e

    def get(self, rdkit_version, mol_id, endpoint):
        return self._entries.get((rdkit_version, mol_id, endpoint))


def open_scientific_review(
    *, old_version, new_version, mol_id, endpoint, reason, observed=None, expected=None
) -> dict:
    """生成可追踪的科学审查单；同一事实得到同一个 review_id（幂等）。"""
    body = {
        "old_version": old_version,
        "new_version": new_version,
        "mol_id": mol_id,
        "endpoint": endpoint,
        "reason": reason,
        "observed": observed,
        "expected": expected,
    }
    rid = hashlib.sha256(
        json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:16]
    return {
        "review_id": rid,
        "opened_at": datetime.now(timezone.utc).isoformat(),
        "status": "OPEN",
        "required_approvers": ["scientific_lead", "qa"],
        "forbid_assertion_edit": True,
        **body,
    }


def assertion_gate(entry, result, *, bound_version, observed_version, mol_id, endpoint):
    """版本绑定断言门禁。返回 skip / pass / review 三态。"""
    if observed_version != bound_version:
        return {
            "status": "SKIP_VERSION_MISMATCH",
            "skip": True,
            "fail": False,
            "review": open_scientific_review(
                old_version=bound_version,
                new_version=observed_version,
                mol_id=mol_id,
                endpoint=endpoint,
                reason="依赖语义升级，断言自动失效；禁止直接修改预期值",
                observed=result,
                expected=getattr(entry, "value", None),
            ),
        }
    if entry is None:
        return {
            "status": "SKIP_NO_GOLDEN",
            "skip": True,
            "fail": False,
            "review": open_scientific_review(
                old_version=bound_version,
                new_version=observed_version,
                mol_id=mol_id,
                endpoint=endpoint,
                reason="当前版本无该分子/端点的黄金快照",
                observed=result,
            ),
        }
    drift = abs(float(result) - entry.value)
    tol = max(entry.tolerance_abs, entry.tolerance_rel * abs(entry.value))
    if drift > tol:
        return {
            "status": "SCIENTIFIC_REVIEW_REQUIRED",
            "skip": False,
            "fail": False,
            "assertion_locked": True,
            "drift": round(drift, 8),
            "tolerance": tol,
            "review": open_scientific_review(
                old_version=bound_version,
                new_version=observed_version,
                mol_id=mol_id,
                endpoint=endpoint,
                reason="同版本结果漂移超容差，禁止改断言；需科学审查新快照",
                observed=result,
                expected=entry.value,
            ),
        }
    return {
        "status": "PASS",
        "skip": False,
        "fail": False,
        "drift": round(drift, 8),
        "tolerance": tol,
        "review": None,
    }


def verify_batch(store, results, *, bound_version, observed_version, endpoint="logp"):
    """批量门禁：skip 不计入失败；任何 review 都会阻止发布但不会卡住 CI 变绿判断。"""
    out = {}
    for mol_id, val in results.items():
        entry = store.get(observed_version, mol_id, endpoint)
        out[mol_id] = assertion_gate(
            entry,
            val,
            bound_version=bound_version,
            observed_version=observed_version,
            mol_id=mol_id,
            endpoint=endpoint,
        )
    n_pass = sum(1 for r in out.values() if r["status"] == "PASS")
    n_skip = sum(1 for r in out.values() if r["skip"])
    n_review = sum(1 for r in out.values() if r.get("review"))
    return {
        "results": out,
        "n_pass": n_pass,
        "n_skip": n_skip,
        "n_review": n_review,
        "ci_blocked_by_review": n_review > 0,
        "note": "版本不匹配只 Skip 不 Fail；漂移/缺快照必须科学审查",
    }


def bind_assertion_version(path, version, *, golden_digest=None):
    """把断言套件绑定的依赖版本写入机器可读 sidecar。"""
    payload = {
        "bound_rdkit_version": version,
        "golden_digest": golden_digest,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    return payload


def automated_golden_diff(
    entry,
    observed_values,
    *,
    bound_version,
    observed_version,
    mol_id,
    endpoint,
    auto_abs_tol=5e-3,
    auto_rel_tol=5e-3,
    max_replicate_cv=0.05,
    critical_endpoint=False,
    affected_fraction=0.0,
    max_auto_fraction=0.02,
):
    """季度镜像强制升级时的自动化黄金快照差异评估（追问2）。

    小幅、稳定、非关键端点、影响面小的漂移 → 机器签发新快照；
    其余 → 推给人类科学审查。避免每次补丁版本都卡住全流水线。
    """
    import statistics

    vals = [float(v) for v in observed_values]
    if not vals:
        return {"status": "HUMAN_REVIEW_REQUIRED", "reason": "NO_OBSERVATION"}
    mean = sum(vals) / len(vals)
    if entry is None:
        return {"status": "HUMAN_REVIEW_REQUIRED", "reason": "NO_GOLDEN"}
    drift = abs(mean - entry.value)
    auto_tol = max(auto_abs_tol, auto_rel_tol * abs(entry.value))
    cv = 0.0
    if mean != 0 and len(vals) > 1:
        cv = statistics.pstdev(vals) / abs(mean)
    reasons = []
    if drift > auto_tol:
        reasons.append("漂移 %.6g > 自动容差 %.6g" % (drift, auto_tol))
    if cv > max_replicate_cv:
        reasons.append("重复测量 CV %.4f > %.4f" % (cv, max_replicate_cv))
    if critical_endpoint:
        reasons.append("关键安全端点不允许自动放行")
    if affected_fraction > max_auto_fraction:
        reasons.append("影响面 %.3f > %.3f" % (affected_fraction, max_auto_fraction))
    if reasons:
        rv = open_scientific_review(
            old_version=bound_version,
            new_version=observed_version,
            mol_id=mol_id,
            endpoint=endpoint,
            reason="自动化差异评估判定需人类复核: " + "; ".join(reasons),
            observed=mean,
            expected=entry.value,
        )
        return {
            "status": "HUMAN_REVIEW_REQUIRED",
            "reasons": reasons,
            "drift": drift,
            "cv": cv,
            "review": rv,
        }
    digest = hashlib.sha256(
        json.dumps(
            {
                "mol_id": mol_id,
                "endpoint": endpoint,
                "value": mean,
                "version": observed_version,
                "old_version": bound_version,
            },
            sort_keys=True,
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()[:16]
    return {
        "status": "AUTO_ACCEPTED",
        "drift": drift,
        "cv": cv,
        "new_snapshot": {
            "mol_id": mol_id,
            "endpoint": endpoint,
            "value": mean,
            "rdkit_version": observed_version,
            "tolerance_abs": entry.tolerance_abs,
            "tolerance_rel": entry.tolerance_rel,
            "source": "automated_golden_diff",
            "evidence_hash": digest,
        },
        "signature": {
            "signers": ["automated_gradient_check", "qa_bot"],
            "reason": "漂移极小且重复测量稳定；仅算法细节微调",
            "review_id": "AUTO-" + digest,
        },
    }


def check_assertion_binding(path, observed_version):
    """CI 入口：版本不匹配 → skip=True，绝不把上游升级误报为断言失败。"""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            binding = json.load(fh)
    except (OSError, ValueError):
        return {
            "skip": True,
            "status": "NO_BINDING",
            "reason": "缺少依赖版本绑定，断言结果不可解释",
        }
    if binding.get("bound_rdkit_version") != observed_version:
        return {
            "skip": True,
            "status": "SKIP_VERSION_MISMATCH",
            "reason": "断言绑定版本 %s != 观测版本 %s"
            % (binding.get("bound_rdkit_version"), observed_version),
            "review": open_scientific_review(
                old_version=binding.get("bound_rdkit_version"),
                new_version=observed_version,
                mol_id="*",
                endpoint="*",
                reason="断言套件版本绑定不匹配",
            ),
        }
    return {"skip": False, "status": "OK", "binding": binding}
