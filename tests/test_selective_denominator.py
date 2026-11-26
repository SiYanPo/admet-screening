# -*- coding: utf-8 -*-
"""C06 / B1 回归：AURC 分母不变性 + 弃权率必须进入 AURC。

判据（报告 §4 B1、§5.1 复审、D02 的可裁决判定式）：
    构造两个「已判定样本质量完全相同、仅弃权率不同」的策略，
    若 AURC 相同 → 分母仍被偷偷删掉，测试必须 FAIL。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from adt import selective as SEL  # noqa: E402


def _decided(n=8, n_wrong=2):
    """8 条已判定样本，2 条错；score 递减。"""
    out = []
    for i in range(n):
        out.append((float(n - i), not (i < n_wrong)))
    return out


def test_build_pairs_keeps_undetermined():
    recs = [
        dict(compound_id="c1", endpoint="e", verdict="PASS"),
        dict(compound_id="c2", endpoint="e", verdict="FAIL"),
        dict(compound_id="c3", endpoint="e", verdict="UNDETERMINED"),
        dict(compound_id="c4", endpoint="e", verdict="UNDETERMINED"),
        dict(compound_id="c5", endpoint="e", verdict="PASS"),  # 无真值
    ]
    label = {("c1", "e"): 0, ("c2", "e"): 1}
    pairs = SEL.build_pairs(recs, label)
    assert len(pairs) == len(recs), "分母不变性被破坏：UNDETERMINED 又被删除了"
    assert sum(1 for _r, ok in pairs if ok is None) == 3


def test_aurc_changes_with_abstention_rate():
    decided = _decided()
    low_ab = [(-999.0, None)] * 2 + decided       # 10 条，弃权率 0.2
    high_ab = [(-999.0, None)] * 8 + decided      # 16 条，弃权率 0.5
    _, aurc_low = SEL.risk_coverage(low_ab, total_n=len(low_ab))
    _, aurc_high = SEL.risk_coverage(high_ab, total_n=len(high_ab))
    assert aurc_low is not None and aurc_high is not None
    assert abs(aurc_low - aurc_high) > 1e-4, (
        "弃权率不同但 AURC 相同 → 弃权仍与 AURC 解耦（C06 未修）")
    assert aurc_high > aurc_low, "弃权越多，含代价 AURC 应越大"


def test_coverage_curve_does_not_always_reach_one_from_decided_only():
    """旧 bug 的直接回归：弃权样本的代价必须进入终局 risk / AURC。"""
    decided = _decided()                      # 8 条，2 错 → 旧口径 risk=0.25
    pairs = [(-999.0, None)] * 12 + decided  # 20 条，12 弃权
    pts, aurc = SEL.risk_coverage(pairs, total_n=len(pairs))
    assert pts[-1]["coverage"] == 1.0
    # 12 * c_abstain + 2 错 = 14 / 20 = 0.7，远大于旧口径 0.25
    assert pts[-1]["risk"] > 0.25, "弃权代价未进入 risk（C06 未修）"
    assert aurc > 0.25, "弃权代价未进入 AURC"


def test_full_abstain_baseline_same_coordinate_system():
    pairs = _decided() + [(-999.0, None)] * 4
    base = SEL.full_abstain_baseline(pairs, c_abstain=1.0, total_n=len(pairs))
    assert base["coordinate_system"] == "all_records_inclusive"
    assert base["risk"] == 1.0


def test_proxy_majority_marked_non_evidence():
    """无实测真值时 --proxy majority 必须标 non_evidence，不参与 sd 比较。"""
    recs = [dict(compound_id="c%d" % i, endpoint="e",
                 verdict="PASS" if i % 2 else "FAIL") for i in range(12)]
    meas = [dict(compound_id="c%d" % i, endpoint="e", value="0.2")
            for i in range(12)]
    res = SEL.evaluate(recs, measurements=meas, rules={}, proxy="majority")
    if res.get("methods"):
        assert res["evidence_grade"] == "non_evidence"
        assert res["comparable_for_prediction_check"] is False
        assert "循环" in res.get("circularity_note", "")
    else:
        # 若伪标签构造因规则为空而失败，至少不得伪装成实测真值
        assert res.get("label_source") != "measured_truth"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print("PASS", fn.__name__)
        except AssertionError as exc:
            failed += 1
            print("FAIL", fn.__name__, exc)
    print("total=%d failed=%d" % (len(fns), failed))
    sys.exit(1 if failed else 0)
