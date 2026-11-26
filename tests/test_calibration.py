# -*- coding: utf-8 -*-
"""U2 回归：概率端点校准（Van Calster 2019, BMC Med 17:230）。

验收点：
  1) 完美校准 -> slope=1、intercept=0、ECE≈0、flag=acceptable
  2) 系统性低估 -> O:E>1、intercept>0、flag=poor（方向必须对）
  3) 量纲门控：percentile / µL/min/mg / log10 一律 not_applicable
     （DrugBank percentile 不是概率，混进来会算出假校准）
  4) 小样本 -> insufficient，不返回可疑数字
  5) 单一类别 -> 不报斜率
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adt import calibration as C  # noqa: E402

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


def _well_cal():
    p, y = [], []
    for k in range(1, 10):
        pr = k / 10.0
        p += [pr] * 20
        y += [1 if i < round(pr * 20) else 0 for i in range(20)]
    return p, y


p, y = _well_cal()

print("== 1) 完美校准 ==")
r = C.assess(p, y, unit="probability")
check("slope=1.000", abs(r["cal_slope"] - 1.0) < 0.02, r["cal_slope"])
check("intercept=0.000", abs(r["cal_intercept"]) < 0.02, r["cal_intercept"])
check("ECE≈0", r["ece"] <= 0.02, r["ece"])
check("O:E=1", abs(r["oe"] - 1.0) < 0.02, r["oe"])
check("flag=acceptable", r["flag"] == "acceptable", r["flag"])

print("== 2) 系统性低估（报的概率偏低） ==")
p_low = [0.02 + 0.9 * (v ** 3) for v in p]
r2 = C.assess(p_low, y, unit="probability")
check("O:E>1（观测多于期望）", r2["oe"] > 1.2, r2["oe"])
check("intercept>0（系统性低估）", r2["cal_intercept"] > 0.3, r2["cal_intercept"])
check("flag=poor", r2["flag"] == "poor", r2["flag"])
check("note 含'系统性偏移'", "系统性偏移" in r2["note"], r2["note"])

print("== 3) 量纲门控 ==")
for unit in ("percentile", "uL/min/mg", "log10(cm/s)", "%"):
    ok, mode, why = C.is_probability(unit, [0.1, 0.9])
    check("%s 拒绝校准" % unit, ok is False and mode == "", (ok, mode, why))
r3 = C.assess([0.1, 0.9] * 20, [0, 1] * 20, unit="percentile")
check("percentile -> not_applicable", r3["flag"] == "not_applicable", r3)
check("拒绝时不给 brier", r3["brier"] == "", r3["brier"])

print("== 3b) 越界值必须拒绝 ==")
ok, _, why = C.is_probability("probability", [0.1, 1.4])
check("值域越界 -> 拒绝", ok is False, why)

print("== 4) 小样本 ==")
r4 = C.assess([0.1, 0.9, 0.8], [0, 1, 1], unit="probability")
check("flag=insufficient", r4["flag"] == "insufficient", r4["flag"])
check("不给 slope", r4["cal_slope"] == "", r4["cal_slope"])

print("== 5) 单一类别 ==")
r5 = C.assess([0.1] * 40, [0] * 40, unit="probability")
check("单一类别 -> insufficient", r5["flag"] == "insufficient", r5["flag"])
check("slope 为空", r5["cal_slope"] == "", r5["cal_slope"])

print("== 6) 校准表与 Wilson CI ==")
tb = C.table(p, y)
check("分箱非空", len(tb) >= 5, len(tb))
check("每箱有 CI 边界", all(r["ci_low"] != "" and r["ci_high"] != "" for r in tb), tb[:1])
check("完美校准每箱 gap≈0", all(abs(r["gap"]) < 0.05 for r in tb), tb[:3])
check("Σn = 样本数", sum(r["n"] for r in tb) == len(p), sum(r["n"] for r in tb))

print()
print("passed %d / failed %d" % (PASS, len(FAIL)))
if FAIL:
    print("FAILED:", FAIL)
    sys.exit(1)
print("ALL OK")
