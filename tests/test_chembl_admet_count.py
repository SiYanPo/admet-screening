# -*- coding: utf-8 -*-
"""C79 回归：ChEMBL 邻居多 ≠ 有 ADMET 实测。

背景：肉桂酰糖苷类 14 个分子在 ChEMBL 各有 180–340 条邻居活性记录，
但 Caco-2 / 蛋白结合 / 微粒体清除的实测**合计 0 条**（全是 GI50/IC50）。
若不显式统计，会误以为"能给三项湿实验替代补第二组"。

跑法: python tests/test_chembl_admet_count.py
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from adt.adapters.chembl import _count_admet_assays, ADMET_ASSAY_KEYS  # noqa: E402

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


print("== 1) 只数 ADMET 类，不数细胞毒 ==")
acts = [{"standard_type": "GI50"}, {"standard_type": "IC50"},
        {"standard_type": "Inhibition"}, {"standard_type": "Activity"}]
check("纯细胞毒/抑制 → 0", _count_admet_assays(acts) == 0,
      str(_count_admet_assays(acts)))

print("== 2) 各类 ADMET 测定都要被认出来 ==")
for st in ("Caco-2", "PAMPA", "Protein Binding", "PPB", "Fraction unbound",
           "Microsomal intrinsic clearance", "Hepatocyte clearance", "CLint"):
    a = [{"standard_type": st}]
    check("识别 %r" % st, _count_admet_assays(a) == 1, str(_count_admet_assays(a)))

print("== 3) 大小写与空值不影响 ==")
check("小写 caco-2", _count_admet_assays([{"standard_type": "caco-2"}]) == 1)
check("None 类型不报错", _count_admet_assays([{"standard_type": None}]) == 0)
check("空列表返回 0", _count_admet_assays([]) == 0)

print("== 4) 混合记录只计 ADMET 那条 ==")
mix = [{"standard_type": "GI50"}, {"standard_type": "Caco-2"},
       {"standard_type": "IC50"}, {"standard_type": "Protein Binding"}]
check("4 条里 2 条 ADMET", _count_admet_assays(mix) == 2, str(_count_admet_assays(mix)))

print("== 5) 关键词表覆盖三类湿实验 ==")
joined = " ".join(ADMET_ASSAY_KEYS)
check("含渗透关键词", "caco" in joined and "permeab" in joined)
check("含结合关键词", "ppb" in joined and "unbound" in joined)
check("含代谢关键词", "microsom" in joined and "clearance" in joined)

print()
print("passed %d / failed %d" % (PASS, len(FAIL)))
if FAIL:
    print("FAILED:", FAIL)
    sys.exit(1)
print("ALL OK")
