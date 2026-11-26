# -*- coding: utf-8 -*-
"""C52 回归测试：ChEMBL 参照层的单位/方向归一（**离线，不触网**）。

三条断言直接对应评估报告 P1-3 的三处科学错误：
  1) hERG nM 与 uM 必须换算后再取分位（旧版直接把 10 nM 与 0.5 uM 当同量级）
  2) ppb 的 "% bound" 与 "fu" 必须方向统一为 fu 分数（旧版互为补数还取分位）
  3) clearance 与 half_life 必须分桶（旧版把 "Half Life" 混进 clearance）

跑法: python tests/test_chembl_units.py
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from adt.adapters.chembl import build_reference_rows, canon   # noqa: E402

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


def act(t, v, u):
    return dict(standard_type=t, standard_value=v, standard_units=u)


print("== 1) canon() 单位归一 ==")
check("hERG 10 nM -> 0.01 uM", canon("herg", 10, "nM") == (0.01, "uM"),
      str(canon("herg", 10, "nM")))
check("hERG 0.5 uM 不变", canon("herg", 0.5, "uM") == (0.5, "uM"))
check("hERG 未知单位 -> None", canon("herg", 1, "banana") is None)
_c = canon("ppb_fu", 90, "%")
check("% bound 90 -> fu 0.1", abs(_c[0] - 0.1) < 1e-9 and _c[1] == "fraction", str(_c))
check("fu 0.2 保持", canon("ppb_fu", 0.2, "fraction") == (0.2, "fraction"))
_c = canon("ppb_fu", 2.0, "")
check("fu 以百分数给出 2.0 -> 0.02", abs(_c[0] - 0.02) < 1e-9 and _c[1] == "fraction", str(_c))
check("半衰期 30 min -> 0.5 h", canon("half_life", 30, "min") == (0.5, "h"))
check("清除率 mL/min/kg 保持", canon("clearance", 12, "mL/min/kg") == (12, "ml/min/kg"))
check("溶解度 500 nM -> 0.5 uM（摩尔单位统一）",
      canon("solubility", 500, "nM") == (0.5, "uM"), str(canon("solubility", 500, "nM")))
check("溶解度 1 mg/mL -> 1000 ug/mL",
      canon("solubility", 1, "mg/mL") == (1000.0, "ug/mL"))

print("== 2) hERG：nM 与 uM 混投时先换算再取分位（旧版会算成 5.25）==")
herg = [act("IC50", 10, "nM"), act("IC50", 20, "nM"), act("IC50", 0.5, "uM")]
rows = build_reference_rows("X", [], herg, "chembl", "t", "prov", min_n=3)
p50 = [r for r in rows if r["endpoint"] == "chembl_herg_p50"][0]
check("p50 = 0.02 uM（10/20 nM -> 0.01/0.02 uM，0.5 uM 为离群）",
      abs(float(p50["value"]) - 0.02) < 1e-9, p50["value"])
check("单位标为 uM", p50["unit"] == "uM", p50["unit"])
check("note 记录已做单位换算", "已做单位换算" in p50["note"], p50["note"])

print("== 3) ppb：% bound 与 fu 方向统一（旧版 p50 会是 45.1 这种无意义值）==")
ppb = [act("Protein binding", 90, "%"), act("fu", 0.2, "fraction"),
       act("% bound", 80, "%")]
rows = build_reference_rows("X", ppb, [], "chembl", "t", "prov", min_n=3)
p50 = [r for r in rows if r["endpoint"] == "chembl_ppb_fu_p50"][0]
check("p50 落在 fu 区间 [0.1,0.2] 内", 0.1 <= float(p50["value"]) <= 0.2, p50["value"])
check("单位标为 fraction", p50["unit"] == "fraction", p50["unit"])

print("== 4) clearance 与 half_life 分桶（旧版把 h 与 mL/min/kg 混算）==")
mixed = [act("Clearance", 10, "mL/min/kg"), act("Clearance", 20, "mL/min/kg"),
         act("Clearance", 30, "mL/min/kg"), act("Half Life", 6, "h"),
         act("Half Life", 8, "h"), act("Half Life", 10, "h")]
rows = build_reference_rows("X", mixed, [], "chembl", "t", "prov", min_n=3)
eps = {r["endpoint"] for r in rows}
check("clearance 桶存在", "chembl_clearance_p50" in eps, str(sorted(eps)))
check("half_life 桶独立存在", "chembl_half_life_p50" in eps, str(sorted(eps)))
cl = [r for r in rows if r["endpoint"] == "chembl_clearance_p50"][0]
check("clearance p50=20（未混入 6/8/10 h）", abs(float(cl["value"]) - 20) < 1e-9, cl["value"])
hl = [r for r in rows if r["endpoint"] == "chembl_half_life_p50"][0]
check("half_life p50=8 h", abs(float(hl["value"]) - 8) < 1e-9, hl["value"])

print("== 5) 样本不足 -> out_of_domain 且不带数值 ==")
few = [act("Clearance", 10, "mL/min/kg"), act("Clearance", 20, "mL/min/kg")]
rows = build_reference_rows("X", few, [], "chembl", "t", "prov", min_n=3)
flag = {r["domain_flag"] for r in rows}
vals = {r["value"] for r in rows}
check("flag 全为 out_of_domain", flag == {"out_of_domain"}, str(flag))
check("out_of_domain 行不带数值", vals == {""}, str(vals))

print("== 6) 无法安全归一的单位被丢弃，不凑数 ==")
weird = [act("Clearance", 10, "banana"), act("Solubility", 5, "banana")]
rows = build_reference_rows("X", weird, [], "chembl", "t", "prov", min_n=3)
check("无法归一的记录不产生任何行", rows == [], str(rows))

print()
print("passed %d / failed %d" % (PASS, len(FAIL)))
if FAIL:
    print("FAILED:", FAIL)
    sys.exit(1)
print("ALL OK")
