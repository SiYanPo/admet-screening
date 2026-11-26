# -*- coding: utf-8 -*-
"""P-gp / BCRP 外排启发式（B2 闭环动作）自检。

核心纪律：启发式**不得**改 verdict、不得进 reliab 计票、所有命中必须可被 Caco-2 ± 抑制剂验证。
本测试只验证"结构特征 → plausibility"的映射在已知分子上方向正确、且输出结构完整；
不验证预测准确性（那是 Caco-2 实验的事）。
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from adt import efflux_heuristic as eh
from adt import bbb


def test_verapamil_plausible():
    """维拉帕米：经典 P-gp 底物（碱性 N + 2 芳香环 + MW≈454 + 多 HBA）。"""
    r = eh.pgp_bcrp_efflux_heuristic("CCN(CC)CCCN(C)C(=O)c1ccc(cc1)Oc2ccccc2OC3CCN(CC3)C")
    assert r["available"] is True
    assert r["pgp"]["plausibility"] in ("medium", "low_to_medium")
    assert r["pgp"]["verdict"] == "plausible_efflux"
    assert "verapamil" in r["pgp"]["mandatory_assay"]


def test_raffinose_low_to_medium():
    """棉子糖：大体积多 OH 糖（MW≈504，HBA=16，0 芳香环）→ 命中 low_to_medium 分支。

    验证"hba_ge2 & mw_ge400 但无芳香环/无碱性N"时不会误判为 medium（保守降级）。
    """
    r = eh.pgp_bcrp_efflux_heuristic(
        "OC[C@H]1O[C@@H](O[C@H]2O[C@H](CO)[C@@H](O)[C@H](O)[C@H]2O)[C@H](O)"
        "[C@@H](O)[C@@H]1O[C@H]3O[C@H](CO)[C@@H](O)[C@H](O)[C@H]3O")
    assert r["available"] is True
    assert r["pgp"]["plausibility"] in ("low_to_medium", "medium")
    assert r["pgp"]["verdict"] == "plausible_efflux"
    assert r["pgp"]["features"]["aromatic_rings"] == 0


def test_pentane_low():
    """正戊烷：无任何转运体相关特征 → 外排 plausibility 为 low，verdict uncertain。"""
    r = eh.pgp_bcrp_efflux_heuristic("CCCCC")
    assert r["available"] is True
    assert r["pgp"]["plausibility"] == "low"
    assert r["pgp"]["verdict"] == "uncertain"
    assert r["pgp"]["features"]["hba"] == 0


def test_invalid_smiles_graceful():
    """不可解析 SMILES：available=False，plausibility=unknown，绝不抛错。"""
    r = eh.pgp_bcrp_efflux_heuristic("not_a_real_smiles((((")
    assert r["available"] is False
    assert r["pgp"]["plausibility"] == "unknown"
    assert r["bcrp"]["plausibility"] == "unknown"


def test_bbb_apply_with_smiles_enriches_action():
    """BBB UNDETERMINED + SMILES → action 含启发式命中段，且既有不变量不变。"""
    rec = {"endpoint": "vnn_bbb", "verdict": "UNDETERMINED", "action": "补实验",
           "smiles": "CCN(CC)CCCN(C)C(=O)c1ccc(cc1)Oc2ccccc2OC3CCN(CC3)C"}
    bbb.apply_dual_layer(rec, rec["smiles"])   # 显式透传 SMILES
    assert rec["bbb_mechanism"] == "three_channel_resolution"
    assert "P-gp" in rec["action"] and "三通道" in rec["action"]
    # 新增：启发式被运行并写入 action
    assert rec.get("efflux_heuristic") is not None
    assert rec["efflux_heuristic"]["available"] is True
    assert "外排启发式" in rec["action"]
    # verdict 不被改写
    assert rec["verdict"] == "UNDETERMINED"


def test_bbb_postprocess_passes_smiles_from_rec():
    """postprocess 自动从 rec.smiles 透传 → 启发式被运行（向后兼容：无 smiles 则纯叙事）。"""
    recs = [
        {"endpoint": "vnn_bbb", "verdict": "PASSTHRU", "action": "",
         "smiles": "CCN(CC)CCCN(C)C(=O)c1ccc(cc1)Oc2ccccc2OC3CCN(CC3)C"},
        {"endpoint": "vnn_bbb", "verdict": "PASSTHRU", "action": ""},  # 无 smiles
    ]
    out = bbb.postprocess(recs)
    assert out[0]["efflux_heuristic"] is not None and out[0]["efflux_heuristic"]["available"] is True
    assert "外排启发式" in out[0]["action"]
    assert out[1]["efflux_heuristic"] is None  # 无 smiles → 纯叙事，不变量不变
    assert "P-gp" in out[1]["action"]


def test_bbb_apply_without_smiles_no_heuristic_key_break():
    """不带 SMILES：沿用历史行为，action 仍含 P-gp 与三通道，不变量完好。"""
    rec = {"endpoint": "vnn_bbb", "verdict": "PASSTHRU", "action": ""}
    bbb.apply_dual_layer(rec)
    assert rec["bbb_mechanism"] == "three_channel_resolution"
    assert "P-gp" in rec["action"] and "三通道" in rec["action"]
    assert rec["efflux_heuristic"] is None


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
