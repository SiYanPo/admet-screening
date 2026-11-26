# -*- coding: utf-8 -*-
"""真值驱动实跑（2026-11-19）暴露的缺陷回归。

这批缺陷的共同点：**单元测试造不出来**，只有在真实数据上跑一遍才会露出来。
测试按"用户会怎么用"写断言，不按内部函数名写。
"""
import csv
import io
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from adt import benchmark as BM          # noqa: E402
from adt import pred_displacement as PD  # noqa: E402


# --------------------------------------------------------------- R1 方向定向
def _two_class_rows(values, labels, endpoint):
    """构造预测长表 + 真值长表（值是"端点原生量纲"，不是风险分数）。"""
    preds, truth = [], []
    for i, (v, y) in enumerate(zip(values, labels)):
        cid = "C%03d" % i
        preds.append(dict(compound_id=cid, endpoint=endpoint, value=str(v),
                          unit="u", source="s", domain_flag="predicted"))
        truth.append(dict(compound_id=cid, endpoint=endpoint, truth_value=str(v),
                          truth_class="FAIL" if y == 1 else "PASS"))
    return preds, truth


def test_down_endpoint_uses_raw_value():
    """shape=down（越小越好，例如 hERG IC50 越低越毒）：风险 = 原值。

    真实数据上的后果（OpenADMET 9 端点）：若按"越大越坏"打分，
    caco2_efflux / mppb / mbpb / mgmb / ksol 5 个端点的 AUROC 会整体翻反
    （mppb 0.918 → 0.082），使用者会读成"模型无效"。
    """
    rule = dict(shape="down", **{"pass": 30.0, "fail": 30.0})
    # shape=down 的语义是「越小越好」（_judge: value<=pass → PASS），
    # 所以值**高**才是 FAIL。这条一开始写反过——正好说明方向语义有多容易搞错。
    vals = [5.0, 10.0, 20.0, 40.0, 60.0, 80.0]
    labels = [0, 0, 0, 1, 1, 1]
    preds, truth = _two_class_rows(vals, labels, "herg_ic50")
    rows, _ = BM.build(preds, truth, {"herg_ic50": rule}, B=50, seed=0)
    r = rows[0]
    assert r["score_orient"] == "raw(shape=down: smaller_is_better)", r
    assert r["auroc"] == 1.0, r          # 方向对了才是完美排序


def test_up_endpoint_negated():
    """shape=up（越大越好，例如溶解度 ksOL）：风险 = -原值。"""
    rule = dict(shape="up", **{"pass": 10.0, "fail": 10.0})
    vals = [1.0, 2.0, 3.0, 50.0, 60.0, 70.0]   # 低溶解度 = FAIL
    labels = [1, 1, 1, 0, 0, 0]
    preds, truth = _two_class_rows(vals, labels, "ksol")
    rows, _ = BM.build(preds, truth, {"ksol": rule}, B=50, seed=0)
    r = rows[0]
    assert r["score_orient"] == "negated(shape=up: larger_is_better)", r
    assert r["auroc"] == 1.0, r


def test_window_endpoint_uses_distance_outside():
    """shape=window（如 logD 0–4）：非单调端点，用"出窗距离"，且必须自陈。"""
    rule = dict(shape="window", window=[0.0, 4.0])
    vals = [-2.0, -1.0, 2.0, 3.0, 6.0, 8.0]
    labels = [1, 1, 0, 0, 1, 1]
    preds, truth = _two_class_rows(vals, labels, "logd")
    rows, _ = BM.build(preds, truth, {"logd": rule}, B=50, seed=0)
    r = rows[0]
    assert r["score_orient"] == "distance_outside_window", r
    assert "不可与方向型端点的 AUROC 直接比大小" in (r["note"] or ""), r["note"]


def test_no_rules_marked_as_assumption():
    """不给规则时必须写出"按数值越大越坏打分，方向可能反了"，不能静默。"""
    vals = [5.0, 10.0, 20.0, 40.0]
    labels = [1, 1, 0, 0]
    preds, truth = _two_class_rows(vals, labels, "unknown_ep")
    rows, _ = BM.build(preds, truth, {}, B=50, seed=0)
    r = rows[0]
    assert r["score_orient"] == "raw_assumed_higher_is_risk", r
    assert "--rules 可修正" in (r["note"] or ""), r["note"]


# --------------------------------------------------------------- R2 no-op 变体
def _vrows(rows):
    """写临时变体长表。"""
    import tempfile
    fd, p = tempfile.mkstemp(suffix=".csv")
    os.close(fd)
    with io.open(p, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["compound_id", "variant", "endpoint",
                                           "value", "noop"])
        w.writeheader()
        w.writerows(rows)
    return p


