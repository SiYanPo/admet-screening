# -*- coding: utf-8 -*-
"""C80 回归：物理不可能值必须挡在裁决（和下游计算）之外。

实测来源：ADMET-AI 的 `Clearance_Microsome_AZ` 在 APAP 上给 **−4.3**、
甘氨酸 **−31.4**、磷酸乙醇胺 **−10.3**（负清除率）。7 个试点分子里 3 个负值。
若放行，well-stirred 会算出 Eh<0 → Fh>1，口服暴露估计直接失真。

跑法: python tests/test_phys_range.py
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from adt import schema                                # noqa: E402
from adt.reliability import evaluate, in_phys_range   # noqa: E402

PASS = 0
FAIL = []

RULE = {"shape": "down", "pass": 30, "fail": 100, "require_sources": 2,
        "phys_range": [0, 5000]}
GROUPS = {"ml": "descriptor_ml", "nb": "neighbor_qsar"}


def check(name, cond, detail=""):
    global PASS
    if cond:
        PASS += 1
        print("  ok  %s" % name)
    else:
        FAIL.append(name)
        print("FAIL  %s  %s" % (name, detail))


def m(cid, ep, src, v, unit="uL/min/mg"):
    return schema.measurement(cid, ep, v, unit, src, "t", "predicted")


print("== 1) in_phys_range 基本语义 ==")
check("负值越界", in_phys_range(-4.3, RULE) is False)
check("0 在界内（边界闭合）", in_phys_range(0, RULE) is True)
check("5000 在界内", in_phys_range(5000, RULE) is True)
check("5001 越界", in_phys_range(5001, RULE) is False)
check("无 rule 视为通过", in_phys_range(-4.3, None) is True)
check("rule 无 phys_range 视为通过", in_phys_range(-4.3, {"shape": "down"}) is True)

print("== 2) 唯一值越界 → 不判，且说明原因 ==")
r = evaluate([m("APAP", "clint_microsome", "ml", -4.3)], {"clint_microsome": RULE},
             source_groups=GROUPS)[0]
check("verdict=UNDETERMINED", r["verdict"] == "UNDETERMINED", r["verdict"])
check("reason 指出越物理边界", "越物理边界" in r["reason"], r["reason"])
check("action 禁止下游使用", "下游" in r["action"], r["action"])

print("== 3) 两源一致但一个越界 → 只用合法那个（且退化为单组）==")
r = evaluate([m("X", "clint_microsome", "ml", -4.3),
              m("X", "clint_microsome", "nb", 25.8)], {"clint_microsome": RULE},
             source_groups=GROUPS)[0]
check("单组不足 → UNDETERMINED", r["verdict"] == "UNDETERMINED", r["verdict"])
check("保留了合法值", abs(float(r["value_used"]) - 25.8) < 1e-9, str(r["value_used"]))
check("reason 记录剔除数", "剔除" in r["reason"], r["reason"])

print("== 4) 两个合法值 → 正常判（边界不干扰正常路径）==")
r = evaluate([m("Y", "clint_microsome", "ml", 25.8),
              m("Y", "clint_microsome", "nb", 24.0)], {"clint_microsome": RULE},
             source_groups=GROUPS)[0]
check("2 组合法值 → PASS（<30）", r["verdict"] == "PASS", r["verdict"])

print("== 5) Caco-2 正数（>1 cm/s）也属物理不可能 ==")
CAC = {"shape": "up", "pass": -5.3, "fail": -6.0, "require_sources": 2,
       "phys_range": [-12, 0]}
r = evaluate([m("Z", "caco2_papp_ab", "ml", 0.5, "log10(cm/s)")],
             {"caco2_papp_ab": CAC}, source_groups=GROUPS)[0]
check("正 log Papp 被挡", r["verdict"] == "UNDETERMINED", r["verdict"])

print("== 6) v3.6.1 回归：实测值也必须过 phys_range（OneADMET 实测暴露的漏洞）==")
def mm(cid, ep, src, v, unit="uL/min/mg"):
    return schema.measurement(cid, ep, v, unit, src, "t", "measured")

# 6a) 唯一实测值越界 → 不得借实测路径判决
r = evaluate([mm("W", "clint_microsome", "lab", 10354.0)],
             {"clint_microsome": RULE}, source_groups=GROUPS)[0]
check("6a 实测越界 → UNDETERMINED", r["verdict"] == "UNDETERMINED", r["verdict"])
check("6a reason 指出越物理边界", "越物理边界" in r["reason"], r["reason"])
check("6a n_in_domain=0（域外触发）", int(r["n_in_domain"]) == 0, str(r["n_in_domain"]))

# 6b) 实测一个越界 + 一个合法 → 只用合法那个，正常判
r = evaluate([mm("V", "clint_microsome", "lab", 10354.0),
              mm("V", "clint_microsome", "lab2", 25.8)],
             {"clint_microsome": RULE}, source_groups=GROUPS)[0]
check("6b 合法实测值保留并判决", r["verdict"] == "PASS", r["verdict"])
check("6b 用的是合法值", abs(float(r["value_used"]) - 25.8) < 1e-9, str(r["value_used"]))

# 6c) 预测越界 + 实测越界 → 全部越物理边界
r = evaluate([mm("U", "clint_microsome", "lab", -4.3),
              m("U", "clint_microsome", "ml", -31.4)],
             {"clint_microsome": RULE}, source_groups=GROUPS)[0]
check("6c 混合越界 → UNDETERMINED", r["verdict"] == "UNDETERMINED", r["verdict"])
check("6c reason 指出越物理边界", "越物理边界" in r["reason"], r["reason"])

print()
print("passed %d / failed %d" % (PASS, len(FAIL)))
if FAIL:
    print("FAILED:", FAIL)
    sys.exit(1)
print("ALL OK")
