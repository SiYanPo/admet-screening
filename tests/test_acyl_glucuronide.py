# -*- coding: utf-8 -*-
"""深水区 2.3：酰基葡萄糖醛酸化结构警示与风险分级测试。

核心不变量（与全 skill 一致，结构警示不是预测）：
  T1 自由羧酸 + α-碳可烯醇化 + 共轭 → high（肉桂酸/咖啡酸/阿魏酸类）
  T2 糖苷（酯键，无自由羧酸）→ low（酯酶水解才间接产生风险）
  T3 无羧酸/酯 → low
  T4 苯甲酸类（共轭但 α 无烯醇化氢）→ medium
  T5 风险分级只给 grade，不产出任何数值型"发生率"
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from adt import acyl_glucuronide as AG

# 苷元：自由羧酸、共轭、α-碳可烯醇化（CH=）
CINNAMIC = "O=C(O)/C=C/c1ccccc1"
CAFFEIC = "O=C(O)/C=C/c1ccc(O)c(O)c1"
FERULIC = "COc1cc(/C=C/C(=O)O)ccc1O"
# 糖苷：肉桂酰基以酯键接糖（无自由羧酸）
GLUCOSIDE_ESTER = ("O=C(/C=C/c1ccc(O)cc1)OC[C@@H](O)CO[C@@H]1O[C@H](CO)"
                   "[C@@H](O)[C@H](O)[C@H]1O")
# 苯甲酸：共轭但 α-碳是芳环（无烯醇化氢）
BENZOIC = "O=C(O)c1ccccc1"
# 无羧酸/酯
CAFFEINE = "CN1C=NC2=C1C(=O)N(C(=O)N2C)C"
GLUCOSE = "OCC1OC(O)C(O)C(O)C1O"


def test_aglycone_high_risk():
    for name, smi in [("cinnamic", CINNAMIC), ("caffeic", CAFFEIC), ("ferulic", FERULIC)]:
        r = AG.risk(smi, name)
        assert r["has_carboxylic_acid"], "%s 应识别到自由羧酸" % name
        assert r["conjugated"], "%s 应识别到共轭" % name
        assert r["enolizable"], "%s 的 α-碳应可烯醇化" % name
        assert r["grade"] == "high", "%s 应为 high（%s）" % (name, r["grade"])


def test_glycoside_ester_indirect_low():
    r = AG.risk(GLUCOSIDE_ESTER, "glycoside")
    assert not r["has_carboxylic_acid"], "糖苷酯键不含自由羧酸"
    assert r["has_ester"], "应识别到酯键"
    assert r["grade"] == "low", "糖苷本身应为 low（间接风险）"
    assert any("水解" in x for x in r["reasons"]), "应提示酯酶水解释放羧酸"


def test_no_acid_low():
    for name, smi in [("caffeine", CAFFEINE), ("glucose", GLUCOSE)]:
        r = AG.risk(smi, name)
        assert not r["has_carboxylic_acid"]
        assert r["grade"] == "low"


def test_benzoic_medium():
    r = AG.risk(BENZOIC, "benzoic")
    assert r["has_carboxylic_acid"]
    assert r["conjugated"]
    assert not r["enolizable"], "苯甲酸 α-碳为芳环，无烯醇化氢"
    assert r["grade"] == "medium"


def test_no_predicted_value():
    # 结构警示不得产出数值型"发生率"
    r = AG.risk(CINNAMIC, "cinnamic")
    assert "grade" in r and isinstance(r["grade"], str)
    # reasons 必须明确这是结构警示而非实测
    assert any("结构警示" in x or "非实测" in x or "监测" in x for x in r["reasons"])


def test_invalid_smiles():
    r = AG.risk("not_a_smiles", "bad")
    assert r["grade"] == "low"
    assert any("解析失败" in x for x in r["reasons"])


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
