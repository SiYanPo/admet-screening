# -*- coding: utf-8 -*-
"""BBB 三通道决议：被动 × 外排 × 摄取。"""
import sys
sys.path.insert(0, ".")

from adt import bbb


def test_non_bbb_untouched():
    rec = {"endpoint": "hERG", "verdict": "UNDETERMINED", "action": "补实验"}
    bbb.apply_dual_layer(rec)
    assert rec["action"] == "补实验"
    assert "bbb_mechanism" not in rec


def test_passthru_triggers_three_channel():
    rec = {"endpoint": "vnn_bbb", "verdict": "PASSTHRU", "action": ""}
    bbb.apply_dual_layer(rec)
    assert rec["bbb_mechanism"] == "three_channel_resolution"
    assert "passive(closed_by_SAR)" in rec["bbb_channels"]
    assert "efflux(P-gp/BCRP)" in rec["bbb_channels"]
    # 摄取通道现已升级为有结构依据的启发式骨架（OATP1A2/LAT1/GLUT1；SGLT1/OATP2B1 为肠侧 Fa 通道不纳入）
    assert "uptake(OATP1A2/LAT1/GLUT1)" in rec["bbb_channels"]
    assert "启发式moiety骨架" in rec["bbb_channels"]


def test_action_covers_efflux_and_uptake():
    rec = {"endpoint": "vnn_bbb", "verdict": "UNDETERMINED", "action": "补实验"}
    bbb.apply_dual_layer(rec)
    a = rec["action"]
    assert "P-gp" in a and "BCRP" in a          # 外排通道
    assert "GLUT1" in a and "SGLT1" in a and "OATP2B1" in a  # 摄取通道
    # 生物学保真：不得夸大完整糖苷的 BBB 侧 GLUT1/SGLT1 摄取
    assert "只转运单糖" in a
    assert "无功能性表达" in a


def test_pass_verdict_not_rewritten():
    rec = {"endpoint": "vnn_bbb", "verdict": "PASS", "action": "x"}
    bbb.apply_dual_layer(rec)
    assert rec["action"] == "x"
    assert "bbb_mechanism" not in rec


def test_postprocess_batch():
    recs = [
        {"endpoint": "vnn_bbb", "verdict": "PASSTHRU", "action": ""},
        {"endpoint": "hERG", "verdict": "UNDETERMINED", "action": "补实验"},
    ]
    out = bbb.postprocess(recs)
    assert out[0]["bbb_mechanism"] == "three_channel_resolution"
    assert out[1]["action"] == "补实验"  # 非 BBB 不动


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
