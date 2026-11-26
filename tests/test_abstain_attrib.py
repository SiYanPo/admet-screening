# -*- coding: utf-8 -*-
"""模块N：UNDETERMINED 结构化弃权归因。"""
import sys
sys.path.insert(0, ".")

from adt import abstain_attrib as AA


def _rec(**kw):
    base = dict(compound_id="C1", endpoint="E", verdict="UNDETERMINED",
                confidence="low", reason="", n_total=3, n_in_domain=2,
                n_indep_groups=2, spread="", action="")
    base.update(kw)
    return base


def test_domain_block_when_no_in_domain():
    r = _rec(n_in_domain=0, reason="全部源域外/失效（flags=out_of_domain）")
    prim, sec = AA.attribute(r)
    assert prim == "domain_block", (prim, sec)


def test_unit_isomerism_detected():
    r = _rec(reason="跨源单位不一致（probability/class）且规则无 class_map")
    assert AA.attribute(r)[0] == "unit_isomerism"


def test_insufficient_independent_groups():
    r = _rec(reason="域内源 3 个但独立方法组仅 1 个 < 要求的 2")
    assert AA.attribute(r)[0] == "insufficient_independent_groups"


def test_spread_exceeded_both_from_text_and_field():
    r1 = _rec(reason="源间分歧过大（极差=0.42）")
    assert AA.attribute(r1)[0] == "spread_exceeded"
    r2 = _rec(reason="", spread="0.55")
    assert AA.attribute(r2)[0] == "spread_exceeded"


def test_priority_domain_beats_unit():
    r = _rec(n_in_domain=0, reason="全部源域外；跨源单位不一致")
    prim, sec = AA.attribute(r)
    assert prim == "domain_block"
    assert "unit_isomerism" in sec


def test_annotate_only_undetermined():
    recs = [_rec(reason="源间分歧过大"),
            dict(compound_id="C2", endpoint="E", verdict="PASS",
                 confidence="high", reason="")]
    AA.annotate(recs)
    assert recs[0]["abstention_reason_attribution"] == "spread_exceeded"
    assert recs[0]["abstention_resolution"]
    assert recs[1]["abstention_reason_attribution"] == ""


def test_distribution_and_write(tmp_path):
    recs = [_rec(n_in_domain=0, reason="全部源域外"),
            _rec(reason="源间分歧过大"),
            _rec(reason="源间分歧过大"),
            dict(compound_id="C9", endpoint="E", verdict="PASS", confidence="high")]
    AA.annotate(recs)
    d1 = AA.distribution(recs, by="primary")
    assert d1["n_undetermined"] == 3
    shares = {r["abstention_reason"]: r["n"] for r in d1["rows"]}
    assert shares["spread_exceeded"] == 2
    d2 = AA.distribution(recs, by="endpoint")
    p1, p2, p3 = AA.write(str(tmp_path), recs, d1, d2)
    assert p1.endswith("reliability_with_attribution.csv")
    assert (tmp_path / "abstention_attribution_distribution.csv").exists()


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
