# -*- coding: utf-8 -*-
"""方向A：准入层消融——四条件策略与指标。"""
import sys
sys.path.insert(0, ".")

from adt import ablation as AB


def _row(cid, ep, val, unit, src, group, dom="predicted"):
    return dict(compound_id=cid, endpoint=ep, value=val, unit=unit,
                source=src, _group=group, domain_flag=dom,
                source_version="v1")


def test_naive_includes_nonprojectable_unit():
    # (a) 忽略单位：uM=5.0 被当成 0/1 投票（naive）；(b) 单位守卫把它剔掉
    rows = [_row("C1", "E", 0.2, "risk_score", "s1", "g1"),
            _row("C1", "E", 5.0, "uM", "s2", "g2")]
    a = AB.policy_all_sources(rows)
    b = AB.policy_unit_guard(rows)
    # naive 下两源 0 vs 1 → 平票 → UNDETERMINED
    assert a[("C1", "E")][0] == "UNDETERMINED", a
    # 单位守卫只剩 s1=0.2 → PASS
    assert b[("C1", "E")][0] == "PASS", b


def test_admission_requires_two_independent_groups():
    one = [_row("C1", "E", 0.9, "risk_score", "s1", "g1"),
           _row("C1", "E", 0.9, "risk_score", "s1b", "g1")]  # 同组镜像
    assert AB.policy_admission(one)[("C1", "E")][0] == "UNDETERMINED"
    two = one + [_row("C1", "E", 0.9, "risk_score", "s2", "g2")]
    assert AB.policy_admission(two)[("C1", "E")][0] == "FAIL"


def test_admission_spread_guard_abstains():
    rows = [_row("C1", "E", 0.9, "risk_score", "s1", "g1"),
            _row("C1", "E", 0.9, "risk_score", "s2", "g2"),
            _row("C1", "E", 0.1, "risk_score", "s3", "g3")]
    # 2 票 FAIL vs 1 票 PASS，但极差 0.8 > 0.30 → 弃权
    assert AB.policy_admission(rows)[("C1", "E")][0] == "UNDETERMINED"


def test_admission_drops_out_of_domain():
    rows = [_row("C1", "E", 0.9, "risk_score", "s1", "g1", dom="out_of_domain"),
            _row("C1", "E", 0.9, "risk_score", "s2", "g2", dom="out_of_domain")]
    assert AB.policy_admission(rows)[("C1", "E")][0] == "UNDETERMINED"


def test_evaluate_and_matched_coverage():
    truth = {("C1", "E"): "FAIL", ("C2", "E"): "PASS"}
    verdicts = {("C1", "E"): ("FAIL", 1.0), ("C2", "E"): ("PASS", 0.4)}
    ev = AB.evaluate(verdicts, truth)
    assert ev["overall"]["decided_accuracy"] == 1.0
    assert ev["overall"]["coverage"] == 1.0
    m = AB.matched_coverage(verdicts, truth, 1)
    assert m["n"] == 1 and m["accuracy"] == 1.0


def test_corrupt_modes():
    rows = [_row("C1", "E", 0.9, "risk_score", "s1", "g1") for _ in range(20)]
    assert all(r["domain_flag"] == "out_of_domain"
               for r in AB.corrupt(rows, "domain", frac=1.0))
    assert len(AB.corrupt(rows, "pseudo")) == 40
    assert any(r["source_version"] == "v0-legacy"
               for r in AB.corrupt(rows, "version", frac=1.0))


def test_run_writes_outputs(tmp_path):
    rows = [_row("C1", "E", 0.9, "risk_score", "s1", "g1"),
            _row("C1", "E", 0.9, "risk_score", "s2", "g2"),
            _row("C2", "E", 0.1, "risk_score", "s1", "g1"),
            _row("C2", "E", 0.1, "risk_score", "s2", "g2")]
    truth = {("C1", "E"): "FAIL", ("C2", "E"): "PASS"}
    res = AB.run(rows, truth, dict(panel="unit", panel_mix="s1; s2"),
                 outdir=str(tmp_path))
    assert res["conformal_status"].startswith("skipped")
    assert (tmp_path / "ablation_summary.csv").exists()
    assert (tmp_path / "ablation_matched_coverage.csv").exists()


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
