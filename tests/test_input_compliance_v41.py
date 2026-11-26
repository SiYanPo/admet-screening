# -*- coding: utf-8 -*-
"""R26/R27/R28 回归测试：输入层硬化、PubChem 字段漂移、端点三级、合规档位、prereg 锚点。"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adt import pubchem as PB          # noqa: E402
from adt import compliance as C        # noqa: E402
from adt import endpoints as E         # noqa: E402
from adt import units as U             # noqa: E402
from adt import decision_value as D    # noqa: E402


def test_pubchem_field_drift_old_vs_new():
    """R27：新旧两种响应形态都必须取到**含立体**的 SMILES。"""
    stereo = "C[C@H](N)C(=O)O"
    # 新版（2026）：SMILES=绝对立体，ConnectivitySMILES=非立体
    new = {"SMILES": stereo, "ConnectivitySMILES": "CC(N)C(=O)O"}
    s1, f1, w1 = PB.pick_smiles(new)
    assert s1 == stereo and f1 == "SMILES", (s1, f1)
    # 旧版：IsomericSMILES
    old = {"IsomericSMILES": stereo, "CanonicalSMILES": "CC(N)C(=O)O"}
    s2, f2, _ = PB.pick_smiles(old)
    assert s2 == stereo and f2 == "IsomericSMILES"
    # 只有非立体字段时必须告警，不得静默
    only_conn = {"ConnectivitySMILES": "CC(N)C(=O)O"}
    s3, f3, w3 = PB.pick_smiles(only_conn)
    assert s3 and "立体信息已丢失" in w3, w3


def test_input_guard_blocks_missing_stereo():
    """C13：本应有立体的分子若缺立体，必须 fail（而不是静默放行）。"""
    v = PB.validate_entry("alanine", "CC(N)C(=O)O")
    assert v["status"] == "fail", v
    assert v["inchikey"], "仍需给出 InChIKey 供锚定"
    ok = PB.validate_entry("L-alanine", "C[C@H](N)C(=O)O", declared_stereo=True)
    assert ok["status"] == "ok", ok
    g = PB.pipeline_guard([{"name": "x", "smiles": "CC(N)C(=O)O"}])
    assert g["ok"] is False and g["blocked"]


def test_endpoint_tier_policy_demotes_dili_ames():
    """R21：DILI/Ames 默认降为 UNDETERMINED；显式接受后可保留。"""
    recs = [{"compound_id": "A", "endpoint": "dili", "verdict": "FAIL", "reason": ""},
            {"compound_id": "A", "endpoint": "herg", "verdict": "FAIL", "reason": ""}]
    out, log = E.apply_tier_policy([dict(r) for r in recs], False)
    assert len(log) == 1 and log[0]["endpoint"] == "dili"
    assert [r["verdict"] for r in out] == ["UNDETERMINED", "FAIL"]
    out2, log2 = E.apply_tier_policy([dict(r) for r in recs], True)
    assert not log2 and out2[0]["verdict"] == "FAIL"
    # v4.3：Ames 依 ICH M7(R2) §6 从 not_recommended 升为 qualitative_only。
    # 但"升档"自带可执行约束，不是放行——下面三条钉住它：
    assert E.endpoint_tier("AMES")[0] == "qualitative_only"
    assert E.endpoint_tier("hERG")[0] == "adjudicable"

    ames = [{"compound_id": "B", "endpoint": "ames", "verdict": "FAIL",
             "sources": "admet_ai;vnn", "expert_rule_layer": True}]
    out3, log3 = E.apply_tier_policy([dict(r) for r in ames], False)
    assert not log3 and out3[0]["verdict"] == "FAIL"
    assert out3[0]["qualitative"] is True

    one_src = [dict(ames[0], sources="admet_ai")]
    out4, log4 = E.apply_tier_policy(one_src, False)
    assert out4[0]["verdict"] == "UNDETERMINED"
    assert "requires_two_methods" in log4[0]["reason"]

    no_rules = [dict(ames[0], expert_rule_layer=False)]
    out5, log5 = E.apply_tier_policy(no_rules, False)
    assert out5[0]["verdict"] == "UNDETERMINED"
    assert "requires_expert_rules" in log5[0]["reason"]


def test_compliance_profiles_and_default_off():
    """R23/R24/R25：四档隔离 + GPL 源默认关闭 + 商用档摘除 NC 源。"""
    _, removed, _ = C.filter_sources("commercial",
                                     ["protox3", "admet_ai", "biotransformer"])
    assert "protox3" in removed and "biotransformer" in removed
    assert "admet_ai" not in removed
    try:
        C.enforce("protox3", "commercial")
        raise AssertionError("commercial 档必须拦截 CC-BY-NC 源")
    except C.ComplianceError:
        pass
    try:
        C.enforce("biotransformer", "academic-internal")
        raise AssertionError("BioTransformer 默认必须关闭")
    except C.ComplianceError:
        pass
    os.environ["ADT_ENABLE_BIOTRANSFORMER"] = "1"
    try:
        assert C.enforce("biotransformer", "academic-internal") is True
    finally:
        os.environ.pop("ADT_ENABLE_BIOTRANSFORMER", None)


def test_unit_conversion_and_semantic_refusal():
    """R22：可换算的真换算；class vs probability 明确拒绝（不得臆造）。"""
    a, b, st, _ = U.try_pair(1.0, "uM", 1000.0, "nM")
    assert st == "converted" and abs(a - b) < 1e-9
    a2, b2, st2, note2 = U.try_pair(1, "class", 0.9, "probability")
    assert st2 == "semantic" and a2 is None and b2 is None
    assert "C78" in note2
    # log ↔ 线性
    assert abs(U.convert(-6.0, "log10(M)", "M") - 1e-6) < 1e-12
    # Papp 的 log10(cm/s) 不是浓度，必须拒绝换算（不得臆造）
    assert U.convert(-6.0, "log10(cm/s)", "M") is None


def test_undetermined_subtypes_and_weak_reco():
    """R16/B3：四细分 + 弱推荐（不得冒充实裁决）。"""
    assert D.classify_undetermined("域内源 2 个但独立方法组仅 1 个") == \
        "undet_insufficient_votes"
    assert D.classify_undetermined("endpoint_not_recommended: xx") == "undet_low_validity"
    assert D.classify_undetermined("sample_size（n=3 < 20）") == "undet_power"
    assert D.classify_undetermined("跨源方向相反") == "undet_conflict"
    r = D.weak_recommendation("undet_conflict", [1, -1, -1])
    assert r["strength"] == "weak" and "不得写入裁决" in r["note"]
    r2 = D.weak_recommendation("undet_domain")
    assert r2["direction"] is None


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print("OK", fn.__name__)
    print("ALL PASS test_input_compliance_v41.py (%d)" % len(fns))
