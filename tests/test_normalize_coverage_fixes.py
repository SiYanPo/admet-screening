# -*- coding: utf-8 -*-
"""全流程覆盖测试发现的两个真实 bug 的回归（F4 / F6）。

F4：normalize.charges_and_ph 的碱性氮 SMARTS 旧写 `!$(N-*)`，把**全部胺**排除
    → propranolol（仲胺）报 0 个碱性氮。修复后：仲胺=1，酰胺/芳香氮=0。
F6：desire 的轴分数在**覆盖率不足**时仍写 geo_mean，一个 PASS 端点即显示 1.0
    （"满分安全"），与"缺失不赋分"冲突。修复后：cov<0.5 → geo_mean 留空。

跑法: python tests/test_normalize_coverage_fixes.py
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from adt.normalize import charges_and_ph                 # noqa: E402
from adt.desirability import compound_scores, AXIS_COVERAGE_MIN  # noqa: E402

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


print("== F4 碱性氮判据 ==")
cases = {
    "propranolol": ("CC(C)NCC(O)COc1cccc2ccccc12", 1),   # 仲胺，必须=1
    "caffeine": ("Cn1cnc2c1c(=O)n(C)c(=O)n2C", 0),        # 黄嘌呤 N 非碱性
    "apap": ("CC(=O)Nc1ccc(O)cc1", 0),                    # 酰胺 N 非碱性
    "ibuprofen": ("CC(C)Cc1ccc(cc1)C(C)C(=O)O", 0),
}
for name, (smi, exp) in cases.items():
    d = charges_and_ph(smi)
    check("%s 碱性氮=%d" % (name, exp), d["n_base_sites"] == exp,
          "got %s" % d.get("n_base_sites"))

print("== F4 酸性位点 ==")
check("caffeic_acid 酸性=3（2 酚 + 1 羧酸）",
      charges_and_ph("OC(=O)/C=C/c1ccc(O)c(O)c1")["n_acid_sites"] == 3)
check("ibuprofen 酸性=1（羧酸）",
      charges_and_ph("CC(C)Cc1ccc(cc1)C(C)C(=O)O")["n_acid_sites"] == 1)

print("== F6 覆盖不足时 geo_mean 必须留空 ==")
RULES = {("e%d" % i): dict(shape="step", fail=0.5, axis="safety") for i in range(1, 5)}
# 只 audited 1/4 -> coverage 0.25 < 0.5（e2–e4 以 UNDETERMINED 存在：占分母、不进均值）
rows_low = [dict(compound_id="Z", endpoint="e1", value_used=0.2, verdict="PASS")]
rows_low += [dict(compound_id="Z", endpoint="e%d" % i, value_used="",
                  verdict="UNDETERMINED") for i in range(2, 5)]
_, ax_low = compound_scores(rows_low, RULES)
z = [r for r in ax_low if r["compound_id"] == "Z"][0]
check("cov=0.25 -> flag=insufficient_coverage", z["flag"] == "insufficient_coverage", z)
check("cov=0.25 -> geo_mean 留空（不再假装 1.0）", z["geo_mean"] == "", z["geo_mean"])

# 全 4 个 PASS -> coverage 1.0 -> geo=1.0（正常情况仍要出分数）
rows_full = [dict(compound_id="Y", endpoint="e%d" % i, value_used=0.2, verdict="PASS")
             for i in range(1, 5)]
_, ax_full = compound_scores(rows_full, RULES)
y = [r for r in ax_full if r["compound_id"] == "Y"][0]
check("cov=1.0 -> geo_mean=1.0（正常路径不受影响）", y["geo_mean"] == 1.0, y["geo_mean"])
check("AXIS_COVERAGE_MIN=0.5（判据稳定）", AXIS_COVERAGE_MIN == 0.5)

print()
print("passed %d / failed %d" % (PASS, len(FAIL)))
if FAIL:
    print("FAILED:", FAIL)
    sys.exit(1)
print("ALL OK")
