# -*- coding: utf-8 -*-
"""v4.14–v4.20 扩展模块自检（pKa / 心脏三联 / PK-PD / PBPK 资格 / interop / 菌群 / 回填）。

纪律（与本 skill 其余测试一致）：
  · 只验证**契约与边界**（结构完整性、闸门是否开火、单位是否被拦），
    不验证预测准确性（那需要湿实验或外部工具实跑）；
  · 每个"禁止"分支都必须有一条**必须失败**的用例（成对断言）；
  · 网络相关的菌群模块只测纯函数（parse/label check），真实调用在 CHANGELOG 里留实跑证据。
"""
import csv
import io
import os
import sys

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from adt import ionization as IZ                      # noqa: E402
from adt import cardiac_panel as CP                   # noqa: E402
from adt import pd_link as PD                         # noqa: E402
from adt import pbpk_qualify as PQ                    # noqa: E402
from adt import interop as IO                         # noqa: E402
from adt import gut_microbiome as GM                  # noqa: E402
from adt import readback as RB                        # noqa: E402


# ---------------------------------------------------------------- pKa / 电离
def test_acid_and_base_direction():
    """羧酸在 pH 7.4 应电离（负），脂肪胺应质子化（正）——方向不能反。"""
    acid = IZ.ionization_profile("CC(=O)Oc1ccccc1C(=O)O")       # aspirin
    base = IZ.ionization_profile("NCc1ccccc1")                  # benzylamine
    assert acid["net_charge"] < -0.9
    assert base["net_charge"] > 0.9
    assert acid["charge_class"] == "ionized_dominant"
    assert base["charge_class"] == "ionized_dominant"


def test_no_ionizable_group_is_neutral_not_error():
    """葡萄糖没有可电离基团 → neutral_no_group，而不是 available=False。"""
    p = IZ.ionization_profile("OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O")
    assert p["available"] is True
    assert p["charge_class"] == "neutral_no_group"
    assert p["f_neutral"] == 1.0


def test_quaternary_ammonium_is_permanently_charged():
    """v4.22（run7 逼出）：Berberine 芳环季铵 [n+] formal charge=+1，
    此前被判 neutral_no_group/net_charge=0——季铵与 pH 无关，必须单独归类。"""
    p = IZ.ionization_profile(
        "COc1ccc2cc3[n+](cc2c1OC)CCc1cc2c(cc1-3)OCO2")  # berberine 骨架
    assert p["available"] is True
    assert p["charge_class"] == "permanently_charged"
    assert p["net_charge"] == 1.0
    assert p["f_neutral"] == 0.0


def test_truly_neutral_no_formal_charge_stays_neutral():
    """无 formal charge 且无可电离基团 → 仍是 neutral_no_group（回归守卫）。"""
    p = IZ.ionization_profile("c1ccc2ccccc2c1")  # 萘
    assert p["charge_class"] == "neutral_no_group"
    assert p["net_charge"] == 0.0


def test_zwitterion_flagged():
    """甘氨酸是两性离子：同时有 COOH 与 NH2。"""
    p = IZ.ionization_profile("NCC(=O)O")
    assert p["zwitterion"] is True
    assert p["n_acid"] == 1 and p["n_base"] == 1


def test_bad_smiles_graceful():
    p = IZ.ionization_profile("not_a_smiles")
    assert p["available"] is False
    assert "不可解析" in IZ.render(p, "x")


def test_logd_shift_negative_and_bracketed():
    """logD ≤ logP 恒成立（电离只会降低分配），且区间必须包住点值。"""
    p = IZ.ionization_profile("OC(=O)/C=C/c1ccc(O)c(O)c1")     # caffeic acid
    ld = IZ.logd_from_logp(1.5, p)
    assert ld["logD"] <= 1.5
    lo, hi = ld["logD_range"]
    assert lo <= ld["logD"] <= hi


def test_pka_grade_is_category_level():
    """pKa 证据等级必须固定为类别级——防止下游把它当实测值。"""
    p = IZ.ionization_profile("CC(=O)O")
    assert p["pka_grade"] == "literature_category_range"
    assert "禁止" in p["limits"]


# ---------------------------------------------------------------- 心脏三联
def _ch(ic50=None, inh=None):
    d = {}
    if ic50 is not None:
        d["ic50_uM"] = ic50
    if inh is not None:
        d["inh_pct"] = inh
    return d


