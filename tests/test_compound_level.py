# -*- coding: utf-8 -*-
"""化合物级 bootstrap 输出的回归测试（防覆盖设计再退化为同义反复）。"""
import csv
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV = os.path.join(ROOT, "out_sensitivity", "compound_level.csv")
MD = os.path.join(ROOT, "references", "COMPOUND_LEVEL_VALIDATION.md")


def rows():
    with io.open(CSV, encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def test_csv_has_three_endpoints_with_bootstraps():
    r = rows()
    assert len(r) == 3
    for x in r:
        assert int(x["n_boot"]) > 0, x
        assert float(x["coverage"]) > 0, x


def test_admission_is_not_tautological_with_probability_matching():
    """按相似度 top-k 与 gate 等价（同义反复）；按概率 top-k 必须不同，否则对照无效。"""
    for x in rows():
        assert abs(float(x["admitted_auc"]) - float(x["sim_matched_auc"])) < 1e-9, x
        assert abs(float(x["admitted_auc"]) - float(x["matched_auc"])) > 0.01, x


def test_markdown_declares_scope_boundary():
    txt = io.open(MD, encoding="utf-8").read()
    assert "不是完整 S1→S4 决策效用" in txt


if __name__ == "__main__":
    for fn in (test_csv_has_three_endpoints_with_bootstraps,
               test_admission_is_not_tautological_with_probability_matching,
               test_markdown_declares_scope_boundary):
        fn()
        print("PASS", fn.__name__)
    print("ALL OK (3 tests)")
