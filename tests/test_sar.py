# -*- coding: utf-8 -*-
"""深水区 2.1：SAR 预筛轴（结构-通透性瓶颈诊断）测试。

核心不变量：
  T1 计算的描述符与 RDKit 一致（真实值，非编造）
  T2 BBB+ 参照（caffeine/theophylline）落在包络内 → plausible
  T3 高极性糖苷（TPSA>140） → unlikely，且瓶颈明确指向 TPSA（糖苷极性负荷）
  T4 最近邻匹配能识别化学型相似物（肉桂酰糖苷 → 二糖/糖苷参照）
  T5 产出是"结构预筛"而非预测：passive_permeability_screen 只取
     plausible/uncertain/unlikely，且 summary 明确标注"预筛"
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from adt import sar

# 苷元（自由羧酸，小分子）
CINNAMIC = "O=C(O)/C=C/c1ccccc1"
# BBB+ 经典
CAFFEINE = "CN1C=NC2=C1C(=O)N(C(=O)N2C)C"
THEOPHYLLINE = "Cn1c(C)nc2c1c(=O)[nH]c(=O)n2C"
# 高极性糖苷（TPSA 远超 90，MW 接近/超 400）
GLUCOSIDE = ("O=C(/C=C/c1ccc(O)cc1)OC[C@@H](O)CO[C@@H]1O[C@H](CO)"
             "[C@@H](O)[C@H](O)[C@H]1O")
GLUCOSE = "OCC1OC(O)C(O)C(O)C1O"


def test_descriptors_real():
    d = sar.compute_descriptors(CAFFEINE)
    assert d["MW"] == 194.2, d
    assert d["TPSA"] is not None and d["HBD"] == 0
    assert d["XlogP"] is not None
    # 肉桂酸：MW 应约 148
    dc = sar.compute_descriptors(CINNAMIC)
    assert 145 < dc["MW"] < 152, dc


def test_bbb_positive_plausible():
    for name, smi in [("caffeine", CAFFEINE), ("theophylline", THEOPHYLLINE)]:
        res = sar.diagnose(smi, name)
        assert res["passive_permeability_screen"] == "plausible", res
        assert res["bottleneck"] == [], res["bottleneck"]


def test_high_polarity_glycoside_unlikely():
    res = sar.diagnose(GLUCOSIDE, "glucoside")
    assert res["passive_permeability_screen"] in ("unlikely", "uncertain"), res
    # 瓶颈必须明确指向 TPSA（糖苷极性负荷），而非肉桂酰基的亲脂性
    bn = ";".join(res["bottleneck"])
    assert "TPSA" in bn, "瓶颈应明确包含 TPSA（糖苷极性负荷）：%s" % bn
    assert res["TPSA"] > 140, res
    assert "预筛" in res["summary"]


def test_nearest_neighbor_sensible():
    res = sar.diagnose(GLUCOSE, "glucose")
    assert res["nearest_label"] == "-", res
    # 糖苷类最近邻应是二糖/单糖（sucrose/glucose），不是 BBB+ 小分子
    assert res["nearest_ref"] in ("sucrose", "glucose"), res["nearest_ref"]


def test_screen_is_not_prediction():
    res = sar.diagnose(CAFFEINE, "caffeine")
    assert res["passive_permeability_screen"] in ("plausible", "uncertain", "unlikely")
    assert "预筛" in res["summary"]
    # 参照集每个都带来源标注
    assert all("BBB" in r for r in res["references_used"])


def test_invalid_smiles():
    res = sar.diagnose("zzz", "bad")
    assert res["MW"] is None
    assert res["passive_permeability_screen"] == "uncertain"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
