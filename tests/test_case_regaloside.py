# -*- coding: utf-8 -*-
"""方向B：Regaloside A vs B 的 17.5× 口服生物利用度差异 case study（原稿误写 9×，已更正）。

2026-11-11：全文 Table 3/4 到位，实测 CL_B/CL_A = 63.6–81.3×、
Vz_B/Vz_A = 106.7–130.7×；case 的被动层判定不变，仅结论量级更新。
"""
import sys
sys.path.insert(0, ".")

from adt import case_regaloside as CR


def test_structures_registered_with_cas():
    assert CR.SOURCES["Regaloside_A"]["cas"] == "114420-66-5"
    assert CR.SOURCES["Regaloside_B"]["cas"] == "114420-67-6"
    assert CR.SOURCES["Regaloside_A"]["oral_f_percent"] == 0.52
    assert CR.SOURCES["Regaloside_B"]["oral_f_percent"] == 9.1


def test_bond_position_discriminates_A_primary_B_secondary():
    r = CR.run()
    a = r["per_molecule"]["Regaloside_A"]["gh"]
    b = r["per_molecule"]["Regaloside_B"]["gh"]
    assert a["bond_position"] == "primary", a
    assert b["bond_position"] == "secondary", b
    assert a["acetylated"] is False
    assert b["acetylated"] is True
    assert a["n_ester_bonds"] == 1
    assert b["n_ester_bonds"] == 2


def test_hydrolysis_grade_is_honestly_the_same():
    # 键型相同（都是 alkyl_glycoside，但都有酯键 → high），这是"有价值的限制"
    r = CR.run()
    a = r["per_molecule"]["Regaloside_A"]["gh"]
    b = r["per_molecule"]["Regaloside_B"]["gh"]
    assert a["intestinal_hydrolysis_risk"] == b["intestinal_hydrolysis_risk"] == "high"
    assert any("不足" in x for x in r["cannot_distinguish"])


def test_both_passive_closed_and_determinant_layer():
    r = CR.run()
    for name in ("Regaloside_A", "Regaloside_B"):
        sar = r["per_molecule"][name]["sar"]
        assert sar["passive_permeability_screen"] == "unlikely"
        assert "transporter_resolution_required" in sar["bbb_determinant_layer"]


def test_B_more_lipophilic_than_A():
    r = CR.run()
    d = {x["field"]: x for x in r["diffs"]}
    assert d["HBD"]["delta"] < 0          # B 少一个自由羟基
    assert d["XlogP"]["delta"] > 0        # B 更亲脂
    assert d["MW"]["delta"] > 0


def test_write_case_files(tmp_path):
    r = CR.run()
    p1, p2, p3 = CR.write(r, str(tmp_path))
    assert (tmp_path / "regaloside_AB_comparison.csv").exists()
    txt = (tmp_path / "regaloside_AB_case.md").read_text(encoding="utf-8")
    assert "可检验假设" in txt and "诚实限制" in txt


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
