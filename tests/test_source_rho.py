# -*- coding: utf-8 -*-
"""工作包 A：真实源间相关性 ρ。"""
import io
import os
import sys
sys.path.insert(0, ".")

from adt import source_rho as SR


def _write(d, name, cols, rows):
    p = os.path.join(d, name)
    with io.open(p, "w", encoding="utf-8", newline="") as fh:
        fh.write(",".join(cols) + "\n")
        for r in rows:
            fh.write(",".join(str(x) for x in r) + "\n")
    return p


def test_spearman_perfect_and_reversed():
    x = [1, 2, 3, 4, 5]
    assert abs(SR.spearman(x, x) - 1.0) < 1e-9
    assert abs(SR.spearman(x, [5, 4, 3, 2, 1]) + 1.0) < 1e-9


def test_spearman_handles_ties():
    x = [1, 1, 2, 2]
    y = [1, 1, 2, 2]
    r = SR.spearman(x, y)
    assert r is not None and r > 0.9


def test_compare_aligns_by_smiles_and_reports_ci(tmp_path):
    d = str(tmp_path)
    cols = ["smiles", "hERG", "DILI"]
    a = _write(d, "a.csv", cols, [
        ["CCO", 0.1, 0.9], ["CCC", 0.2, 0.8], ["CCN", 0.3, 0.7],
        ["CCCl", 0.4, 0.6], ["CCBr", 0.5, 0.5], ["CCI", 0.6, 0.4],
    ])
    b = _write(d, "b.csv", cols, [
        ["CCO", 0.15, 0.1], ["CCC", 0.25, 0.2], ["CCN", 0.35, 0.3],
        ["CCCl", 0.45, 0.4], ["CCBr", 0.55, 0.5], ["CCI", 0.65, 0.6],
    ])
    res = SR.compare(a, b)
    assert res["n_compounds"] == 6
    assert res["n_shared_endpoints"] == 2
    ep = {r["endpoint"]: r for r in res["rows"]}
    assert ep["hERG"]["spearman"] == 1.0            # 完全同向
    assert ep["DILI"]["spearman"] == -1.0           # 完全反向（符号冲突）
    assert ep["hERG"]["ci_lo"] is not None
    assert res["median_spearman"] is not None


def test_verdict_flags_redundancy_and_sign_conflict():
    hi = dict(median_spearman=0.9)
    assert "独立方法组" in SR.verdict(hi)
    lo = dict(median_spearman=0.1)
    assert "不同信息" in SR.verdict(lo)
    mid = dict(median_spearman=0.65)
    assert "部分冗余" in SR.verdict(mid)


def test_missing_values_are_skipped(tmp_path):
    d = str(tmp_path)
    cols = ["smiles", "hERG"]
    a = _write(d, "a.csv", cols, [["CCO", 0.1], ["CCC", "-"], ["CCN", 0.3], ["CCCl", 0.4]])
    b = _write(d, "b.csv", cols, [["CCO", 0.2], ["CCC", 0.5], ["CCN", 0.4], ["CCCl", 0.5]])
    res = SR.compare(a, b)
    assert res["rows"][0]["n_pairs"] == 3           # "-" 被跳过


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
