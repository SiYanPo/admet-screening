# -*- coding: utf-8 -*-
"""工作包 A 测试：独立性量化 + 校准计票。

跑法: python tests/test_independence.py
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from adt import independence as I  # noqa: E402

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


def row(cid, ep, src, v, unit="probability", flag="predicted"):
    return dict(compound_id=cid, endpoint=ep, source=src, value=str(v),
                unit=unit, domain_flag=flag)


print("== 1) Spearman ==")
check("单调升 = 1.0", abs(I.spearman([1, 2, 3, 4, 5], [2, 4, 6, 8, 10]) - 1.0) < 1e-9)
check("单调降 = -1.0", abs(I.spearman([1, 2, 3, 4, 5], [10, 8, 6, 4, 2]) + 1.0) < 1e-9)
check("并列秩不炸", I.spearman([1, 1, 2, 3], [1, 2, 2, 3]) is not None)

print("== 2) Fleiss kappa ==")
perfect = [[1, 1, 1], [0, 0, 0], [1, 1, 1]]
k = I.fleiss_kappa(perfect)
check("完全一致 kappa=1", abs(k["kappa"] - 1.0) < 1e-9, str(k))
mixed = [[1, 1, 0], [0, 0, 1], [1, 0, 1], [0, 1, 0]]
k2 = I.fleiss_kappa(mixed)
check("随机一致 kappa 明显 <1", k2["kappa"] is not None and k2["kappa"] < 0.6, str(k2))

print("== 3) pairwise + 组权重 ==")
groups = {"a1": "G", "a2": "G", "b1": "H"}
rows = []
vals = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]
for i, v in enumerate(vals):
    rows.append(row("C%d" % i, "e", "a1", v))
    rows.append(row("C%d" % i, "e", "a2", v + 0.01))
pairs = I.pairwise_stats(rows, groups)
g = [x for x in pairs if x["source_a"] == "a1"][0]
check("同组配对 ρ≈1", g["same_group"] and abs(float(g["spearman"]) - 1.0) < 0.05, str(g))
gs = I.group_summary(pairs, groups)
check("ρ>=0.9 组权重降为 0.5", gs[0]["group_weight"] == 0.5, str(gs))
check("evidence 标 redundant", "redundant" in gs[0]["evidence"], gs[0]["evidence"])

print("== 4) 负相关 -> sign_conflict ==")
rows2 = []
for i, v in enumerate(vals):
    rows2.append(row("C%d" % i, "e", "a1", v))
    rows2.append(row("C%d" % i, "e", "a2", 1.0 - v))
pairs2 = I.pairwise_stats(rows2, groups)
g2 = [x for x in pairs2 if x["source_a"] == "a1"][0]
check("ρ<0 标 sign_conflict", g2["sign_conflict"] == "Y", str(g2))
gs2 = I.group_summary(pairs2, groups)
check("负相关不当作冗余降权", gs2[0]["group_weight"] == 1.0, str(gs2[0]))
check("组摘要含 sign_conflict", "sign_conflict" in gs2[0]["evidence"], gs2[0]["evidence"])

print("== 5) effective_votes / 伪共识 ==")
rows3 = [row("C0", "e", "a1", 0.2), row("C0", "e", "a2", 0.9),
         row("C0", "e", "b1", 0.3)]
eff = I.effective_votes(rows3, groups, [dict(group="G", group_weight=0.5),
                                       dict(group="H", group_weight=0.5)])
r0 = eff[0]
check("两组但有效票=1.0", abs(r0["effective_votes"] - 1.0) < 1e-9, str(r0))
check("标 pseudo_consensus", r0["pseudo_consensus"] == "Y", str(r0))

print("== 6) vote_calibration ==")
# k=3/3 全对；k=1/3 全错
measurements = []
truth = []
for i in range(6):
    cid = "T%d" % i
    if i < 3:
        vs = [1, 1, 1]
        tcls = "FAIL"
    else:
        vs = [1, 0, 0]
        tcls = "FAIL"      # 多数票=0(阴性) 与真值 FAIL 不符 -> 该记错误
    for j, v in enumerate(vs):
        measurements.append(row(cid, "DILI", "s%d" % j, v))
    truth.append(dict(compound_id=cid, endpoint="DILI", truth_class=tcls))
cal = I.vote_calibration(measurements, truth, rules={})
byk = {int(r["k"]): r for r in cal}
check("k=3 的 u 低于 k=1", byk[3]["u_smoothed"] < byk[1]["u_smoothed"],
      "%s vs %s" % (byk[3]["u_smoothed"], byk[1]["u_smoothed"]))
check("k=3 vote_confidence 高", float(byk[3]["vote_confidence"]) > 0.5,
      str(byk[3]))
check("小样本标 insufficient", byk[3]["status"] == "insufficient",
      byk[3]["status"])

print()
if FAIL:
    print("FAILED: %d 条 -> %s" % (len(FAIL), FAIL))
    sys.exit(1)
print("ALL PASS (%d assertions)" % PASS)
