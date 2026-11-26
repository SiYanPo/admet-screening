# -*- coding: utf-8 -*-
"""深水区 2.2：BBB 双层机制——UNDETERMINED/PASSTHRU 强制指向 P-gp 评估。

核心不变量（呼应 BBB-Nuke 2026 的 transport-aware 立场）：
  T1 vnn_bbb（role=reference，本类域外 → PASSTHRU）未给确定裁决 → action 被强制改写为
     "P-gp 底物概率评估"，并打标 bbb_mechanism=dual_layer_activated
  T2 非 BBB 端点（如 hERG）即便 UNDETERMINED 也**不**被改写
  T3 已给确定裁决（PASS/FAIL）的 BBB 端点不被改写
  T4 经 reliab 管线端到端：vnn_bbb 行在 reliability.csv 里 action 字段即为 P-gp 评估
  T5 改写只动 action/mechanism，不动 verdict / confidence（双层机制不改变原裁决）
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from adt import bbb
from adt.reliability import evaluate

import yaml
RULES = yaml.safe_load(open(os.path.join(HERE, "references", "03_endpoint_rules.yaml"),
                            encoding="utf-8"))


def test_bbb_passthru_forced():
    rec = {"endpoint": "vnn_bbb", "verdict": "PASSTHRU", "action": "",
           "confidence": ""}
    bbb.apply_dual_layer(rec)
    assert rec["bbb_mechanism"] == "three_channel_resolution"
    assert "P-gp" in rec["action"] and "三通道" in rec["action"]
    # verdict / confidence 不被改写
    assert rec["verdict"] == "PASSTHRU"


def test_bbb_undetermined_forced():
    rec = {"endpoint": "vnn_bbb", "verdict": "UNDETERMINED", "action": "补实验"}
    bbb.apply_dual_layer(rec)
    assert rec["bbb_mechanism"] == "three_channel_resolution"
    assert "P-gp" in rec["action"]


def test_non_bbb_untouched():
    for ep in ("hERG", "mmp", "caco2_papp_ab"):
        rec = {"endpoint": ep, "verdict": "UNDETERMINED", "action": "补实验"}
        bbb.apply_dual_layer(rec)
        assert rec.get("bbb_mechanism") is None
        assert rec["action"] == "补实验"


def test_resolved_bbb_untouched():
    rec = {"endpoint": "vnn_bbb", "verdict": "PASS", "action": ""}
    bbb.apply_dual_layer(rec)
    assert rec.get("bbb_mechanism") is None
    assert rec["action"] == ""


def test_postprocess_list():
    recs = [
        {"endpoint": "vnn_bbb", "verdict": "PASSTHRU", "action": ""},
        {"endpoint": "hERG", "verdict": "UNDETERMINED", "action": "补实验"},
    ]
    out = bbb.postprocess(recs)
    assert out[0]["bbb_mechanism"] == "three_channel_resolution"
    assert out[1].get("bbb_mechanism") is None


def test_end_to_end_reliab():
    """端到端：vnn_bbb 域外行经 reliab 后 action 应为 P-gp 评估。"""
    rows = [dict(compound_id="X1", endpoint="vnn_bbb", value="", unit="class_0_1",
                 source="vnn", source_version="1.0", retrieved_at="2026",
                 domain_flag="out_of_domain", uncertainty="NA",
                 provenance_url="https://x", note="no predict")]
    recs = evaluate(rows, RULES, None, None, {})
    bb = [r for r in recs if r["endpoint"] == "vnn_bbb"]
    assert bb, "vnn_bbb 行应存在"
    assert "P-gp" in (bb[0].get("action") or ""), bb[0].get("action")


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