def test_herg_only_cannot_clear():
    """只有 hERG 且为 LOW 时，verdict 必须带 herg_only，allowed 必须写明"不能排除"。"""
    r = CP.assess_compound("X", {"herg": _ch(ic50=50.0)}, cmax_uM=0.1)
    assert r["panel_verdict"] == "herg_only_low"
    assert "不能" in r["allowed_statement"]
    assert r["missing_channels"] == "cav12;nav15"
    assert r["net_effect"] == "not_estimated"


def test_three_channel_worst_drives_verdict():
    """三通道齐备时取最差档；已知 hERG 阻断剂 Terfenadine 应判 high。"""
    r = CP.assess_compound(
        "Terfenadine",
        {"herg": _ch(ic50=0.06), "cav12": _ch(ic50=8.0), "nav15": _ch(ic50=6.0)},
        cmax_uM=0.097)
    assert r["n_channels"] == 3
    assert r["worst_tier"] == "HIGH"
    assert r["panel_verdict"] == "panel_high"


def test_no_data_undetermined():
    r = CP.assess_compound("Y", {}, cmax_uM=1.0)
    assert r["panel_verdict"] == "undetermined_no_channel_data"
    assert r["n_channels"] == 0


def test_inhibition_only_path():
    """只有 %抑制、没有 IC50 时也必须能分档（margin 留空，不伪造）。"""
    r = CP.assess_compound("Z", {"herg": _ch(inh=45.0)}, cmax_uM=0.4)
    assert r["herg_tier"] == "INTERMEDIATE"
    assert r["herg_margin"] == ""


# ---------------------------------------------------------------- PK/PD
_T = [0.0, 0.5, 1.0, 2.0, 4.0, 8.0, 12.0, 24.0]
_C = [0.0, 0.6, 1.0, 0.8, 0.5, 0.2, 0.05, 0.0]


def test_ft_above_matches_analytic_expectation():
    """阈值 0.5、C 曲线在 0.5 到 4.0 之间都 ≥0.5 → 时长应约为 3.5 h。"""
    m = PD.pd_metrics(_T, _C, ec50=0.5, emax=100.0, n=1.0, interval_h=12.0)
    assert 3.0 <= m["t_above_ec50_h"] <= 4.0
    assert 0.2 <= m["frac_interval_above_ec50"] <= 0.35
    assert m["status"] == "ok"


def test_pd_requires_points():
    with pytest.raises(PD.PDParameterError):
        PD.pd_metrics([0.0, 1.0], [0.0, 1.0], ec50=0.5, emax=100.0)


def test_ec50_must_be_positive():
    with pytest.raises(PD.PDParameterError):
        PD.hill([1.0], ec50=0.0, emax=1.0)


def test_unit_conversion_requires_mw():
    with pytest.raises(PD.PDParameterError):
        PD.c_mg_per_L_to_uM([1.0], mw=None)
    out = PD.c_mg_per_L_to_uM([1.0], mw=100.0)     # 1 mg/L, MW 100 -> 10 µM
    assert abs(float(out[0]) - 10.0) < 1e-9


def test_effect_compartment_shifts_peak_later():
    """ke0 有限时效应室峰值不应早于血药峰值。"""
    ce = PD.effect_compartment(_T, _C, ke0=0.5)
    i_c = max(range(len(_C)), key=lambda i: _C[i])
    i_ce = max(range(len(ce)), key=lambda i: ce[i])
    assert i_ce >= i_c


def test_tmdd_refuses_without_params():
    """TMDD 缺参数必须报错——绝不能用默认值凑出一条占用率曲线。"""
    with pytest.raises(PD.PDParameterError) as e:
        PD.tmdd_minimal(_T, _C, r0_nM=0, kon_per_nM_per_h=0.1, koff_per_h=0.1,
                        kint_per_h=0.1, kdeg_per_h=0.1)
    assert "不许用默认值" in str(e.value)


# ---------------------------------------------------------------- PBPK 资格
def _pairs(fold_list, n_tp=6):
    out, i = [], 0
    for cid, folds in fold_list.items():
        for j, f in enumerate(folds * n_tp):
            out.append(dict(compound_id=cid, time_h=float(j),
                            obs=1.0, pred=float(f), unit="mg/L"))
            i += 1
    return out


