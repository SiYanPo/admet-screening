# -*- coding: utf-8 -*-
"""工作包 E 测试：Dempster-Shafer 组合 + 证据准入对照。

跑法: python tests/test_dst.py
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from adt import dst as DS  # noqa: E402

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


print("== 1) mass 构造 ==")
m = DS.mass_from_value(0.8, "probability")
check("pos=0.8", abs(m["pos"] - 0.8) < 1e-9, str(m))
check("neg=0.2", abs(m["neg"] - 0.2) < 1e-9, str(m))
check("theta=0", abs(m["theta"]) < 1e-9, str(m))
mc = DS.mass_from_value(1, "class")
check("类别 1 -> pos=1", mc["pos"] == 1.0, str(mc))

print("== 2) ignorance 是 Dempster 单位元 ==")
ign = DS.ignorance()
comb, K = DS.combine([m, ign], "dempster")
check("组合后 mass 不变", abs(comb["pos"] - 0.8) < 1e-9, str(comb))
check("冲突 K=0", abs(K) < 1e-9, str(K))

print("== 3) 冲突组合 ==")
a = DS.mass_from_value(0.9, "probability")   # pos .9 / neg .1
b = DS.mass_from_value(0.1, "probability")   # pos .1 / neg .9
comb2, K2 = DS.combine([a, b], "dempster")
check("K=0.82", abs(K2 - 0.82) < 1e-9, str(K2))
check("归一后 pos=0.5", abs(comb2["pos"] - 0.5) < 1e-9, str(comb2))
bp = DS.belief_plausibility(comb2)
check("Bel(pos)=0.5", abs(bp["bel_pos"] - 0.5) < 1e-9, str(bp))
check("Pl(pos)=0.5", abs(bp["pl_pos"] - 0.5) < 1e-9, str(bp))
d, r = DS.decide(bp)
check("判 FAIL（Bel 恰好 0.5）", d == "FAIL", "%s %s" % (d, r))

print("== 4) Yager 冲突归 ignorance ==")
comb3, K3 = DS.combine([a, b], "yager")
check("K=0.82", abs(K3 - 0.82) < 1e-9, str(K3))
check("theta=0.82", abs(comb3["theta"] - 0.82) < 1e-9, str(comb3))

print("== 5) 准入对照：blocked 源仍投票 vs 排除 ==")
rows = [dict(compound_id="X", endpoint="DILI", value="0.9", unit="probability",
             source="s1", domain_flag="predicted"),
        dict(compound_id="X", endpoint="DILI", value="0.1", unit="probability",
             source="s2", domain_flag="predicted")]
rel = [dict(compound_id="X", endpoint="DILI", verdict="UNDETERMINED")]
cmp = DS.compare(rows, blocked={("s1", "dili")}, reliability=rel)[0]
check("all-in 判 FAIL", cmp["allin_decision"] == "FAIL", str(cmp))
check("准入判 PASS", cmp["adm_decision"] == "PASS", str(cmp))
check("裁决不同", cmp["decisions_differ"] == "Y", str(cmp))
check("标过度裁决", cmp["dst_overclaims"] == "Y", str(cmp))
check("n_blocked=1", cmp["n_blocked"] == 1, str(cmp))

print("== 6) summary ==")
s = DS.summarize([cmp])
check("n=1", s["n"] == 1, str(s))
check("过度裁决=1", s["dst_overclaims_vs_reliab"] == 1, str(s))

print()
if FAIL:
    print("FAILED: %d 条 -> %s" % (len(FAIL), FAIL))
    sys.exit(1)
print("ALL PASS (%d assertions)" % PASS)
