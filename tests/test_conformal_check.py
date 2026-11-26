# -*- coding: utf-8 -*-
"""工作包 F 测试：conformal 宽度 vs UNDETERMINED 的一致性检查。

跑法: python tests/test_conformal_check.py
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from adt import conformal_check as CC  # noqa: E402
from adt import conformal as CP  # noqa: E402

PASS = 0
FAIL = []


def check(name, cond, detail=""):
    global PASS
    if cond:
        PASS += 1
        print("  ok  %s" % name)
    else:
        FAIL.append(name)
        print("FAIL  %s  %s" % (name, detail))


print("== 1) 宽度按 verdict 分组 ==")
conf = [
    dict(compound_id="A", endpoint="e", width="10", flag="ok"),
    dict(compound_id="B", endpoint="e", width="1.0", flag="ok"),
    dict(compound_id="C", endpoint="e", width="1.2", flag="ok"),
    dict(compound_id="D", endpoint="e", width="", flag="insufficient"),
    dict(compound_id="E", endpoint="e", width="2.0", flag="self_calibrated"),
]
rel = [
    dict(compound_id="A", endpoint="e", verdict="UNDETERMINED"),
    dict(compound_id="B", endpoint="e", verdict="PASS"),
    dict(compound_id="C", endpoint="e", verdict="FAIL"),
    dict(compound_id="D", endpoint="e", verdict="PASS"),
    dict(compound_id="E", endpoint="e", verdict="FAIL"),
]
per, s = CC.assess(conf, rel)
by = {r["verdict"]: r for r in per}
check("UNDET n=1", by["UNDETERMINED"]["n"] == 1, str(by["UNDETERMINED"]))
check("PASS n=1", by["PASS"]["n"] == 1, str(by["PASS"]))
check("UNDET 中位宽=10", by["UNDETERMINED"]["median_width"] == 10.0,
      str(by["UNDETERMINED"]))
check("可判中位宽=1.1", abs(by["PASS"]["median_width"] + by["FAIL"]["median_width"] - 2.2) < 1e-9,
      str(by))
check("跳过 insufficient/self_calibrated", s["n_skipped"] == 2, str(s))

print("== 2) AUC / 比值 / 结论 ==")
check("n_total=3", s["n_total"] == 3, str(s))
check("ratio=10/1.1≈9.09", abs(float(s["ratio"]) - 10 / 1.1) < 0.01, str(s))
check("AUC=1.0", abs(float(s["auc_width_vs_abstention"]) - 1.0) < 1e-9, str(s))
check("结论支持", "支持" in s["conclusion"], s["conclusion"])

print("== 3) 反向：UNDET 更窄 -> 不支持 ==")
conf2 = [
    dict(compound_id="A", endpoint="e", width="1", flag="ok"),
    dict(compound_id="B", endpoint="e", width="10", flag="ok"),
    dict(compound_id="C", endpoint="e", width="12", flag="ok"),
]
rel2 = [
    dict(compound_id="A", endpoint="e", verdict="UNDETERMINED"),
    dict(compound_id="B", endpoint="e", verdict="PASS"),
    dict(compound_id="C", endpoint="e", verdict="FAIL"),
]
_, s2 = CC.assess(conf2, rel2)
check("AUC=0.0", abs(float(s2["auc_width_vs_abstention"]) - 0.0) < 1e-9, str(s2))
check("结论反向", "反向" in s2["conclusion"], s2["conclusion"])

print("== 4) 样本不足 ==")
_, s3 = CC.assess([dict(compound_id="A", endpoint="e", width="10", flag="ok")],
                  [dict(compound_id="A", endpoint="e", verdict="UNDETERMINED")])
check("AUC 空", s3["auc_width_vs_abstention"] == "", str(s3))
check("结论样本不足", "样本不足" in s3["conclusion"], s3["conclusion"])

print("== 5) normalized conformal：宽度随 sigma 变化 ==")
pred = [
    dict(compound_id="A", endpoint="e", value="1.0", domain_flag="predicted"),
    dict(compound_id="B", endpoint="e", value="2.0", domain_flag="predicted"),
]
truth = [
    dict(compound_id="A", endpoint="e", truth_value="1.1"),
    dict(compound_id="B", endpoint="e", truth_value="2.2"),
]
rows, summ = CP.build(pred, truth, "e", alpha=0.5, min_n=2,
                      mode="normalized", scale_map={"A": 1.0, "B": 10.0})
by = {r["compound_id"]: r for r in rows}
check("mode=normalized", summ["mode"] == "normalized", str(summ))
check("B 的区间更宽", float(by["B"]["width"]) > float(by["A"]["width"]),
      "%s vs %s" % (by["A"]["width"], by["B"]["width"]))
check("A 宽=2q*1", abs(float(by["A"]["width"]) - 2 * 0.1) < 1e-6,
      str(by["A"]))
check("B 宽=2q*10", abs(float(by["B"]["width"]) - 2 * 0.1 * 10) < 1e-6,
      str(by["B"]))
