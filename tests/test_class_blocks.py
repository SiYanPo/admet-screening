# -*- coding: utf-8 -*-
"""C82 回归：registry 的 blocked_endpoints_in_class 必须真正生效。

复核发现：registry 里登记得很完整（ADMETlab 的 DILI 14/14 0.643–0.914、
Ames 14/14 0.830–0.990），但**没有任何代码读取**——于是"整类全阳、无区分度"的源
仍在参与裁决，把 DILI/Ames 表现成"源间分歧"而不是"域外"。
这是典型的"写了但没接线"（同 C55）。

跑法: python tests/test_class_blocks.py
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from adt import schema                             # noqa: E402
from adt.reliability import apply_class_blocks     # noqa: E402

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


REG = {"sources": [
    {"name": "admetlab3",
     "blocked_endpoints_in_class": {"glyco": [
         {"endpoint": "DILI", "evidence": "14/14 >0.5，0.643–0.914"},
         {"endpoint": "Ames", "evidence": "14/14 >0.5"}]}},
    {"name": "admet_ai", "blocked_endpoints_in_class": {"glyco": [
        {"endpoint": "DILI", "evidence": "0/14 >0.5（近饱和阴性）"}]}},
]}
CLS = "glyco"

rows = [
    schema.measurement("A", "dili", 0.77, "probability", "admetlab3", "3.0", "predicted"),
    schema.measurement("A", "dili", 0.28, "probability", "admet_ai", "2.0", "predicted"),
    schema.measurement("A", "ames", 0.92, "probability", "admetlab3", "3.0", "predicted"),
    schema.measurement("A", "herg", 0.02, "probability", "admetlab3", "3.0", "predicted"),
]

print("== 1) 命中 blocked 的行被置 out_of_domain ==")
out, det = apply_class_blocks(rows, REG, CLS)
by = {(r["source"], r["endpoint"]): r for r in out}
check("admetlab3.dili 被置域外",
      by[("admetlab3", "dili")]["domain_flag"] == "out_of_domain",
      by[("admetlab3", "dili")]["domain_flag"])
check("admetlab3.ames 被置域外",
      by[("admetlab3", "ames")]["domain_flag"] == "out_of_domain")
check("admet_ai.dili 也被置域外（registry 两条都登记了）",
      by[("admet_ai", "dili")]["domain_flag"] == "out_of_domain")

print("== 2) 未登记的行不受影响 ==")
check("admetlab3.herg 仍是 predicted",
      by[("admetlab3", "herg")]["domain_flag"] == "predicted",
      by[("admetlab3", "herg")]["domain_flag"])

print("== 3) note 留痕（写明证据）==")
check("note 含 blocked 证据", "0.643–0.914" in by[("admetlab3", "dili")]["note"],
      by[("admetlab3", "dili")]["note"][:80])

print("== 4) 汇总 detail 正确 ==")
check("3 组被拦截", len(det) == 3, str([(d["source"], d["endpoint"]) for d in det]))
check("每组 n=1", all(d["n"] == 1 for d in det))

print("== 5) 无该化学类 / 空 registry 时原样返回 ==")
out2, det2 = apply_class_blocks(rows, REG, "other_class")
check("别的化学类不拦", det2 == [] and len(out2) == len(rows))
out3, det3 = apply_class_blocks(rows, {}, CLS)
check("空 registry 不拦", det3 == [] and len(out3) == len(rows))

print("== 6) 大小写归一生效（registry 写 DILI，长表写 dili）==")
check("DILI 与 dili 能对上", det and det[0]["endpoint"] == "dili",
      str(det[0] if det else None))

print()
print("passed %d / failed %d" % (PASS, len(FAIL)))
if FAIL:
    print("FAILED:", FAIL)
    sys.exit(1)
print("ALL OK")
