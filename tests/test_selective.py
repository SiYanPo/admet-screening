# -*- coding: utf-8 -*-
"""工作包 H 测试：选择性预测的 risk–coverage。

跑法: python tests/test_selective.py
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from adt import selective as S  # noqa: E402

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


print("== 1) risk_coverage 解析解 ==")
pts, aurc = S.risk_coverage([(0.9, True), (0.8, True), (0.1, False)])
check("3 个点", len(pts) == 3, str(pts))
check("coverage 1/3 时 risk=0", abs(pts[0]["risk"] - 0.0) < 1e-9, str(pts[0]))
check("coverage 1 时 risk=1/3", abs(pts[-1]["risk"] - 1 / 3.0) < 1e-3, str(pts[-1]))
check("AURC=1/9≈0.111（阶梯积分）", abs(aurc - 1 / 9.0) < 1e-3, str(aurc))

print("== 2) 完美排序 AURC=0 ==")
_, a0 = S.risk_coverage([(0.9, True), (0.8, True), (0.7, True)])
check("AURC=0", abs(a0 - 0.0) < 1e-9, str(a0))
_, a1 = S.risk_coverage([(0.9, False), (0.8, False), (0.7, False)])
check("全错 AURC=1.0", abs(a1 - 1.0) < 1e-3, str(a1))

print("== 3) structural_score ==")
check("UNDETERMINED=0",
      S.structural_score(dict(verdict="UNDETERMINED")) == 0.0)
check("PASS high=1",
      S.structural_score(dict(verdict="PASS", confidence="high")) == 1.0)
check("PASS medium=0.7",
      S.structural_score(dict(verdict="PASS", confidence="medium")) == 0.7)
check("PASS low=0.45",
      S.structural_score(dict(verdict="PASS", confidence="low")) == 0.45)
check("伪共识降为 0.35",
      S.structural_score(dict(verdict="PASS", confidence="medium",
                              pseudo_consensus="Y")) == 0.35)

print("== 4) spread_score 单调 ==")
check("spread 0 -> 1", S.spread_score(dict(spread="0")) == 1.0)
check("spread 0.5 -> 0", S.spread_score(dict(spread="0.5")) == 0.0)

print("== 5) 多数票标签（含端点别名） ==")
meas = [
    dict(compound_id="X", endpoint="DILI", value="0.9", unit="probability",
         domain_flag="predicted", source="s1"),
    dict(compound_id="X", endpoint="DILI", value="0.8", unit="probability",
         domain_flag="predicted", source="s2"),
    dict(compound_id="Y", endpoint="DILI", value="0.1", unit="probability",
         domain_flag="predicted", source="s1"),
    dict(compound_id="Y", endpoint="DILI", value="0.2", unit="probability",
         domain_flag="predicted", source="s2"),
]
rules = {"dili": {"shape": "down", "pass": 0.5, "fail": 0.5}}
m = S._majority_map(meas, rules)
check("DILI 大写能匹配到规则", ("X", "DILI") in m, str(m))
check("X 多数 FAIL -> 1", m.get(("X", "DILI")) == 1, str(m))
check("Y 多数 PASS -> 0", m.get(("Y", "DILI")) == 0, str(m))

print("== 6) 无标签不臆造 ==")
res = S.evaluate([], None, None, None, proxy="none")
check("返回 error", bool(res.get("error")), str(res))

print("== 7) conformal 宽度基线 ==")
check("无区间=0", S.conformal_width_score(
    {"compound_id": "X", "endpoint": "e"}, {}) == 0.0)
check("宽 0 -> 1", abs(S.conformal_width_score(
    {"compound_id": "X", "endpoint": "e"}, {("X", "e"): "0"}) - 1.0) < 1e-9)
check("宽 1 -> 0.5", abs(S.conformal_width_score(
    {"compound_id": "X", "endpoint": "e"}, {("X", "e"): "1"}) - 0.5) < 1e-9)

print()
if FAIL:
    print("FAILED: %d 条 -> %s" % (len(FAIL), FAIL))
    sys.exit(1)
print("ALL PASS (%d assertions)" % PASS)
