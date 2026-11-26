# -*- coding: utf-8 -*-
"""糖苷水解-苷元暴露轴：结构判定与风险分级。"""
import sys
sys.path.insert(0, ".")

from adt import glycoside_hydrolysis as GH


def test_parse_failure():
    r = GH.classify("not_a_smiles", "bad")
    assert r["parse_ok"] is False
    assert r["intestinal_hydrolysis_risk"] == "n/a"


def test_free_sugar_no_glycosidic():
    # 葡萄糖：有糖环但无苷元 O-糖苷键
    r = GH.classify("OCC1OC(O)C(O)C(O)C1O", "glucose")
    assert r["sugar_ring"] is True
    assert r["glycosidic_bond"] is False
    assert r["intestinal_hydrolysis_risk"] == "low"


def test_phenolic_glycoside_salicin():
    # 水杨苷：糖的异头 O 直接连苄基 C、苄基 C 连芳环（酚苷）；无酯、无羧酸
    r = GH.classify("Oc1ccccc1COC1OC(O)C(O)C(O)C1O", "salicin")
    assert r["glycosidic_bond"] is True
    assert r["glycoside_bond_type"] == "phenolic_glycoside"
    assert r["ester_bond"] is False
    assert r["intestinal_hydrolysis_risk"] == "medium"


def test_non_glycoside_ester_methyl_salicylate():
    # 水杨酸甲酯：有酯键、有芳环羧酸，但无糖环 → 不是糖苷
    r = GH.classify("COC(=O)c1ccccc1O", "methyl_salicylate")
    assert r["sugar_ring"] is False
    assert r["glycosidic_bond"] is False
    assert r["phenolic_acid_moiety"] is True  # 芳环-羧酸酯


def test_regaloside_like_high_risk():
    # 1-O-β-D-葡萄糖基甘油，甘油中位的羟基被咖啡酸**酯化**（酰基糖苷 / 酯型糖苷键）
    # + 糖-甘油 O-糖苷键（烷基苷）。结构示：O=C(OC...) 为酯，CO[glucose] 为 O-糖苷键。
    smi = "OCC(OC(=O)/C=C/c1ccc(O)cc1)CO[C@H]1O[C@H](CO)[C@@H](O)[C@H](O)[C@H]1O"
    r = GH.classify(smi, "regaloside_like")
    assert r["glycosidic_bond"] is True
    assert r["ester_bond"] is True                       # 咖啡酸甘油酯
    assert r["phenolic_acid_moiety"] is True             # 肉桂酸（咖啡酸）型苷元
    assert r["glycoside_bond_type"] == "alkyl_glycoside"  # 糖-甘油为烷基 O-苷
    assert r["intestinal_hydrolysis_risk"] == "high"     # 酯最易水解
    assert r["aglycone_first_pass_risk"] == "high"       # 酚酸苷元首过/低脑浓度
    # 新增维度：苷元碳取代度 + 酯键数 + 乙酰化
    assert r["bond_position"] in ("primary", "secondary")
    assert r["n_ester_bonds"] >= 1
    assert r["acetylated"] is False


def test_bond_position_and_acetylation_discriminate_AB():
    # Regaloside A：糖在甘油 C1（伯碳），无乙酰化
    a = GH.classify(
        "O(C[C@@H](COC(/C=C/C1=CC=C(O)C=C1)=O)O)[C@@H]2O[C@H](CO)[C@@H](O)[C@H](O)[C@H]2O",
        "Regaloside_A")
    # Regaloside B：糖在甘油 C2（仲碳）+ 乙酰化
    b = GH.classify(
        "CC(=O)OC[C@@H](COC(=O)/C=C/c1ccc(O)cc1)O[C@@H]1O[C@H](CO)[C@@H](O)[C@H](O)[C@H]1O",
        "Regaloside_B")
    assert a["bond_position"] == "primary", a
    assert b["bond_position"] == "secondary", b
    assert a["acetylated"] is False and b["acetylated"] is True
    assert a["n_ester_bonds"] == 1 and b["n_ester_bonds"] == 2


def test_assess_file_io(tmp_path):
    import csv
    p = tmp_path / "c.csv"
    with open(str(p), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["compound_id", "calc_smiles"])
        w.writerow(["X1", "OCC1OC(O)C(O)C(O)C1O"])           # glucose
        w.writerow(["X2", "Oc1ccccc1COC1OC(O)C(O)C(O)C1O"])  # salicin
    rows, op = GH.assess_file(str(p), outdir=str(tmp_path))
    assert len(rows) == 2
    assert op.endswith("glycoside_hydrolysis.csv")


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