def test_noop_variant_is_excluded_not_zero():
    """noop=Y 的变体（SMILES 与母体完全相同）必须被排除，不能算成"位移=0"。

    真实事故：ac-plan 的 tautomer 变体在 6/6 个面板分子上与母体相同，
    pred-shift 于是报"位移 0.000 / 比值 0.00"，再解释成"结构扰动影响小于源间分歧"——
    一个**空转的变体集**变成了科学结论。
    """
    rows = [
        dict(compound_id="A", variant="original", endpoint="logP", value="1.0", noop="N"),
        dict(compound_id="A", variant="tautomer", endpoint="logP", value="1.0", noop="Y"),
        dict(compound_id="A", variant="real_shift", endpoint="logP", value="1.5", noop="N"),
    ]
    p = _vrows(rows)
    loaded = PD.load_long(p)
    disp = PD.displacement(loaded)
    by = {d["variant"]: d for d in disp}
    assert by["tautomer"]["n"] == 0 and by["tautomer"]["n_noop"] == 1, by["tautomer"]
    assert by["tautomer"]["noop_all"] is True
    assert by["real_shift"]["n"] == 1 and by["real_shift"]["mean_abs_shift"] == 0.5
    # 全部 no-op 时，verdict 必须拒绝下"结构不敏感"的结论
    only_noop = PD.displacement(PD.load_long(_vrows(rows[:2])))
    msg = PD.verdict(PD.compare(only_noop, {"logP": dict(mean_abs_diff=0.6)}))
    assert "没有可解释的位移" in msg and "变体没生成" in msg, msg
    os.unlink(p)


# --------------------------------------------------------------- R3 互变体生成
def test_tautomer_variant_actually_differs():
    """tautomer 变体必须真的换一个互变体，不能把"规范态=原分子"当变体交差。"""
    from rdkit import Chem
    from adt import perturbation as PB
    for name, smi in [("APAP", "CC(=O)Nc1ccc(O)cc1"),
                      ("quercetin", "O=c1c(O)c(-c2ccc(O)c(O)c2)oc2cc(O)cc(O)c12"),
                      ("phenol", "Oc1ccccc1")]:
        v = PB.variants(smi)
        assert v["tautomer"][0] and v["tautomer"][0] != Chem.MolToSmiles(Chem.MolFromSmiles(smi)), \
            "%s 的 tautomer 变体与母体相同（no-op）" % name


# --------------------------------------------------------------- R4 立体盲区
def test_stereo_enumeration_gives_zero_delta():
    """华法林 R/S 在 2D 预测栈上必须完全一致（证明是结构性失明，不是精度问题）。"""
    from rdkit import Chem
    from rdkit.Chem.EnumerateStereoisomers import (EnumerateStereoisomers,
                                                   StereoEnumerationOptions)
    from rdkit.Chem import Crippen, Descriptors
    smi = "CC(=O)CC(c1ccccc1)c1c(O)c2ccccc2oc1=O"
    m = Chem.MolFromSmiles(smi)
    isos = list(EnumerateStereoisomers(
        m, options=StereoEnumerationOptions(onlyUnassigned=True, unique=True)))
    assert len(isos) == 2, len(isos)
    vals = [(Crippen.MolLogP(x), Descriptors.TPSA(x)) for x in isos]
    assert abs(vals[0][0] - vals[1][0]) < 1e-9, vals
    assert abs(vals[0][1] - vals[1][1]) < 1e-9, vals


# --------------------------------------------------------------- R5 本地引擎
def test_sygma_engine_when_available():
    """SyGMa 可用时必须真出产物；不可用则跳过（不静默假装跑过）。"""
    pytest = __import__("pytest")
    pytest.importorskip("sygma")
    from adt.adapters.sygma_local import SyGMaAdapter
    ad = SyGMaAdapter(verbose=False, cycles=1, top=10)
    if not ad.preflight():
        __import__("pytest").skip("sygma 规则文件缺失")
    res = ad.run([dict(compound_id="APAP",
                       calc_smiles="CC(=O)Nc1ccc(O)cc1")])
    assert res.metabolites, "SyGMa 对 APAP 应给出至少一个产物"
    assert all(m["source"] == "sygma_local" for m in res.metabolites)
    assert all(m["biosystem"] == "human" for m in res.metabolites)
    # 截断必须自陈：节点总数 vs 保留数
    pc = res.meta["per_compound"][0]
    assert pc["n_nodes_total"] >= pc["n_kept"] >= 1, pc


if __name__ == "__main__":
    import pytest as _p
    sys.exit(_p.main([__file__, "-v", "--no-header", "-p", "no:cacheprovider"]))
