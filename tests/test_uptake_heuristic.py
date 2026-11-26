# -*- coding: utf-8 -*-
"""OATP1A2 / LAT1 / GLUT1 摄取启发式的单元测试 + bbb 集成（B2 闭环动作，2026-11-03）。

纪律（与 test_efflux_heuristic.py 一致）：所有命中都是**启发式、非实测、须实验验证、不得进计票**；
本测试只验证"结构代理按预期分级"，不验证任何药理学真值。
"""
import pytest


def _run(smiles):
    from adt import uptake_heuristic as uh
    return uh.oatp1a2_lat1_glut1_uptake_heuristic(smiles)


def test_module_exports():
    from adt import uptake_heuristic as uh
    assert callable(uh.oatp1a2_lat1_glut1_uptake_heuristic)
    assert callable(uh.summarize)


def test_invalid_smiles_graceful():
    r = _run("not_a_smiles!!!")
    assert r["available"] is False
    assert r["oatp1a2"]["plausibility"] == "unknown"
    assert r["oatp1a2"]["verdict"] == "unknown"
    assert r["lat1"]["verdict"] == "unknown"
    assert r["glut1"]["verdict"] == "unknown"


def test_glucose_free_is_glut1_plausible():
    """游离葡萄糖：GLUT1 候选（plausible_uptake），且无阴离子/氨基酸 → OATP/LAT uncertain。"""
    r = _run("OC1OC(CO)C(O)C(O)C1O")
    assert r["available"] is True
    assert r["glut1"]["plausibility"] == "medium"
    assert r["glut1"]["verdict"] == "plausible_uptake"
    assert r["oatp1a2"]["verdict"] == "uncertain"
    assert r["lat1"]["verdict"] == "uncertain"


def test_levodopa_lat1_medium_and_oatp_candidate():
    """L-DOPA：经典 LAT1 底物（medium），同时是 OATP1A2 候选（low_to_medium）。"""
    r = _run("N[C@@H](Cc1ccc(O)c(O)c1)C(=O)O")
    assert r["available"] is True
    assert r["lat1"]["plausibility"] == "medium"
    assert r["lat1"]["verdict"] == "plausible_uptake"
    assert r["oatp1a2"]["plausibility"] in ("low_to_medium", "medium")
    assert r["oatp1a2"]["verdict"] == "plausible_uptake"


def test_estrone_sulfate_oatp1a2_medium():
    """estrone-3-sulfate：OATP1A2 经典探针底物（medium）。"""
    r = _run("CC12CCC3C(=O)CCC4=C(OS(=O)(=O)[O-])C(O)CCC34C1CC(O)C2")
    assert r["available"] is True
    assert r["oatp1a2"]["plausibility"] == "medium"
    assert r["oatp1a2"]["verdict"] == "plausible_uptake"
    # 类固醇无 α-氨基酸骨架 → LAT1 不应判 medium
    assert r["lat1"]["plausibility"] != "medium"


def test_intact_glycoside_glut1_excluded():
    """完整糖苷（棉子糖）：含糖但 MW 偏大 → GLUT1 排除（完整糖苷非 GLUT1 底物）。"""
    r = _run("OC[C@H]1O[C@@H](O[C@H]2O[C@H](CO)[C@@H](O)[C@H](O)[C@H]2O)[C@H](O)[C@@H](O)[C@@H]1O")
    assert r["available"] is True
    assert r["glut1"]["verdict"] == "excluded_for_intact_glycoside"


def test_non_substrate_low():
    """戊烷：无任何转运体特征 → 全 low/uncertain。"""
    r = _run("CCCCC")
    assert r["available"] is True
    for ch in ("oatp1a2", "lat1", "glut1"):
        assert r[ch]["plausibility"] == "low"
        assert r[ch]["verdict"] in ("uncertain", "unknown")


def test_glycine_small_aa_downgraded():
    """甘氨酸（C2，唯一非 LAT1 底物的氨基酸）应被强制降级为 low/uncertain。"""
    r = _run("NCC(=O)O")
    assert r["available"] is True
    assert r["lat1"]["plausibility"] == "low"
    assert r["lat1"]["verdict"] == "uncertain"


def test_summarize_returns_string():
    from adt import uptake_heuristic as uh
    r = uh.oatp1a2_lat1_glut1_uptake_heuristic("OC1OC(CO)C(O)C(O)C1O")
    s = uh.summarize(r)
    assert isinstance(s, str) and len(s) > 0
    assert "非实测" in s


# ---------------- bbb 集成 ----------------
def test_bbb_apply_with_smiles_enriches_uptake_action():
    """BBB UNDETERMINED + SMILES → action 含摄取启发式命中段；既有不变量不变。"""
    import adt.bbb as bbb
    smiles = "N[C@@H](Cc1ccc(O)c(O)c1)C(=O)O"  # L-DOPA
    rec = {"endpoint": "vnn_bbb", "verdict": "UNDETERMINED", "action": "补实验", "smiles": smiles}
    bbb.apply_dual_layer(rec, smiles)   # 显式透传 SMILES
    assert rec["bbb_mechanism"] == "three_channel_resolution"
    assert "P-gp" in rec["action"] and "三通道" in rec["action"]
    assert rec.get("uptake_heuristic") is not None
    assert rec["uptake_heuristic"]["available"] is True
    assert "摄取启发式命中" in rec["action"]
    # verdict 不被改写
    assert rec["verdict"] == "UNDETERMINED"


def test_bbb_postprocess_passes_smiles_for_uptake():
    """postprocess 自动从 rec.smiles 透传 → 摄取启发式被运行（向后兼容：无 smiles 则纯叙事）。"""
    import adt.bbb as bbb
    recs = [
        {"endpoint": "vnn_bbb", "verdict": "PASSTHRU", "action": "",
         "smiles": "N[C@@H](Cc1ccc(O)c(O)c1)C(=O)O"},   # L-DOPA
        {"endpoint": "vnn_bbb", "verdict": "PASSTHRU", "action": ""},  # 无 smiles
    ]
    out = bbb.postprocess(recs)
    assert out[0]["uptake_heuristic"] is not None and out[0]["uptake_heuristic"]["available"] is True
    assert "摄取启发式命中" in out[0]["action"]
    assert out[1]["uptake_heuristic"] is None  # 无 smiles → 纯叙事，不变量不变
    assert "P-gp" in out[1]["action"]


def test_bbb_apply_without_smiles_no_uptake_heuristic():
    """无 SMILES → uptake_heuristic 为 None（向后兼容纯叙事，不变量不变）。"""
    import adt.bbb as bbb
    rec = {"endpoint": "vnn_bbb", "verdict": "PASSTHRU", "action": "补实验"}
    bbb.apply_dual_layer(rec)
    assert rec["bbb_mechanism"] == "three_channel_resolution"
    assert rec.get("uptake_heuristic") is None
    assert "摄取启发式命中" not in rec["action"]
