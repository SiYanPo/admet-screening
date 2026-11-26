# -*- coding: utf-8 -*-
"""C77/C78 回归：默认两独立组 + 异构单位按类别投射。

C77：`require_sources` 默认值原为 1，导致未显式声明的端点（nr_ar_lbd/sr_p53/sr_are）
     仅凭单组就被判 PASS/FAIL，与"两票半"原则矛盾。
C78：hERG/MMP 上 vNN 给**类别 0/1**、ADMET-AI 给**概率**。直接取中位数会把
     "类别 0（无信号）"当成"概率 0"，本地版数值偏低时恰好躲过 spread 守卫，
     产出一个**假 PASS**（实测本地版 hERG 6 个 PASS，修后归零）。

跑法: python tests/test_strict_and_mixed_units.py
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from adt import schema                    # noqa: E402
from adt.reliability import evaluate      # noqa: E402

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


def m(cid, ep, src, v, unit):
    return schema.measurement(cid, ep, v, unit, src, "t", "predicted")


GROUPS = {"ml": "descriptor_ml", "nb": "neighbor_qsar"}

print("== 1) C77：默认要求 2 个独立方法组 ==")
# 只有一个源、规则未写 require_sources → 必须 UNDETERMINED
rel = evaluate([m("X", "custom_ep", "ml", 0.9, "probability")],
               {"custom_ep": {"shape": "up", "pass": 0.5}}, source_groups=GROUPS)
r = rel[0]
check("单组 + 规则未声明 → UNDETERMINED", r["verdict"] == "UNDETERMINED", r["verdict"])
check("reason 写明要求 2", "要求的 2" in r["reason"], r["reason"])

print("== 2) 两个独立组方向一致 → 可判 ==")
rel = evaluate([m("X", "custom_ep", "ml", 0.9, "probability"),
                m("X", "custom_ep", "nb", 0.8, "probability")],
               {"custom_ep": {"shape": "up", "pass": 0.5}}, source_groups=GROUPS)
check("2 组一致 → PASS", rel[0]["verdict"] == "PASS", rel[0]["verdict"])

print("== 3) C78：class 0/1 与 probability 混用 ==")
RULE = {"shape": "down", "pass": 0.3, "fail": 0.7,
        "class_map": {"0": "PASS", "1": "FAIL"}, "require_sources": 2}

# 类别 1（阳性）与概率 0.02（阴性）方向相反 → 必须 UNDETERMINED，禁止取中位数
rel = evaluate([m("Y", "mmp", "nb", 1, "class"),
                m("Y", "mmp", "ml", 0.02, "probability")], {"mmp": RULE},
               source_groups=GROUPS)
r = rel[0]
check("方向相反 → UNDETERMINED", r["verdict"] == "UNDETERMINED", r["verdict"])
check("reason 指出单位异构", "单位不一致" in r["reason"], r["reason"])

# 类别 0（阴性）与概率 0.05（阴性）→ 方向一致，可判 PASS
rel = evaluate([m("Z", "mmp", "nb", 0, "class"),
                m("Z", "mmp", "ml", 0.05, "probability")], {"mmp": RULE},
               source_groups=GROUPS)
r = rel[0]
check("类别 0 + 概率 0.05 → PASS", r["verdict"] == "PASS", r["verdict"])
check("报告的数值取概率子集（0.05），不是中位数 0.025",
      abs(float(r["value_used"]) - 0.05) < 1e-9, str(r["value_used"]))
check("unit 记为 probability", r["unit"] == "probability", r["unit"])

# 概率落在灰区（0.5）→ 不能投射出一致方向
rel = evaluate([m("W", "mmp", "nb", 0, "class"),
                m("W", "mmp", "ml", 0.5, "probability")], {"mmp": RULE},
               source_groups=GROUPS)
check("概率在灰区 → UNDETERMINED", rel[0]["verdict"] == "UNDETERMINED",
      rel[0]["verdict"])

print("== 4) 无 class_map 时必须拒判（不许猜）==")
rel = evaluate([m("V", "hero", "nb", 0, "class"),
                m("V", "hero", "ml", 0.02, "probability")],
               {"hero": {"shape": "down", "pass": 0.1, "fail": 0.5,
                         "require_sources": 2}}, source_groups=GROUPS)
check("缺 class_map → UNDETERMINED", rel[0]["verdict"] == "UNDETERMINED",
      rel[0]["verdict"])
check("action 提示补 class_map", "class_map" in rel[0]["action"], rel[0]["action"])

print()
print("passed %d / failed %d" % (PASS, len(FAIL)))
if FAIL:
    print("FAILED:", FAIL)
    sys.exit(1)
print("ALL OK")
