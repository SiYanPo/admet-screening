# -*- coding: utf-8 -*-
"""同行评审 §6 Phase 1（B19）：命令分层与 evidence_role 声明骨架。

报告 P1-2："CLI 4,761 行、104 命令；新增命令要同时改 parser/dispatch/文档/smoke；
审稿人分不清'结论链'与'演示'。" 建议每命令声明 input_contract/output_contract/
evidence_role，并按 core/sources/decision/evidence/experimental 分层。

本模块先建立**声明层**（不改 CLI 结构，避免一次大重构引发回归）：
  - ROLES：命令 → (layer, evidence_role, input_contract, output_contract)
  - evidence_role ∈ decision_chain | evidence_only | governance | io_utility | experimental
  - validate_registry()：确保 CLI 每个命令都有声明（未登记 → 失败，禁止悄悄新增）
  - claimable(cmd)：该命令的产物是否允许进入结论链

注意：这只是"分层骨架 + 角色声明"，**不等同**于 CLI 拆到 <800 行（报告建议的
物理拆分属多轮工程，见 references/PEER_REVIEW_ROADMAP.md 的诚实排期）。
"""

from __future__ import annotations

import re
import os

# (layer, evidence_role, input_contract, output_contract)
_ROWS = {
    # --- core：数据入口/状态/复现，不直接给结论 ---
    "normalize": ("core", "io_utility", "smiles-or-file", "compounds.csv"),
    "saturate": ("core", "io_utility", "wide-table", "saturation.csv"),
    "validate": ("core", "governance", "long-tables", "validation.json"),
    "snapshot-summary": ("core", "io_utility", "outdir", "snapshot.json"),
    "snapshot-verify": ("core", "governance", "snapshot", "verify.json"),
    "release-check": ("core", "governance", "repo", "gate.json"),
    "env-audit": ("core", "governance", "environment", "env_audit.json"),
    "env-fp": ("core", "governance", "environment", "fingerprint.json"),
    "report": ("core", "io_utility", "artifacts", "report.md"),
    "reporting": ("core", "io_utility", "artifacts", "reporting.csv"),
    "ledger": ("core", "governance", "artifacts", "ledger.csv"),
    "readback": ("core", "governance", "artifacts", "readback.json"),
    "merge": ("core", "io_utility", "long-tables", "merged.csv"),
    "interop": ("core", "io_utility", "artifacts", "interop.csv"),
    # --- sources：外部源适配/摄取，产物是测量不是结论 ---
    "chembl": ("sources", "evidence_only", "compounds.csv", "measurements.csv"),
    "bt": ("sources", "evidence_only", "compounds.csv", "metabolites.csv"),
    "web": ("sources", "evidence_only", "query", "raw.json"),
    "xeno-ingest": ("sources", "evidence_only", "manual-file", "measurements.csv"),
    "xeno-prep": ("sources", "evidence_only", "compounds.csv", "prep.csv"),
    "external": ("sources", "evidence_only", "dataset", "measurements.csv"),
    "glycoside-hyd": ("sources", "evidence_only", "compounds.csv", "measurements.csv"),
    "acyl-glucuronide": (
        "sources",
        "evidence_only",
        "compounds.csv",
        "measurements.csv",
    ),
    "gut-micro": ("sources", "evidence_only", "compounds.csv", "metabolites.csv"),
    "cardiac": ("sources", "evidence_only", "compounds.csv", "cardiac_panel.csv"),
    "pka": ("sources", "evidence_only", "compounds.csv", "pka.csv"),
    "transport": ("sources", "evidence_only", "compounds.csv", "measurements.csv"),
    "background": ("sources", "evidence_only", "compounds.csv", "background.csv"),
    # --- decision：进结论链的裁决/弃权/封顶 ---
    "trust": ("decision", "decision_chain", "compounds+measurements", "trust.csv"),
    "reliab": ("decision", "decision_chain", "measurements", "reliability.csv"),
    "tier": ("decision", "decision_chain", "reliability+coverage", "tier.csv"),
    "rank": ("decision", "decision_chain", "reliability", "ranking.csv"),
    "desire": ("decision", "decision_chain", "scores", "desirability.csv"),
    "selective": ("decision", "decision_chain", "risk-pairs", "abstention.csv"),
    "abstain-why": ("decision", "decision_chain", "abstention", "attribution.csv"),
    "advisory-check": ("decision", "decision_chain", "decision", "advisory.json"),
    "certainty": ("decision", "decision_chain", "decision", "certainty.csv"),
    "coverage-gate": ("decision", "decision_chain", "coverage", "gate.json"),
    "qaf": ("decision", "decision_chain", "reliability", "qaf.csv"),
    "claims-fragility": ("decision", "decision_chain", "claims", "fragility.csv"),
    "decision-value": ("decision", "decision_chain", "decisions+truth", "value.csv"),
    # --- evidence：基准/消融/覆盖/多重性——支撑或反驳结论，不等于结论 ---
    "benchmark": ("evidence", "evidence_only", "predictions+truth", "benchmark.csv"),
    "ablate": ("evidence", "evidence_only", "panel+truth", "ablation_summary.csv"),
    "prospect": ("evidence", "evidence_only", "measurements+truth", "prospective.csv"),
    "conformal": ("evidence", "evidence_only", "pred+truth", "conformal.csv"),
    "conformal-check": ("evidence", "evidence_only", "conformal", "check.json"),
    "conformal-class": (
        "evidence",
        "evidence_only",
        "pred+truth",
        "class_coverage.csv",
    ),
    "conformal-scale": ("evidence", "evidence_only", "conformal", "scale.csv"),
    "cross-class": ("evidence", "evidence_only", "panel", "cross_class.csv"),
    "baseline": ("evidence", "evidence_only", "train+test", "baseline.csv"),
    "estimand": ("evidence", "evidence_only", "decisions", "estimand.csv"),
    "prereg-status": ("evidence", "governance", "prereg", "status.json"),
    "prereg-init": ("evidence", "governance", "criteria-json", "prereg.jsonl"),
    "independence": ("evidence", "evidence_only", "sources", "independence.csv"),
    "indep-bayes": ("evidence", "evidence_only", "raters", "posterior.csv"),
    "indep-power": ("evidence", "evidence_only", "raters", "power.csv"),
    "knn-sensitivity": (
        "evidence",
        "evidence_only",
        "threshold-grid",
        "sensitivity.csv",
    ),
    "sensitize": ("evidence", "evidence_only", "decisions", "sensitivity.csv"),
    "source-admit": (
        "evidence",
        "evidence_only",
        "source-measurements",
        "admission.json",
    ),
    "source-health": ("evidence", "evidence_only", "sources", "health.csv"),
    "source-rho": ("evidence", "evidence_only", "source-scores", "rho.csv"),
    "interference": (
        "evidence",
        "evidence_only",
        "version-banner",
        "interference.json",
    ),
    "landscape": ("evidence", "evidence_only", "decisions", "landscape.csv"),
    "perturb": ("evidence", "evidence_only", "decisions", "perturb.csv"),
    "pred-shift": ("evidence", "evidence_only", "compounds", "shift.csv"),
    "failure-modes": ("evidence", "evidence_only", "artifacts", "failure_modes.csv"),
    "fail-layers": ("evidence", "evidence_only", "artifacts", "fail_layers.csv"),
    "dst": ("evidence", "evidence_only", "scores", "dst.csv"),
    "endpoint-tiers": ("evidence", "evidence_only", "endpoints", "tiers.csv"),
    "coverage": (
        "evidence",
        "evidence_only",
        "measurements+truth",
        "coverage_matrix.csv",
    ),
    "transfer": ("evidence", "evidence_only", "datasets", "transfer.csv"),
    "abstain-cmp": ("evidence", "evidence_only", "abstention", "compare.csv"),
    # --- experimental：实验性/演示，不得进生产结论链 ---
    "pbpk": ("experimental", "experimental", "compounds", "pbpk.csv"),
    "pbpk-qualify": ("experimental", "experimental", "pbpk", "qualify.json"),
    "pd": ("experimental", "experimental", "compounds", "pd.csv"),
    "regaloside-ab": ("experimental", "experimental", "compounds", "case.csv"),
    "sar": ("experimental", "experimental", "compounds", "sar.csv"),
    "ac-plan": ("experimental", "experimental", "compounds", "plan.csv"),
    "local-tools": ("experimental", "experimental", "smiles", "local.csv"),
}

ROLES = {
    k: dict(layer=v[0], evidence_role=v[1], input_contract=v[2], output_contract=v[3])
    for k, v in _ROWS.items()
}


def cli_commands():
    """从 adt/cli.py 的 add_parser(...) 调用抽命令名（不重复硬编码）。"""
    here = os.path.dirname(os.path.abspath(__file__))
    src = open(os.path.join(here, "cli.py"), encoding="utf-8").read()
    return sorted(set(re.findall(r'add_parser\(\s*["\']([\w\-]+)["\']', src)))


def validate_registry():
    """返回 (ok, undeclared, stale)：CLI 有但没声明 / 声明了但 CLI 没有。"""
    cmds = set(cli_commands())
    undeclared = sorted(cmds - set(ROLES))
    stale = sorted(set(ROLES) - cmds)
    return (not undeclared and not stale), undeclared, stale


def claimable(command):
    """该命令产物是否允许进入结论链；未登记命令默认 False（fail-closed）。"""
    r = ROLES.get(command)
    return bool(r and r["evidence_role"] == "decision_chain")