def test_qualify_pass_path():
    res = PQ.qualify(_pairs({"a": [1.1], "b": [0.9], "c": [1.3]}))
    assert res["verdict"] == "qualified_conventional"
    assert res["aafe"] <= 2.0


def test_qualify_rejects_single_timepoint():
    """只对 Cmax 的比对不构成资格认定——必须显式拒绝（n 够但时点不够）。"""
    res = PQ.qualify(_pairs({"a": [1.1], "b": [1.0], "c": [0.9],
                             "d": [1.2], "e": [0.8]}, n_tp=1))
    assert res["verdict"] == "insufficient_timepoints"
    assert "不构成" in res["reason"]


def test_qualify_rejects_too_few_pairs():
    res = PQ.qualify(_pairs({"a": [1.1]}, n_tp=2))
    assert res["verdict"] == "insufficient_n"


def test_qualify_rejects_mixed_units():
    p = _pairs({"a": [1.0]})
    p[0]["unit"] = "uM"
    with pytest.raises(PQ.QualificationError):
        PQ.qualify(p)


def test_qualify_fails_on_big_bias():
    res = PQ.qualify(_pairs({"a": [5.0], "b": [0.2]}))
    assert res["verdict"] == "not_qualified"


# ---------------------------------------------------------------- interop
def test_pk_sim_export_reports_missing():
    rows, meta = IO.pk_sim_compounds(
        {"x": dict(mw=300.0, clogp=2.0)},
        pka_by_cid={"x": [4.5]}, ion_class_by_cid={"x": "acid"})
    assert rows[0]["pka_values"] == "4.50"
    assert rows[0]["ionization_class"] == "acid"
    # v4.21：claim 从"布尔 False"改成三级分级；但"ID=化合物不是个体"必须留在提示里
    assert "notice" in meta
    assert "分级" in meta["notice"] and "仿真层未闭环" in meta["notice"]
    assert "eta 不是 IIV" in meta["notice"]
    # 没有来源字段的 PK-Sim 参数必须显式列出
    assert meta["fields_without_source"]


def test_nonmem_contract_validation():
    rows = IO.nonmem_dataset([
        dict(id="a", time=0.0, amt=100, dv="", cmt=1),
        dict(id="a", time=1.0, dv=0.5),
    ])
    assert IO.validate_nonmem(rows) == []
    bad = IO.nonmem_dataset([dict(id="b", time=1.0, dv="", mdv=0)])
    assert any("MDV" in p for p in IO.validate_nonmem(bad))


def test_nonmem_time_must_be_sorted():
    rows = IO.nonmem_dataset([
        dict(id="a", time=0.0, amt=100, dv=""),
        dict(id="a", time=2.0, dv=0.2),
        dict(id="a", time=1.0, dv=0.4),
    ])
    assert any("未排序" in p for p in IO.validate_nonmem(rows))


def test_nlmixr2_skeleton_marks_measured_status():
    """v4.21：骨架不再是 template_only —— nlmixr2 已真跑通，标注改为实测结论。"""
    s = IO.nlmixr2_skeleton()
    assert "nlmixr2_fit_passed" in s
    assert "template_only" not in s
    # 但必须带上实测暴露的两个前提，否则会被当成常规 popPK 使用
    assert "化合物" in s and "不得当作 IIV" in s
    assert "不可辨识" in s


def test_nonmem_obs_cmt_separated_from_dose():
    """口服布局：给药进 CMT=1（胃肠道），观测进 CMT=2（中央室）。"""
    rows = IO.nonmem_dataset([
        dict(id="a", time=0.0, amt=100, dv="", cmt=1),
        dict(id="a", time=1.0, dv=0.5),
    ], obs_cmt=2)
    cmts = {(r["EVID"], r["CMT"]) for r in rows}
    assert cmts == {(1, 1), (0, 2)}
    assert IO.cmt_split_ok(rows) is True


def test_nonmem_cmt_split_guard_fires_on_shared_compartment():
    """成对断言：同腔必须在 expect_cmt_split 下被拒；给了 obs_cmt 就通过。"""
    shared = IO.nonmem_dataset([
        dict(id="a", time=0.0, amt=100, dv="", cmt=1),
        dict(id="a", time=1.0, dv=0.5),
    ])                                     # 默认 obs_cmt=None -> 同腔
    assert IO.cmt_split_ok(shared) is False
    assert IO.validate_nonmem(shared) == []          # 不声明口服时不该误报
    probs = IO.validate_nonmem(shared, expect_cmt_split=True)
    assert len(probs) == 1 and "未分离" in probs[0]

    split = IO.nonmem_dataset([
        dict(id="a", time=0.0, amt=100, dv="", cmt=1),
        dict(id="a", time=1.0, dv=0.5),
    ], obs_cmt=2)
    assert IO.validate_nonmem(split, expect_cmt_split=True) == []


