# -*- coding: utf-8 -*-
"""工作包 C 测试：结构扰动（去盐/中和/互变/立体）+ 预测位移比对。

跑法: python tests/test_perturbation.py
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from adt import perturbation as P  # noqa: E402

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


print("== 1) 去盐：醋酸钠 ==")
vs = P.variants("CC(=O)[O-].[Na+]")
check("desalted 非空", bool(vs["desalted"][0]), str(vs["desalted"]))
check("desalted 不含 Na", "Na" not in vs["desalted"][0], vs["desalted"][0])
d0 = P.descriptor_vector("CC(=O)[O-].[Na+]")
d1 = P.descriptor_vector(vs["desalted"][0])
check("去盐后 MW 下降", d1["mw"] < d0["mw"], "%s vs %s" % (d0["mw"], d1["mw"]))
check("去盐后 heavy 下降", d1["heavy"] < d0["heavy"], "%s vs %s" % (d0["heavy"], d1["heavy"]))

print("== 2) 中和：甘氨酸两性离子 ==")
vs2 = P.variants("[NH3+]CC(=O)[O-]")
check("neutralized 与 original 不同", vs2["neutralized"][0] != vs2["original"][0],
      str(vs2["neutralized"]))
n0 = P.descriptor_vector(vs2["original"][0])
n1 = P.descriptor_vector(vs2["neutralized"][0])
check("中和后 TPSA 变化", abs(n1["tpsa"] - n0["tpsa"]) > 1.0,
      "%s vs %s" % (n0["tpsa"], n1["tpsa"]))
check("中和后 clogp 变化", abs(n1["clogp"] - n0["clogp"]) > 0.5,
      "%s vs %s" % (n0["clogp"], n1["clogp"]))

print("== 3) 零基线相对变化不炸 ==")
check("_rel_delta(0,1)=None", P._rel_delta(0, 1) is None)

print("== 4) 互变丢立体要告警（C4） ==")
vs3 = P.variants("CC(=O)O[C@@H](COC(=O)/C=C/c1ccc(O)c(O)c1)CO[C@@H]1O[C@H](CO)[C@@H](O)[C@H](O)[C@H]1O")
check("tautomer 标丢失立体", "丢失" in vs3["tautomer"][1], vs3["tautomer"][1])

print("== 5) 描述符汇总 ==")
comps = [
    dict(compound_id="salt", input_smiles="CC(=O)[O-].[Na+]"),
    dict(compound_id="zw", input_smiles="[NH3+]CC(=O)[O-]"),
]
rows, agg = P.analyze_descriptors(comps)
check("有明细行", len(rows) > 0, str(len(rows)))
byk = {r["descriptor"]: r for r in agg}
check("mw invariant=N", byk["mw"]["invariant"] == "N", str(byk["mw"]))
check("rings invariant=Y", byk["rings"]["invariant"] == "Y", str(byk["rings"]))

print("== 6) 预测位移 / 源间分歧 ==")
long_rows = [
    dict(compound_id="C", variant="original", endpoint="dili", source="s1",
         value="0.1", unit="probability"),
    dict(compound_id="C", variant="original", endpoint="dili", source="s2",
         value="0.5", unit="probability"),
    dict(compound_id="C", variant="desalted", endpoint="dili", source="s1",
         value="0.2", unit="probability"),
    dict(compound_id="C", variant="desalted", endpoint="dili", source="s2",
         value="0.45", unit="probability"),
]
pa = P.analyze_predictions(long_rows)
r = pa[0]
check("median_delta=0.075", abs(float(r["median_delta"]) - 0.075) < 1e-6, str(r))
check("median_spread=0.4", abs(float(r["median_spread"]) - 0.4) < 1e-6, str(r))
check("ratio=0.1875", abs(float(r["ratio_structure_to_source"]) - 0.1875) < 1e-6, str(r))
check("interpretation 有值", bool(r["interpretation"]), str(r))

print()
if FAIL:
    print("FAILED: %d 条 -> %s" % (len(FAIL), FAIL))
    sys.exit(1)
print("ALL PASS (%d assertions)" % PASS)
