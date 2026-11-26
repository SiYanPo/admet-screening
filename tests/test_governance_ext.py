# -*- coding: utf-8 -*-
"""治理扩展层（adt.governance_ext）的移植后可用性回归。

只验证移植后模块可导入、关键契约可运行；完整 408 项原型断言仍在
adt_proto 仓内。实验层不进入主预测链，故此处只做最小但真实的调用。
"""
import os
import sys


def test_governance_ext_imports_and_core_contracts(tmp_path):
    from adt.governance_ext import (zk_audit, split_audit, trust_inheritance,
                                    uncertainty_quantification as uq)
    salt = "audit-salt"
    b = zk_audit.BlindAuditManifest(salt)
    man = b.build(["CCO", "c1ccccc1"], endpoint="herg",
                  execution_summary={"mode": "test"})
    pub = b.strip_private(man)
    ev = b.evidence(man, 0)
    assert zk_audit.verify_evidence(pub, ev, "CCO", salt, endpoint="herg")["ok"]

    rows = [{"smiles": "c1ccccc1", "label": 1, "pred": 1, "year": 2020},
            {"smiles": "c1ccncc1", "label": 0, "pred": 0, "year": 2021}]
    rep = split_audit.build_report(rows, max_gap=0.5)
    assert "random" in rep["metrics"] and "gate" in rep

    led = trust_inheritance.DerivationLedger()
    lid = led.record_origin(input_commitment="a" * 64, envelope_id="e1",
                            ancestor_tier="T2")
    led.derive(lid, child_hash="b" * 64, operation="edit", actor="u")
    assert led.effective_trust(lid, child_hash="b" * 64)["tier"] == "T1"
    assert led.verify_chain(lid)["ok"]

    assert uq.from_samples([0.2, 0.3])["ok"]
    assert uq.uq_gate({"value": 0.2, "std": 0.5, "variance": 0.25,
                       "smiles": "CCO"})["tier_ceiling"] == "T0"


def test_governance_ext_has_no_absolute_machine_paths():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    pkg = os.path.join(root, "adt", "governance_ext")
    bad = []
    for fn in os.listdir(pkg):
        if not fn.endswith(".py"):
            continue
        s = open(os.path.join(pkg, fn), encoding="utf-8").read()
        for token in ("C:\\Users", "/mnt/c/", "huawei"):
            if token in s:
                bad.append((fn, token))
    assert not bad, bad