# ---------------------------------------------------------------- 菌群
def _fake_bt_response():
    return {"predictions": [{
        "identifier": "apap",
        "biotransformations": [{
            "biosystem": "Gut microbial environment",
            "reaction_type": "Decarboxylation of aromatic L-amino acid",
            "metabolic_enzymes": ["SULFOTRANSFERASE"],
            "substrates": [{"smiles": "CC(=O)NC1=CC=C(O)C=C1"}],
            "products": [{"smiles": "CC(=O)NC1=CC=C(OC2OC(C(O)C(O)C2O)C(O)=O)C=C1",
                          "inchikey": "IPROLSVTVHAQLE-UHFFFAOYSA-N",
                          "title": "p-acetamidophenylglucuronide"}],
        }]}]}


def test_parse_and_filter_biosystem():
    rows = GM.parse_response(_fake_bt_response())
    assert len(rows) == 1
    assert GM.filter_biosystem(rows, "gut")
    assert not GM.filter_biosystem(rows, "environmental")  # 该条是 gut，不是 env


def test_reaction_label_inconsistent_detected():
    """实测已知缺陷：葡糖醛酸化被标成脱羧 → 质量差 +176 Da 与"丢 CO2"矛盾。

    这是本模块最重要的一个断言：它证明"reaction_type 不可信"不是猜测，是可复现的。
    """
    chk = GM.reaction_label_check("CC(=O)NC1=CC=C(O)C=C1",
                                  "CC(=O)NC1=CC=C(OC2OC(C(O)C(O)C2O)C(O)=O)C=C1",
                                  "Decarboxylation of aromatic L-amino acid")
    assert chk["status"] == "inconsistent"
    assert chk["delta_mass"] > 100


def test_reaction_label_consistent_case():
    chk = GM.reaction_label_check("Oc1ccccc1", "Oc1ccc(O)cc1",
                                  "Hydroxylation of aromatic ring")
    assert chk["status"] == "consistent"


def test_unknown_reaction_not_judged():
    chk = GM.reaction_label_check("CC(=O)O", "CC(=O)OC", "Acylation")
    assert chk["status"] in ("unknown", "consistent")


def test_invalid_option_rejected():
    with pytest.raises(ValueError):
        GM.run_gut([], option="NOT_AN_OPTION")


