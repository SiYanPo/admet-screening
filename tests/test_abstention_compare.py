# -*- coding: utf-8 -*-
"""模块M：结构性 vs 模型依赖弃权的跨端点一致性对比。"""
import sys
sys.path.insert(0, ".")

from adt import abstention_compare as AC

RULES = {"vnn_bbb": {"id": "vnn_bbb", "role": "quality", "threshold": 0.5,
                     "direction": "higher_is_worse", "require_sources": 2,
                     "phys_range": [0.0, 1.0]},
         "herg": {"id": "herg", "role": "quality", "threshold": 0.5,
                  "direction": "higher_is_worse", "require_sources": 2,
                  "phys_range": [0.0, 1.0]}}


def _recs(ep, n=20, err_every=5):
    out = []
    for i in range(n):
        fail = (i % 2 == 0)
        truth_fail = fail
        if i % err_every == 0:      # 周期性制造错误 → 让 AURC 有意义
            truth_fail = not fail
        out.append(dict(compound_id="C%d" % i, endpoint=ep,
                        verdict="FAIL" if fail else "PASS",
                        confidence="high" if i % 3 else "medium",
                        n_total=3, n_in_domain=3, n_indep_groups=2,
                        spread="0.10", reason="", action=""))
        out[-1]["_truth_fail"] = truth_fail
    return out


def _truth(recs):
    return [dict(compound_id=r["compound_id"], endpoint=r["endpoint"],
                 truth_class=("FAIL" if r["_truth_fail"] else "PASS"))
            for r in recs]


def test_compare_produces_spread_for_each_signal():
    recs = _recs("vnn_bbb") + _recs("herg")
    res = AC.compare_by_endpoint(recs, truth_rows=_truth(recs), rules=RULES,
                                 min_pairs=2)
    assert set(res["per_endpoint"]) == {"vnn_bbb", "herg"}
    for name in ("structural", "spread", "vote_confidence"):
        assert name in res["spread"], res["spread"]
    assert res["spread"]["structural"]["n_endpoints"] == 2


def test_insufficient_endpoints_excluded_from_spread():
    recs = _recs("vnn_bbb", n=20) + _recs("herg", n=3)
    res = AC.compare_by_endpoint(recs, truth_rows=_truth(recs), rules=RULES,
                                 min_pairs=10)
    # herg 只有 3 对 → insufficient，不参与离散度统计
    assert res["spread"]["structural"]["n_endpoints"] == 1
    assert res["per_endpoint"]["herg"]["methods"]["structural"]["status"] == "insufficient"


def test_prediction_check_is_explicit():
    recs = _recs("vnn_bbb") + _recs("herg")
    res = AC.compare_by_endpoint(recs, truth_rows=_truth(recs), rules=RULES,
                                 min_pairs=2)
    assert res["prediction_check"]
    assert ("支持预测" in res["prediction_check"]
            or "⚠" in res["prediction_check"]
            or "不可估" in res["prediction_check"])


def test_write_outputs(tmp_path):
    recs = _recs("vnn_bbb") + _recs("herg")
    res = AC.compare_by_endpoint(recs, truth_rows=_truth(recs), rules=RULES,
                                 min_pairs=2)
    p1, p2, p3 = AC.write(str(tmp_path), res)
    assert (tmp_path / "abstention_compare_by_endpoint.csv").exists()
    assert (tmp_path / "abstention_compare_spread.csv").exists()


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
