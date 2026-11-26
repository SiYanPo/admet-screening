# -*- coding: utf-8 -*-
"""零/弱引用模块与主 CLI 入口的可用性回归。

盘点发现 `paired_stats` / `saturation` / `tdc_local` 三个模块在 tests/ 里
没有直接引用（前两个被 mmp.py / abstain_attrib.py 间接调用，tdc_local 是
备用回落模块）。「补齐」不等于把它们硬塞进主链路：先证明它们**确实可用**，
并把 tdc_local 的定位写清楚，避免下一个人误以为它已接入生产。
"""
import io
import json
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_tdc_local_csv_fallback(tmp_path):
    """tdc 包不可用时，可从本地缓存 CSV 读取切分（模块 docstring 的主用途）。"""
    from adt import tdc_local as T
    name = "Caco2_Wang"
    d = T.dataset_dir(str(tmp_path), name)
    os.makedirs(d, exist_ok=True)
    io.open(os.path.join(d, "train_val.csv"), "w", encoding="utf-8").write(
        "Drug,Y\nCCO,0.1\nc1ccccc1,0.9\nCC(=O)O,0.4\n")
    io.open(os.path.join(d, "test.csv"), "w", encoding="utf-8").write(
        "Drug,Y\nCN1C=NC2=C1C(=O)N(C)C(=O)N2C,0.7\n")
    assert T.is_available(str(tmp_path), name) is True
    split = T.load_split(str(tmp_path), name)
    assert set(split) == {"train_val", "test"}
    assert set(split["train_val"].columns) >= {"Drug", "Y"}
    assert len(split["train_val"]) == 3 and len(split["test"]) == 1


def test_tdc_local_fails_loud_on_missing_or_bad_columns(tmp_path):
    from adt import tdc_local as T
    assert T.is_available(str(tmp_path), "never_cached") is False
    with pytest.raises(FileNotFoundError):
        T.load_split(str(tmp_path), "never_cached")
    d = T.dataset_dir(str(tmp_path), "bad")
    os.makedirs(d, exist_ok=True)
    io.open(os.path.join(d, "train_val.csv"), "w", encoding="utf-8").write("SMILES,label\na,1\n")
    io.open(os.path.join(d, "test.csv"), "w", encoding="utf-8").write("Drug,Y\na,1\n")
    with pytest.raises(ValueError, match="缺少列"):
        T.load_split(str(tmp_path), "bad")


def test_paired_stats_basic_invariants():
    from adt import paired_stats as P
    # Holm：全小 p 全拒；极小/极大混合时_step-down 生效
    assert P.holm([0.001, 0.002, 0.003]) == [True, True, True]
    assert P.holm([0.001, 0.04, 0.9]) == [True, False, False]
    assert P.sign_z_continuous(10, 10) > 0
    assert P.sign_z_continuous(0, 10) < 0
    # post-hoc 等效界不得允许推断（B4 半真修复的核心守卫）
    r = P.paired_tost([0.0] * 12, margin=0.05, margin_preregistered=False)
    assert r["equivalent"] is True
    assert r["inferential_use_allowed"] is False
    assert any("post-hoc" in w for w in r["warnings"])


def test_saturation_scan_classifies_saturated_and_usable():
    from adt import saturation as S
    rows = [{"id": str(i), "score_a": v, "const_flag": 1.0}
            for i, v in enumerate([0.1, 0.9, 0.2, 0.8, 0.3, 0.7])]
    diag = []
    recs = S.scan(rows, diag=diag)
    by_ep = {r["endpoint"]: r for r in recs}
    assert by_ep["const_flag"]["verdict"] == "saturated_in_set"
    assert by_ep["score_a"]["verdict"] == "usable"
    assert "const_flag" in S.non_ranking_endpoints(recs)
    assert S.blocked_endpoints(recs) == set()
    # C57：少于 3 个数值的列必须进 diag，而不是静默跳过
    rows2 = [{"id": "a", "sparse": 1}, {"id": "b", "sparse": 2},
             {"id": "c", "sparse": 3}, {"id": "d", "sparse": 4}]
    diag2 = []
    S.scan(rows2, diag=diag2, cols=["tiny"])
    assert diag2 and diag2[0]["endpoint"] == "tiny"


def test_local_tools_main_cli_entrypoint():
    """6 个离线工具必须能从 adt.cli 主入口调用（此前只有独立子包）。"""
    env = dict(os.environ)
    r = subprocess.run([sys.executable, "-m", "adt.cli", "local-tools",
                        "--list-tools"],
                       cwd=HERE, capture_output=True, text=True,
                       encoding="utf-8", timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    payload = json.loads(r.stdout[r.stdout.index("{"):])
    assert len(payload["tools"]) == 6
    assert "Molecular Descriptors" in payload["tools"]

    r2 = subprocess.run([sys.executable, "-m", "adt.cli", "local-tools",
                         "--tool", "Molecular Descriptors",
                         "--smiles", "CC(=O)Oc1ccccc1C(=O)O"],
                        cwd=HERE, capture_output=True, text=True,
                        encoding="utf-8", timeout=120)
    assert r2.returncode == 0, r2.stdout + r2.stderr
    d = json.loads(r2.stdout[r2.stdout.index("{"):])
    assert abs(d["MW"] - 180.16) < 0.05
    assert d["HBD"] == 1


def test_local_tools_long_table_deterministic(tmp_path):
    """--deterministic 让筛查层长表也能逐字节复现。"""
    import csv
    import hashlib
    outs = []
    for i in (1, 2):
        p = tmp_path / ("d%d.csv" % i)
        r = subprocess.run([sys.executable, "-m", "adt.cli", "local-tools",
                            "--tool", "DeepEsol", "--smiles", "CCO",
                            "--format", "long", "--deterministic", "--out", str(p)],
                           cwd=HERE, capture_output=True, text=True,
                           encoding="utf-8", timeout=120)
        assert r.returncode == 0, r.stdout + r.stderr
        outs.append(p)
    assert (hashlib.sha256(outs[0].read_bytes()).hexdigest()
            == hashlib.sha256(outs[1].read_bytes()).hexdigest())
    rows = list(csv.DictReader(io.open(str(outs[0]), encoding="utf-8")))
    assert rows and all(r["retrieved_at"] == "DETERMINISTIC" for r in rows)
