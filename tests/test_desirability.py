# -*- coding: utf-8 -*-
"""desirability / 几何平均 / Pareto 的逻辑分支测试（合成数据，25+ 断言）。

跑法: python tests/test_desirability.py
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from adt.desirability import (desirability, _geo, compound_scores,
                              pareto_front, can_rank_full, AXIS_COVERAGE_MIN)

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


R_UP = {"shape": "up", "pass": 60, "fail": 10, "axis": "exposure"}
R_DOWN = {"shape": "down", "pass": 2, "fail": 3, "axis": "exposure"}
R_WIN = {"shape": "window", "window": [-1, 3], "soft": [-2, 4], "axis": "exposure"}
R_STEP = {"shape": "step", "fail": 0.5, "axis": "safety"}
R_NONE = {"shape": "none", "axis": "coverage"}

print("== 1) 单端点 desirability ==")
check("up: fail=0", desirability(10, R_UP) == 0.0)
check("up: pass=1", desirability(60, R_UP) == 1.0)
check("up: 中点=0.5", abs(desirability(35, R_UP) - 0.5) < 1e-9)
check("up: 越上界截断", desirability(1000, R_UP) == 1.0)
check("up: 越下界截断", desirability(-5, R_UP) == 0.0)
check("down: fail=0", desirability(3, R_DOWN) == 0.0)
check("down: pass=1", desirability(2, R_DOWN) == 1.0)
check("down: 越低越好不超 1", desirability(0.1, R_DOWN) == 1.0)
check("window: 窗内=1", desirability(1.0, R_WIN) == 1.0)
check("window: soft 边=0", desirability(-2, R_WIN) == 0.0)
check("window: 左软区线性", abs(desirability(-1.5, R_WIN) - 0.5) < 1e-9)
check("window: 窗外右软区", 0 < desirability(3.5, R_WIN) < 1.0)
check("step: 过线=0", desirability(0.6, R_STEP) == 0.0)
check("step: 未过=1", desirability(0.3, R_STEP) == 1.0)
check("none: 不打分", desirability(5, R_NONE) is None)
check("value 缺失", desirability(None, R_UP) is None)

print("== 2) 几何平均的三个性质 ==")
check("空集=None", _geo([]) is None)
check("含 0 则整体=0（FAIL 必须拉低）", _geo([0.9, 0.0]) == 0.0)
check("非对称惩罚：geo(0.9,0.1)<geo(0.5,0.5)",
      _geo([0.9, 0.1]) < _geo([0.5, 0.5]))

print("== 3) compound_scores：UNDETERMINED 不进均值但占分母 ==")
RULES = {"dili": R_STEP, "herg": {"shape": "down", "pass": 0.1, "fail": 0.5, "axis": "safety"},
         "solubility_kinetic_ph74": R_UP}
# 分子 A：dili PASS(1.0) + herg PASS(1.0)，solubility UNDETERMINED
# 分子 B：dili FAIL(0.0) + herg PASS(1.0) + solubility 0.8 PASS
rows = [
    dict(compound_id="A", endpoint="dili", value_used=0.2, verdict="PASS"),
    dict(compound_id="A", endpoint="herg", value_used=0.05, verdict="PASS"),
    dict(compound_id="A", endpoint="solubility_kinetic_ph74", value_used="",
         verdict="UNDETERMINED"),
    dict(compound_id="B", endpoint="dili", value_used=0.9, verdict="FAIL"),
    dict(compound_id="B", endpoint="herg", value_used=0.05, verdict="PASS"),
    dict(compound_id="B", endpoint="solubility_kinetic_ph74", value_used=50,
         verdict="PASS"),
]
ep_rows, ax_rows = compound_scores(rows, RULES)
A = {r["axis"]: r for r in ax_rows if r["compound_id"] == "A"}
B = {r["axis"]: r for r in ax_rows if r["compound_id"] == "B"}
check("A.safety n_all=2", A["safety"]["n_endpoints"] == 2)
check("A.safety n_audited=2 (UNDETERMINED 只在 exposure)", A["safety"]["n_audited"] == 2)
check("A.safety geo=1.0", A["safety"]["geo_mean"] == 1.0)
check("A.exposure 全 UNDETERMINED -> no_audited_endpoints",
      A["exposure"]["flag"] == "no_audited_endpoints")
check("B.safety geo=0（FAIL 拉底）", B["safety"]["geo_mean"] == 0.0)
check("B.exposure geo≈0.8", abs(B["exposure"]["geo_mean"] - 0.8) < 0.02)

print("== 4) 轴覆盖率不足 -> insufficient_coverage ==")
RULES3 = dict(RULES)
RULES3["logd_74"] = R_WIN
rows2 = [dict(compound_id="C", endpoint="solubility_kinetic_ph74",
              value_used=80, verdict="PASS"),
         dict(compound_id="C", endpoint="logd_74", value_used="",
              verdict="UNDETERMINED")]
_, ax2 = compound_scores(rows2, RULES3)
c = [r for r in ax2 if r["compound_id"] == "C"][0]
check("C.exposure coverage=0.5", abs(c["coverage"] - 0.5) < 1e-9)
check("C.exposure flag=insufficient_coverage (cov<0.5 之外，恰好等于仍 ok)",
      c["flag"] == "ok" if c["coverage"] >= AXIS_COVERAGE_MIN else
      c["flag"] == "insufficient_coverage")

print("== 5) Pareto：支配 / 前沿 / 共同轴缺失 ==")
ax_p = [
    dict(compound_id="P", axis="safety", geo_mean="0.8", flag="ok"),
    dict(compound_id="P", axis="exposure", geo_mean="0.2", flag="ok"),
    dict(compound_id="Q", axis="safety", geo_mean="0.8", flag="ok"),
    dict(compound_id="Q", axis="exposure", geo_mean="0.9", flag="ok"),
    dict(compound_id="R", axis="safety", geo_mean="0.95", flag="ok"),
    # R 没有 exposure 轴（覆盖率不足），不能被 P/Q 支配
]
front, dom = pareto_front(ax_p, ["safety", "exposure"])
check("P 被 Q 支配（Q 两轴都不差且 exposure 严格更好）", "Q" in dom["P"])
check("Q 在前沿（R 缺共同轴）", "Q" in front)
check("R 在前沿（缺共同轴不可被支配）", "R" in front)

print("== 6) can_rank_full 四条件 ==")
ok, why = can_rank_full(50, 0.2, 0.2, 5, 250)
check("四条全过 -> ok", ok)
ok, why = can_rank_full(14, 0.2, 0.2, 5, 70)
check("候选 14 < 30 -> 拒绝", not ok and any("30" in w for w in why))
ok, why = can_rank_full(50, 0.5, 0.2, 5, 250)
check("最大簇 50% -> 拒绝", not ok and any("30%" in w for w in why))
ok, why = can_rank_full(50, 0.2, 0.2, 2, 100)
check("可判端点 2 < 3 -> 拒绝", not ok and any("< 3" in w for w in why))

print("== 7) 真实数据 smoke（试点 8 分子 × 多端点的 reliability 输出）==")
# C54（评估报告 P1-4）：原实现硬编码开发工作区的 out/reliability.csv，
# 装机副本没有该文件 -> 整个测试套件 FileNotFoundError 崩溃。
# 现改为读 skill 自带的 _pilot 产物，并做成"缺失则跳过"而不是崩溃。
import csv, io
_pilot = os.path.join(HERE, "_pilot", "reliability.csv")
if not os.path.exists(_pilot):
    print("  skip  _pilot/reliability.csv 不存在（跳过真实数据 smoke；逻辑断言已全部执行）")
else:
    rel = list(csv.DictReader(io.open(_pilot, encoding="utf-8-sig")))
    check("_pilot/reliability.csv 可读且行数 >= 90", len(rel) >= 90, "n=%d" % len(rel))
    check("含 PASSTHRU 行（v2.1 端点角色）",
          any(r["verdict"] == "PASSTHRU" for r in rel))
    ep_r, ax_r = compound_scores(rel, RULES)   # 只配 3 个规则，其余被跳过
    n_comp = len({r["compound_id"] for r in ax_r})
    n_axis = len({r["axis"] for r in ax_r})
    check("每分子每轴都有行（%d 分子 × %d 轴）" % (n_comp, n_axis),
          len({(r["compound_id"], r["axis"]) for r in ax_r}) == n_comp * n_axis)
    check("PASSTHRU 端点未进入轴聚合",
          all("chembl_" not in e for r in ax_r
              for e in (r["endpoints_audited"] or "").split(";") if e))

print()
print("passed %d / failed %d" % (PASS, len(FAIL)))
if FAIL:
    print("FAILED:", FAIL)
    sys.exit(1)
print("ALL OK")