# ---------------------------------------------------------------- readback
def _write(tmpdir, name, text):
    p = os.path.join(str(tmpdir), name)
    with io.open(p, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    return p


def test_readback_maps_and_reports_unmapped(tmp_path):
    comp = _write(tmp_path, "compounds.csv",
                  "compound_id,input_smiles,calc_smiles,inchikey\n"
                  "T,CC(C)(C)c1ccc(C(O)CCCN2CCC(C(O)(c3ccccc3)c3ccccc3)CC2)cc1,"
                  "CC(C)(C)c1ccc(C(O)CCCN2CCC(C(O)(c3ccccc3)c3ccccc3)CC2)cc1,\n")
    src = _write(tmp_path, "sw.csv",
                 "Molecule name,SMILES,GI absorption,Pgp substrate,WeirdCol\n"
                 "T,CC(C)(C)c1ccc(C(O)CCCN2CCC(C(O)(c3ccccc3)c3ccccc3)CC2)cc1,High,Yes,x\n")
    from adt.cli import load_compounds_csv
    rows, rep = RB.ingest("swissadme", src, compounds=load_compounds_csv(comp))
    assert rep["structure_checked"] is True
    assert rep["n_unmatched"] == 0
    assert rep["unmapped_columns"] == ["WeirdCol"]
    vals = {r["endpoint"]: r["value"] for r in rows}
    assert vals["hia_absorption"] == 1
    assert vals["pgp_substrate"] == 1


def test_readback_drops_unmatched_silently_is_forbidden(tmp_path):
    """结构对不上必须进 unmatched 报表，不能硬配、也不能静默丢。"""
    comp = _write(tmp_path, "compounds.csv",
                  "compound_id,input_smiles,calc_smiles,inchikey\n"
                  "T,c1ccccc1,c1ccccc1,\n")
    src = _write(tmp_path, "sw.csv",
                 "SMILES,Pgp substrate\nCCCCCCCC(=O)O,No\n")
    from adt.cli import load_compounds_csv
    rows, rep = RB.ingest("swissadme", src, compounds=load_compounds_csv(comp))
    assert rows == []
    assert rep["n_unmatched"] == 1


def test_readback_override_allows_unmapped_source(tmp_path):
    src = _write(tmp_path, "a.csv", "SMILES,hERG,pIC50\nc1ccccc1,0.2,6.7\n")
    rows, rep = RB.ingest("aoamp", src,
                          col_map_override={"hERG": dict(id="herg", unit="probability")})
    assert rows and rows[0]["endpoint"] == "herg"
    assert "pIC50" in rep["unmapped_columns"]


def test_readback_measured_without_provenance_downgrades(tmp_path):
    src = _write(tmp_path, "a.csv", "SMILES,Pgp substrate\nc1ccccc1,Yes\n")
    rows, _ = RB.ingest("swissadme", src, domain_flag="measured")
    assert rows[0]["domain_flag"] == "manual"
    assert "降级" in rows[0]["note"]


def test_readback_unknown_source_needs_map(tmp_path):
    src = _write(tmp_path, "a.csv", "SMILES,x\nc1ccccc1,1\n")
    with pytest.raises(ValueError):
        RB.ingest("totally_new_tool", src)


@pytest.mark.parametrize("bad_flag", ["out_of_domain", "saturated", "error"])
def test_readback_rejects_trust_root_flags(tmp_path, bad_flag):
    """C2 信任根：回填通道不得自行声明 out_of_domain/saturated/error。

    这三个取值改变的是"可判性"与"是否入票"——若允许回填表（或 schema）声明，
    任何人只要在 CSV 里写一列就能把分子踢出裁决。只能由
    reliability.apply_class_blocks 与饱和扫描产生。
    """
    src = _write(tmp_path, "a.csv", "SMILES,Pgp substrate\nc1ccccc1,Yes\n")
    with pytest.raises(ValueError) as ei:
        RB.ingest("swissadme", src, domain_flag=bad_flag)
    assert "BACKFILL" in str(ei.value) or "只允许" in str(ei.value)


def test_readback_allowed_flags_are_exactly_three():
    """成对断言：白名单就是三个；多一个都不行（防止日后"顺手加一个"）。"""
    assert set(RB.BACKFILL_FLAGS) == {"predicted", "measured", "manual"}
    from adt.schema import DOMAIN_FLAGS
    assert set(RB.BACKFILL_FLAGS) <= set(DOMAIN_FLAGS)


def test_microbe_db_ingest_marks_non_voting(tmp_path):
    """MicrobeTCM 回填必须标 database_annotation + predictive_value=none（不许投票）。"""
    src = _write(tmp_path, "m.csv",
                 "compound_id,microbe,interaction,metabolite_smiles,evidence,doi\n"
                 "Q,Eubacterium ramulus,ring fission,,LC-MS,10.1/x\n")
    recs, problems = GM.ingest_microbe_db(src, source="microbetcm")
    assert problems == []
    assert recs[0]["evidence_level"] == "database_annotation"
    assert recs[0]["predictive_value"] == "none"


def test_microbe_db_requires_identifier(tmp_path):
    src = _write(tmp_path, "m.csv", "compound_id,microbe\n,x\n")
    recs, problems = GM.ingest_microbe_db(src)
    assert recs == [] and problems


# ---------------------------------------------------------------- CLI 接线
def test_cli_subcommands_registered():
    """7 个新子命令必须都有 --help（argparse 的 % 崩溃只在这里暴露）。"""
    from adt import cli
    import subprocess
    for cmd in ["pka", "cardiac", "pd", "pbpk-qualify", "interop",
                "gut-micro", "readback"]:
        r = subprocess.run([sys.executable, "-m", "adt.cli", cmd, "--help"],
                           cwd=HERE, capture_output=True, text=True)
        assert r.returncode == 0, "%s --help 失败：%s" % (cmd, r.stderr[-400:])
