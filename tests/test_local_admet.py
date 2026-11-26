# -*- coding: utf-8 -*-
"""local_admet（离线 6 工具）回归测试。

验证：6 个工具都能跑、都带 rule-based-local-proxy 标记；描述符与 RDKit 一致；
pKa/Ames 关键判据正确；长表列符合 measurements.csv 契约；未知工具报错。
"""
import csv
import io
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from local_admet import TOOL_NAMES, run_tool, normalize_tool  # noqa: E402
from local_admet.cli import main as cli_main  # noqa: E402


MOLS = {
    "aspirin": "CC(=O)Oc1ccccc1C(=O)O",
    "caffeine": "Cn1cnc2c1c(=O)n(C)c(=O)n2C",
    "imidazole": "c1cnc[nH]1",
    "aniline": "Nc1ccccc1",
}


def test_all_six_tools_run_and_are_labelled():
    for tool in TOOL_NAMES:
        for cid, smi in MOLS.items():
            r = run_tool(tool, smi)
            assert r["tool"] == tool
            assert r["method"] == "rule-based-local-proxy"
            assert r["warning"]


def test_descriptors_match_rdkit():
    from rdkit import Chem
    from rdkit.Chem import Descriptors
    smi = MOLS["aspirin"]
    r = run_tool("Molecular Descriptors", smi)
    assert abs(r["MW"] - Descriptors.MolWt(Chem.MolFromSmiles(smi))) < 1e-6
    assert r["formula"] == "C9H8O4"


def test_pka_imidazole():
    r = run_tool("Graph-pKa", MOLS["imidazole"])
    assert r["n_ionizable_groups"] >= 1
    assert any(abs(g["pKa_estimate"] - 6.0) < 0.01 for g in r["ionizable_groups"])


def test_ames_alert_nitrobenzene():
    r = run_tool("ADMET Predictor", "[O-][N+](=O)c1ccccc1", features="T")
    assert r["endpoints"]["ames_mutagenicity"]["category"] == "alert_positive"


def test_alias_and_unknown():
    assert normalize_tool("predictor") == "ADMET Predictor"
    assert normalize_tool("pka") == "Graph-pKa"
    with pytest.raises(ValueError):
        normalize_tool("no-such-tool")


def test_long_table_contract(tmp_path):
    out = tmp_path / "d.csv"
    rc = cli_main(["--tool", "Molecular Descriptors", "--smiles", MOLS["aspirin"],
                   "--format", "long", "--out", str(out)])
    assert rc == 0
    rows = list(csv.DictReader(io.open(str(out), encoding="utf-8")))
    assert rows
    assert rows[0]["source"] == "local_admet"
    assert rows[0]["domain_flag"] == "predicted"
    required = {"compound_id", "endpoint", "value", "unit", "source", "source_version",
                "retrieved_at", "domain_flag", "uncertainty", "provenance_url", "note"}
    assert required.issubset(set(rows[0].keys()))


def test_selftest_exit0():
    assert cli_main(["--selftest"]) == 0
