# -*- coding: utf-8 -*-
"""工作包 G：真前瞻裁决（PASS 组实测失败率）。"""
import io
import os
import sys
sys.path.insert(0, ".")

from adt import prospective as PR


def test_pass_failure_rate_counts_committed_errors():
    # 4 对真值：2 PASS 真、2 FAIL 真
    truth = {("C1", "E"): "PASS", ("C2", "E"): "FAIL",
             ("C3", "E"): "PASS", ("C4", "E"): "FAIL"}
    verdicts = {
        ("C1", "E"): ("PASS", 1.0),   # 对
        ("C2", "E"): ("PASS", 0.9),   # 错：判 PASS 实为 FAIL
        ("C3", "E"): ("UNDETERMINED", 0.0),
        ("C4", "E"): ("FAIL", 0.8),   # 对
    }
    s = PR.summarize(verdicts, truth, "t")["overall"]
    assert s["n_pairs"] == 4
    assert s["n_decided"] == 3
    assert s["coverage"] == 0.75
    assert s["pass_n"] == 2
    assert s["pass_failure_rate"] == 0.5      # 2 个 PASS 里 1 个实为 FAIL
    assert s["fail_n"] == 1
    assert s["fail_false_alarm_rate"] == 0.0


def test_fail_false_alarm_rate():
    truth = {("C1", "E"): "PASS", ("C2", "E"): "FAIL"}
    verdicts = {("C1", "E"): ("FAIL", 0.9), ("C2", "E"): ("FAIL", 0.9)}
    s = PR.summarize(verdicts, truth, "t")["overall"]
    assert s["fail_false_alarm_rate"] == 0.5
    assert s["pass_failure_rate"] is None     # 没有 PASS 裁决


def test_per_endpoint_rows_and_coverage_none():
    truth = {("C1", "A"): "PASS", ("C1", "B"): "FAIL"}
    verdicts = {("C1", "A"): ("PASS", 1.0)}
    res = PR.summarize(verdicts, truth, "t")
    eps = {r["endpoint"]: r for r in res["per_endpoint"]}
    assert eps["A"]["decided_accuracy"] == 1.0
    # B 端点没有任何裁决记录 → 不在 per_endpoint 里
    assert "B" not in eps


def test_load_truth_ignores_undetermined(tmp_path):
    p = os.path.join(str(tmp_path), "truth.csv")
    with io.open(p, "w", encoding="utf-8", newline="") as fh:
        fh.write("compound_id,endpoint,truth_class\n")
        fh.write("C1,E,PASS\nC2,E,FAIL\nC3,E,UNDETERMINED\n")
    t = PR.load_truth(p)
    assert len(t) == 2 and t[("C1", "E")] == "PASS"


def test_write_outputs(tmp_path):
    truth = {("C1", "E"): "PASS"}
    verdicts = {("C1", "E"): ("PASS", 1.0)}
    res = [("admission_layer", PR.summarize(verdicts, truth, "admission_layer"))]
    p1, p2, p3 = PR.write(str(tmp_path), res, dict(split_note="temporal"))
    assert (tmp_path / "prospective_summary.csv").exists()
    txt = (tmp_path / "prospective_note.md").read_text(encoding="utf-8")
    assert "PASS 组失败率" in txt


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
