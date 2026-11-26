# -*- coding: utf-8 -*-
"""工作包 D 测试：决策曲线 + 实验预算三策略。

跑法: python tests/test_decision_value.py
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from adt import decision_value as D  # noqa: E402

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


print("== 1) decision curve 解析解 ==")
c = D.decision_curve([0.9, 0.1], [1, 0], thresholds=[0.5])
check("pt=0.5 选 1 个", c[0]["n_selected"] == 1, str(c))
check("TP=1 FP=0", c[0]["tp"] == 1 and c[0]["fp"] == 0, str(c))
check("NB=0.5", abs(c[0]["net_benefit"] - 0.5) < 1e-9, str(c))
c2 = D.decision_curve([0.9, 0.3], [1, 0], thresholds=[0.2])
check("pt=0.2 选 2 个", c2[0]["n_selected"] == 2, str(c2))
check("NB=-1.5", abs(c2[0]["net_benefit"] + 1.5) < 1e-9, str(c2))

print("== 2) 三策略（合成） ==")
def rec(cid, verdict, conf, n_dom=3, n_indep=3, reason="", spread="0.1"):
    return dict(compound_id=cid, endpoint="e", verdict=verdict,
                confidence=conf, n_in_domain=n_dom, n_indep_groups=n_indep,
                reason=reason, spread=spread, n_total=3, action="补源")

recs = [rec("C1", "PASS", "high"),
        rec("C2", "FAIL", "low"),
        rec("C3", "UNDETERMINED", "low", 2, 1,
            "域内源 2 个但独立方法组仅 1 个 < 要求的 2")]
good = {("C1", "e"): 1, ("C2", "e"): 0, ("C3", "e"): 1}
rows, meta = D.resource_allocation(recs, good, budget=2, cost_fp=3.0,
                                   p_convert=0.5)
check("三策略", len(rows) == 3, str(rows))
by = {r["strategy"]: r for r in rows}
check("vote_all 选 2 个", by["vote_all"]["n_selected"] == 2, str(by["vote_all"]))
check("admission 选 >0 个", by["admission"]["n_selected"] > 0, str(by["admission"]))
check("random 期望 = budget", abs(by["random"]["n_selected"] - 2) < 1e-9,
      str(by["random"]))
check("meta n_compounds=3", meta["n_compounds"] == 3, str(meta))
check("meta 有可解决计数", meta["n_resolvable"] >= 1, str(meta))

print("== 3) 无真值/无 proxy 不臆造 ==")
res = D.build(recs, None, None, None, proxy="none")
check("返回 error", bool(res.get("error")), str(res))

print("== 4) proxy 标签（含端点别名） ==")
meas = [dict(compound_id="X", endpoint="DILI", value="0.1", unit="probability",
             domain_flag="predicted", source="s1"),
        dict(compound_id="Y", endpoint="DILI", value="0.9", unit="probability",
             domain_flag="predicted", source="s1")]
gm = D._proxy_map(meas, {"dili": {"shape": "down", "pass": 0.5, "fail": 0.5}})
check("X 标为好=1", gm.get(("X", "DILI")) == 1, str(gm))
check("Y 标为坏=0", gm.get(("Y", "DILI")) == 0, str(gm))

print()
if FAIL:
    print("FAILED: %d 条 -> %s" % (len(FAIL), FAIL))
    sys.exit(1)
print("ALL PASS (%d assertions)" % PASS)
