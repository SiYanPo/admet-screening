# -*- coding: utf-8 -*-
"""E3 阈值敏感性分析的逻辑测试（合成数据，不触网）。

验收点：
  1) 贴近阈值的结论在摄动后确实被识别为翻转（PASS -> 灰区/UNDETERMINED）
  2) 翻转率分档正确（robust / fragile / threshold_critical）
  3) 非质量端点（role=reference/applicability）不进入摄动范围
  4) global 模式与 per_endpoint 模式都产出，且 global 行 endpoint="(all)"

跑法: python tests/test_sensitivity.py
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from adt import schema                                    # noqa: E402
from adt.sensitivity import analyze                       # noqa: E402

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


def m(cid, ep, v, src, flag="predicted", unit="probability"):
    return schema.measurement(cid, ep, v, unit, src, "test", flag)


RULES = {
    "herg": {"shape": "down", "pass": 0.1, "fail": 0.5, "axis": "safety",
             "require_sources": 1},
    "dili": {"shape": "step", "fail": 0.5, "axis": "safety", "require_sources": 1},
    "chembl_herg_p50": {"role": "reference"},
}

# C1 贴阈值（0.085 → PASS）；C2 灰区（0.46）；C3 dili 明确 PASS；C4 dili 明确 FAIL
ROWS = [m("C1", "herg", 0.08, "s1"), m("C1", "herg", 0.09, "s2"),
        m("C2", "herg", 0.45, "s1"), m("C2", "herg", 0.47, "s2"),
        m("C3", "dili", 0.2, "s1"), m("C3", "dili", 0.25, "s2"),
        m("C4", "dili", 0.9, "s1"), m("C4", "dili", 0.95, "s2"),
        m("C1", "chembl_herg_p50", 0.3, "chembl")]

print("== 1) 基线：C1 herg PASS / C3 dili PASS / C4 dili FAIL ==")
rows, summ = analyze(ROWS, RULES, factors=(0.5,))
check("产出 global 行", any(r["mode"] == "global" and r["endpoint"] == "(all)"
                            for r in rows))
check("per_endpoint 只含质量端点",
      {r["endpoint"] for r in rows if r["mode"] == "per_endpoint"} == {"herg", "dili"},
      str({r["endpoint"] for r in rows if r["mode"] == "per_endpoint"}))

print("== 2) 贴阈值端点在 pass 下调 50% 后必须翻转 ==")
h = [r for r in rows if r["endpoint"] == "herg" and r["direction"] == "lower"
     and r["mode"] == "per_endpoint"][0]
check("herg 有翻转", int(h["n_flipped"]) >= 1, str(h))
check("herg 判 threshold_critical（翻转率 1.0 > 0.5）",
      h["flag"] == "threshold_critical", h["flag"])
check("examples 指出被翻的分子", "C1" in h["examples"], h["examples"])

print("== 3) 远离阈值的端点应 robust ==")
d = [r for r in rows if r["endpoint"] == "dili" and r["mode"] == "per_endpoint"
     and r["direction"] == "lower"][0]
check("dili lower 0.5 无翻转 -> robust", d["flag"] == "robust", str(d))
check("dili 有 2 个可判端点", int(d["n_decided_base"]) == 2, str(d))

print("== 4) summary：最敏感端点排序与全局翻转率 ==")
check("worst_endpoints 首位是 herg", summ["worst_endpoints"][0][0] == "herg",
      str(summ["worst_endpoints"]))
check("max_global_flip 有值", summ["max_global_flip"] is not None,
      str(summ["max_global_flip"]))

print("== 5) 无判定的端点标 no_decided，不伪装成 robust ==")
rows2, _ = analyze([m("C9", "herg", "", "s1", flag="out_of_domain")],
                   RULES, factors=(0.2,))
nd = [r for r in rows2 if r["endpoint"] == "herg" and r["mode"] == "per_endpoint"][0]
check("flag=no_decided", nd["flag"] == "no_decided", str(nd))

print()
print("passed %d / failed %d" % (PASS, len(FAIL)))
if FAIL:
    print("FAILED:", FAIL)
    sys.exit(1)
print("ALL OK")
