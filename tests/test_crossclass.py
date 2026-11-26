# -*- coding: utf-8 -*-
"""跨化学类裁决行为一致性：弃权率随可裁决性单调变化的预测检验。"""
import sys
sys.path.insert(0, ".")

import csv
import os

from adt import crossclass as XC


def _write_space(tmp_path, name, verdicts):
    p = os.path.join(str(tmp_path), name)
    with open(p, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["compound_id", "endpoint", "verdict", "confidence", "reason"])
        for i, v in enumerate(verdicts):
            w.writerow(["C%d" % i, "ep1", v, "high", ""])
    return p


def test_analyze_space_metrics(tmp_path):
    # 高极性糖苷类：全部 UNDETERMINED（域外源多 → 弃权率高）
    p_hi = _write_space(tmp_path, "glycosides.csv",
                        ["UNDETERMINED"] * 14)
    s = XC.analyze_space(p_hi, "glycosides")
    assert s["n_rows"] == 14
    assert abs(s["abstention_rate"] - 1.0) < 1e-9
    assert abs(s["decided_rate"] - 0.0) < 1e-9


def test_compare_spaces_monotone(tmp_path):
    # 糖苷类（高弃权）vs 药物样 OpenADMET（低弃权）：预期方向与实际一致
    p_hi = _write_space(tmp_path, "glycosides.csv", ["UNDETERMINED"] * 14)
    p_lo = _write_space(tmp_path, "openadmet.csv",
                        ["PASS"] * 60 + ["FAIL"] * 20 + ["UNDETERMINED"] * 20)
    spaces = [XC.analyze_space(p_hi, "glycosides"),
              XC.analyze_space(p_lo, "openadmet")]
    comp = XC.compare_spaces(spaces,
                             expected_highest_abstention="glycosides",
                             expected_lowest_abstention="openadmet")
    # 预测检验：高极性类弃权率显著高于药物样空间
    assert "符合预期" in comp["prediction_check"], comp["prediction_check"]
    assert comp["ordered_by_abstention"][0]["label"] == "glycosides"


def test_compare_spaces_reverse_warning(tmp_path):
    # 反向：预期高弃权的糖苷类实际弃权反而更低 → 结构性缺口告警
    p_hi = _write_space(tmp_path, "glycosides.csv",
                        ["PASS"] * 10 + ["FAIL"] * 4)      # 低弃权（实际）
    p_lo = _write_space(tmp_path, "openadmet.csv",
                        ["UNDETERMINED"] * 100)            # 高弃权（实际）
    spaces = [XC.analyze_space(p_hi, "glycosides"),
              XC.analyze_space(p_lo, "openadmet")]
    comp = XC.compare_spaces(spaces,
                             expected_highest_abstention="glycosides",
                             expected_lowest_abstention="openadmet")
    assert "反向" in comp["prediction_check"], comp["prediction_check"]


def test_compare_spaces_no_expected_falls_back(tmp_path):
    # 未声明预期方向时退化为裸排序报告（不误报反向）
    p_hi = _write_space(tmp_path, "glycosides.csv", ["UNDETERMINED"] * 14)
    p_lo = _write_space(tmp_path, "openadmet.csv",
                        ["PASS"] * 60 + ["FAIL"] * 20 + ["UNDETERMINED"] * 20)
    spaces = [XC.analyze_space(p_hi, "glycosides"),
              XC.analyze_space(p_lo, "openadmet")]
    comp = XC.compare_spaces(spaces)
    assert "符合预期" not in comp["prediction_check"]
    assert "反向" not in comp["prediction_check"]


def test_write_output(tmp_path):
    p = _write_space(tmp_path, "s.csv", ["UNDETERMINED"] * 5 + ["PASS"] * 5)
    s = XC.analyze_space(p, "s")
    op = os.path.join(str(tmp_path), "out.csv")
    XC.write(op, [s], XC.compare_spaces([s]))
    assert os.path.exists(op)


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
