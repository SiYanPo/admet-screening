# -*- coding: utf-8 -*-
"""工作包 I 测试：GRADE 式确定性修饰符。

跑法: python tests/test_certainty.py
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from adt import certainty as C  # noqa: E402

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


def rec(verdict, conf="low", n_dom=2, n_indep=2, reason="", spread="0.1",
        n_total=3):
    return dict(compound_id="X", endpoint="e", verdict=verdict,
                confidence=conf, n_in_domain=n_dom, n_indep_groups=n_indep,
                reason=reason, spread=spread, n_total=n_total,
                action="补源")


print("== 1) PASS + high -> high ==")
m, why = C.classify(rec("PASS", "high", 3, 3, "有实测值（n=1）"))
check("high", m == "high", m)
check("rationale 含 GRADE 维度", "indirectness=" in why, why)

print("== 2) UNDETERMINED 全部域外 -> low_unresolvable ==")
m2, why2 = C.classify(rec("UNDETERMINED", n_dom=0, n_indep=0,
                          reason="全部源域外/失效（flags=out_of_domain）"))
check("low_unresolvable", m2 == "low_unresolvable", m2)

print("== 3) 单位异构 -> low_resolvable ==")
m3, _ = C.classify(rec("UNDETERMINED", n_dom=3, n_indep=2,
                       reason="跨源单位不一致（class/probability）且规则无 class_map"))
check("low_resolvable", m3 == "low_resolvable", m3)

print("== 4) 源间分歧 -> medium_needs_experiment ==")
m4, why4 = C.classify(rec("UNDETERMINED", n_dom=3, n_indep=2,
                          reason="源间分歧过大（极差=0.37）"))
check("medium_needs_experiment", m4 == "medium_needs_experiment", m4)

print("== 5) 独立组不足 -> low_resolvable ==")
m5, _ = C.classify(rec("UNDETERMINED", n_dom=2, n_indep=1,
                       reason="域内源 2 个但独立方法组仅 1 个 < 要求的 2"))
check("low_resolvable", m5 == "low_resolvable", m5)

print("== 6) PASS 但两维高不确定 -> moderate ==")
m6, _ = C.classify(rec("PASS", "medium", n_dom=1, n_indep=1,
                       reason="1 个域内源一致", spread="0.35"))
check("moderate", m6 == "moderate", m6)

print("== 7) 版本漂移 -> 不得 high ==")
m7, _ = C.classify(rec("PASS", "high", 3, 3, "有实测值"),
                   dims=dict(indirectness="low", inconsistency="low",
                             imprecision="low", risk_of_bias="high(version_drift)"))
check("版本漂移时不是 high", m7 != "high", m7)

print("== 8) 映射表 ==")
check("映射表 5 档", len(C.mapping_table()) == 5)
check("含 low_resolvable", any(x["modifier"] == "low_resolvable"
                               for x in C.mapping_table()))

print("== 9) 方向C：decision_trigger 与决策阈值挂钩 ==")
recs = [rec("PASS", "high", 3, 3, "有实测值"),
        rec("PASS", "medium", n_dom=1, n_indep=1, reason="1 个域内源一致",
            spread="0.35"),
        rec("UNDETERMINED", n_dom=3, n_indep=2, reason="源间分歧过大（极差=0.37）"),
        rec("UNDETERMINED", n_dom=3, n_indep=2,
            reason="跨源单位不一致（class/probability）且规则无 class_map"),
        rec("UNDETERMINED", n_dom=0, n_indep=0,
            reason="全部源域外/失效（flags=out_of_domain）")]
C.annotate(recs)
for r in recs:
    check("每个等级都有 decision_trigger(%s)" % r["certainty_modifier"],
          bool(r.get("decision_trigger")))
    check("每个等级都有 decision_next_step(%s)" % r["certainty_modifier"],
          bool(r.get("decision_next_step")))
low_unres = [r for r in recs if r["certainty_modifier"] == "low_unresolvable"][0]
check("low_unresolvable 明确禁止计算推进",
      "不得基于计算推进" in low_unres["decision_trigger"],
      low_unres["decision_trigger"])
mod = [r for r in recs if r["certainty_modifier"] == "moderate"]
if mod:
    check("moderate 禁止排序", "不得" in mod[0]["decision_trigger"]
          and "排序" in mod[0]["decision_trigger"], mod[0]["decision_trigger"])
check("映射表带 decision_trigger",
      all(x.get("decision_trigger") for x in C.mapping_table()))

print()
if FAIL:
    print("FAILED: %d 条 -> %s" % (len(FAIL), FAIL))
    sys.exit(1)
print("ALL PASS (%d assertions)" % PASS)
