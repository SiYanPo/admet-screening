# -*- coding: utf-8 -*-
"""s5 可靠性裁决的单元测试（**注意：这里的数据是合成的**，只用于验证逻辑分支）。

真实数据跑出来的结果见 out/reliability.csv —— 那是 14 个分子 × 3 端点 × 4 源，
全部 UNDETERMINED（源间分歧或灰区），这不是 bug，是那个化学类的真实状况。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from adt import schema, reliability as R  # noqa: E402

RULES = {
    "herg": {"shape": "down", "pass": 0.1, "fail": 0.5, "require_sources": 2},
    "ames": {"shape": "step", "fail": 0.5, "require_sources": 2},
    "solubility": {"shape": "up", "pass": 60, "fail": 10},
}
EPS = [[], set(), None]


def m(cid, ep, val, src, flag="predicted", unit="probability"):
    return schema.measurement(cid, ep, val, unit, src, "test", flag)


def one(rows, ep="herg", non_ranking=None):
    recs = R.evaluate(rows, RULES, non_ranking or set())
    hit = [r for r in recs if r["endpoint"] == ep]
    assert len(hit) == 1, hit
    return hit[0]


passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("  PASS  %s" % name)
    else:
        failed += 1
        print("  FAIL  %s  %s" % (name, detail))


print("=== 1) 有实测值优先 ===")
r = one([m("X", "herg", 0.02, "s1"), m("X", "herg", 0.45, "s2"),
         m("X", "herg", 0.03, "lab", flag="measured")])
check("verdict=PASS（实测 0.02 <= 0.1）", r["verdict"] == "PASS", r)
check("confidence=high", r["confidence"] == "high", r["confidence"])
check("n_measured=1", r["n_measured"] == 1, r["n_measured"])

print("=== 2) 全部域外 ===")
r = one([m("X", "herg", "", "s1", flag="out_of_domain"),
         m("X", "herg", "", "s2", flag="out_of_domain")])
check("verdict=UNDETERMINED", r["verdict"] == "UNDETERMINED", r)
check("有 action", bool(r["action"]), r["action"])

print("=== 3) 源间分歧 ===")
r = one([m("X", "herg", 0.02, "s1"), m("X", "herg", 0.45, "s2")])
check("verdict=UNDETERMINED", r["verdict"] == "UNDETERMINED", r)
check("reason 含'分歧'", "分歧" in r["reason"], r["reason"])
check("无 value_used（不取平均）", r["value_used"] == "", r["value_used"])

print("=== 4) 单源且要求 >=2 源 ===")
r = one([m("X", "herg", 0.03, "s1")])
check("verdict=UNDETERMINED", r["verdict"] == "UNDETERMINED", r)
check("reason 提到域内源数", "独立方法组" in r["reason"], r["reason"])

print("=== 5) 两源一致且通过阈值 ===")
r = one([m("X", "herg", 0.02, "s1"), m("X", "herg", 0.04, "s2")])
check("verdict=PASS", r["verdict"] == "PASS", r)
check("value_used 是中位数 0.03", abs(float(r["value_used"]) - 0.03) < 1e-9, r["value_used"])

print("=== 6) 两源一致且超阈值 ===")
r = one([m("X", "herg", 0.80, "s1"), m("X", "herg", 0.90, "s2")])
check("verdict=FAIL", r["verdict"] == "FAIL", r)

print("=== 7) 灰区（0.1-0.5）必须有 action ===")
r = one([m("X", "herg", 0.20, "s1"), m("X", "herg", 0.22, "s2")])
check("verdict=UNDETERMINED", r["verdict"] == "UNDETERMINED", r)
check("action 提到关注带", "关注带" in r["action"], r["action"])

print("=== 8) 集合内无区分度 -> 阈值仍判，但 confidence=low ===")
r = one([m("X", "herg", 0.02, "s1"), m("X", "herg", 0.03, "s2")], non_ranking={"herg"})
check("verdict=PASS（阈值仍有效）", r["verdict"] == "PASS", r)
check("confidence=low", r["confidence"] == "low", r["confidence"])
check("reason 写明不能排序", "不能排序" in r["reason"], r["reason"])

print("=== 9) 步阶规则 ames ===")
r = one([m("X", "ames", 0.80, "s1"), m("X", "ames", 0.85, "s2")], ep="ames")
check("verdict=FAIL（>0.5）", r["verdict"] == "FAIL", r)
r = one([m("X", "ames", 0.05, "s1"), m("X", "ames", 0.06, "s2")], ep="ames")
check("verdict=PASS", r["verdict"] == "PASS", r)

print("=== 10) 连续型端点（溶解度）走相对极差 ===")
r = one([m("X", "solubility", 50, "s1", unit="ug/mL"),
         m("X", "solubility", 55, "s2", unit="ug/mL")], ep="solubility")
check("spread 是相对量(<1)", float(r["spread"]) < 1, r["spread"])
check("verdict=UNDETERMINED（50-55 落在 10..60 之间）", r["verdict"] == "UNDETERMINED", r)

print("=== 11) 排名三条件 ===")
ok, why = R.can_rank(14, 0.86, 0.3)
check("14 个 / 86% 同类簇 -> 禁止排名", not ok and len(why) >= 2, why)
ok, why = R.can_rank(60, 0.10, 0.05)
check("60 个 / 10% / 分歧小 -> 允许", ok, why)

print("=== 12) 不变量：任何 UNDETERMINED 都必须有 action ===")
rows = []
for i in range(6):
    rows.append(m("Y%d" % i, "herg", 0.02 + 0.09 * i, "s1"))
    rows.append(m("Y%d" % i, "herg", 0.03 + 0.02 * i, "s2"))
recs = R.evaluate(rows, RULES, {"herg"})
bad = [r for r in recs if r["verdict"] == "UNDETERMINED" and not r["action"]]
check("所有 UNDETERMINED 都带 action", not bad, bad)

print("\n结果：%d passed, %d failed" % (passed, failed))
sys.exit(1 if failed else 0)
