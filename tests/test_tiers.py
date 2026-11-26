# -*- coding: utf-8 -*-
"""运行档位 + 项目级结论封顶测试（移植 E0/门控状态机的验收点）。

验收点：
  1) 无实测、无 2 独立组 -> T1；有 ≥1 个 2 独立组端点 -> T2；三件齐 -> T3
  2) enforce 拒绝越级（T3 vs T2），同级通过
  3) stats_from_reliability 正确计数

跑法: python tests/test_tiers.py
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from adt import tiers  # noqa: E402

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


print("== 1) 档位判定 ==")
t1, c1, _ = tiers.assign(dict(n_measured=0, n_judged_indep2=0))
check("无实测无独立组 -> T1", t1 == "T1", t1)
check("T1 上限 exploratory_only", c1 == "exploratory_only", c1)
t2, c2, _ = tiers.assign(dict(n_measured=0, n_judged_indep2=5))
check("有 2 独立组端点 -> T2", t2 == "T2", t2)
check("T2 上限 decision_support", c2 == "decision_support", c2)
t3, c3, miss = tiers.assign(dict(n_measured=3, n_judged_indep2=5),
                            has_benchmark=True, has_coverage_decl=True,
                            benchmark_ok=True)
check("实测+基准+覆盖 -> T3", t3 == "T3", t3)
check("T3 上限 publication", c3 == "publication", c3)
check("T3 无缺口", miss == [], str(miss))

print("== 2) enforce 越级拦截 ==")
ok, msg = tiers.enforce("T3", "T2")
check("请求 T3 但只支持 T2 -> 拒绝", ok is False and "越级" in msg, msg)
ok2, _ = tiers.enforce("T2", "T2")
check("请求 T2 且支持 T2 -> 允许", ok2 is True)
ok3, _ = tiers.enforce("T1", "T3")
check("请求 T1 且支持 T3（保守）-> 允许", ok3 is True)

print("== 3) 证据构成计数 ==")
recs = [
    dict(verdict="PASS", n_measured="0", n_indep_groups="2"),
    dict(verdict="PASS", n_measured="0", n_indep_groups="2"),
    dict(verdict="UNDETERMINED", n_measured="0", n_indep_groups="1"),
    dict(verdict="PASSTHRU", n_measured="0", n_indep_groups="0"),
    dict(verdict="FAIL", n_measured="1", n_indep_groups="2"),
]
st = tiers.stats_from_reliability(recs)
check("n_rows=5", st["n_rows"] == 5, str(st))
check("n_measured=1", st["n_measured"] == 1, str(st))
check("n_judged=3", st["n_judged"] == 3, str(st))
check("n_judged_indep2=3", st["n_judged_indep2"] == 3, str(st))

print()
print("passed %d / failed %d" % (PASS, len(FAIL)))
if FAIL:
    print("FAILED:", FAIL)
    sys.exit(1)
print("ALL OK")
