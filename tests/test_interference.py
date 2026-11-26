# -*- coding: utf-8 -*-
"""离线结构干扰红旗层 / 源健康探针 / f_oral 口径 / 干扰措辞断言 回归测试。

重点钉住三件容易悄悄退化的事：
  ① catalog 来源归属（合并 catalog 会把 BRENK 命中误读成 PAINS 命中）；
  ② C87 教训（松 SMARTS 把愈创木基误判成邻苯二酚）；
  ③ 红旗层不是一票、不淘汰分子（糖苷天然违规不得判 FAIL）。
"""
import csv
import hashlib
import io
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from adt import interference as IF                       # noqa: E402
from adt import source_health as SH                      # noqa: E402
from adt import endpoints as E                           # noqa: E402
from adt import claims_audit as CA                       # noqa: E402

CURCUMIN = "COc1cc(/C=C/C(=O)CC(=O)/C=C/c2ccc(O)c(OC)c2)ccc1O"
CAFFEIC = "O=C(O)/C=C/c1ccc(O)c(O)c1"
FERULIC = "COc1cc(/C=C/C(=O)O)ccc1O"
CAFFEINE = "Cn1cnc2c1c(=O)n(C)c(=O)n2C"
ASPIRIN = "CC(=O)Oc1ccccc1C(=O)O"
EGCG = ("Oc1cc(O)c2C[C@H](OC(=O)c3cc(O)c(O)c(O)c3)[C@H](Oc2c1)"
        "c4cc(O)c(O)c(O)c4")


def test_selftest_all_positive_negative_controls():
    rep = IF.selftest()
    assert rep["passed"], rep["failures"]
    assert rep["n_cases"] == 7


def test_catalog_attribution_not_merged():
    """BRENK 条目不得被当成 PAINS；真 PAINS 条目必须在 PAINS_B 命中。

    这条回归钉住 2026-11-11 实测发现的来源误读：把 5 个 catalog 合并后
    Michael_acceptor_1/catechol/beta-keto/anhydride 看起来像 PAINS 命中。
    """
    cur = IF.assess(CURCUMIN, "curcumin")
    by_desc = {h["description"]: h["catalog"] for h in cur["hits"]}
    assert by_desc["Michael_acceptor_1"] == "BRENK"
    assert by_desc["beta-keto/anhydride"] == "BRENK"
    assert not any(h["catalog"].startswith("PAINS") for h in cur["hits"])

    eg = IF.assess(EGCG, "EGCG")
    pains = [h for h in eg["hits"] if h["catalog"].startswith("PAINS")]
    assert pains and any("catechol_A(92)" in h["description"] for h in pains)
    sizes = IF.catalog_sizes()
    assert sizes == dict(PAINS_A=16, PAINS_B=55, PAINS_C=409,
                         BRENK=105, NIH=180)


def test_strong_vs_weak_tiers():
    assert IF.assess(CAFFEINE)["flag"] == IF.FLAG_NONE
    assert IF.assess(ASPIRIN)["flag"] == IF.FLAG_WEAK_ONLY
    assert IF.assess(CURCUMIN)["flag"] == IF.FLAG_SUSPECT
    assert IF.assess(EGCG)["flag"] == IF.FLAG_SUSPECT
    assert IF.assess(CURCUMIN)["gate_action"] == IF.ACTION_DOWNGRADE


def test_c87_catechol_vs_guaiacyl():
    """咖啡酸(真邻苯二酚)命中 catechol；阿魏酸(愈创木基)不命中且不折减结论。"""
    caf = IF.assess(CAFFEIC, "caffeic")
    fer = IF.assess(FERULIC, "ferulic")
    assert any("catechol" in h["description"] for h in caf["hits"])
    assert not any("catechol" in h["description"] for h in fer["hits"])
    assert caf["flag"] == IF.FLAG_SUSPECT          # PAINS_B catechol_A(92)
    assert fer["flag"] == IF.FLAG_WEAK_ONLY        # GRAS 不饱和酸子类
    assert fer["n_strong"] == 0


def test_invalid_smiles_is_rejected_not_silently_skipped():
    r = IF.assess("this-is-not-a-smiles", "bad")
    assert r["flag"] == IF.FLAG_INVALID
    assert r["gate_action"] == IF.ACTION_REJECT
    assert r["canonical_smiles"] == ""


def test_red_flag_layer_is_not_a_vote_and_never_rejects():
    for smi in (CURCUMIN, CAFFEINE, ASPIRIN):
        r = IF.assess(smi)
        assert r["not_a_vote"] is True
        assert r["flag"] != "FAIL"
        p = r.get("policy") or {}
        assert p.get("enters_reliab_vote") is False
        assert p.get("admissible_for_rejection") is False
        assert p.get("writes_measurements_long_table") is False
        assert r["druglikeness"]["admissible_for_rejection"] is False


def test_phrasing_cap_on_strong_flag():
    ph = IF.allowed_statement_for(IF.FLAG_SUSPECT)
    assert "未见毒性" in ph["forbidden"] and "已排除风险" in ph["forbidden"]
    # 姜黄素的强命中来自 BRENK，模板不得笼统写成「强 PAINS 结构警报」
    assert "强 PAINS 结构警报" not in ph["allowed"]
    assert "确认阳性" in IF.allowed_statement_for(IF.FLAG_WEAK_ONLY)["forbidden"]
    assert "已排除干扰" in IF.allowed_statement_for(IF.FLAG_NONE)["forbidden"]


def test_real_regalosides_are_weak_only_and_deterministic(tmp_path):
    """项目真实分子：不饱和酯 GRAS 子类，只单列需实验确认，不折减既有结论。"""
    src = os.path.join(ROOT, "out_wbh", "compounds.csv")
    if not os.path.isfile(src):
        pytest.skip("out_wbh/compounds.csv 不存在（换机环境）")
    out1, out2 = tmp_path / "a", tmp_path / "b"
    rows1, p1 = IF.assess_file(src, outdir=str(out1))
    rows2, p2 = IF.assess_file(src, outdir=str(out2))
    assert {r["compound_id"] for r in rows1} >= {"WBLG-A", "WBLG-B"}
    for r in rows1:
        assert r["flag"] == IF.FLAG_WEAK_ONLY
        assert r["n_strong"] == 0
        # 糖苷天然违规：Veber 不过，但绝不判 FAIL / 不淘汰
        assert r["druglikeness"]["veber_pass"] is False
        assert r["druglikeness"]["admissible_for_rejection"] is False
    for k in ("csv", "json"):
        h1 = hashlib.sha256(io.open(p1[k], "rb").read()).hexdigest()
        h2 = hashlib.sha256(io.open(p2[k], "rb").read()).hexdigest()
        assert h1 == h2, "%s 产物非确定性" % k
    with io.open(p1["csv"], encoding="utf-8-sig") as fh:
        rd = list(csv.DictReader(fh))
    assert list(rd[0]) == IF.CSV_COLS
    assert len(rd) == len(rows1) == len(rows2)


def test_endpoint_rules_f_oral_and_not_covered():
    import yaml
    p = os.path.join(ROOT, "references", "03_endpoint_rules.yaml")
    d = yaml.safe_load(io.open(p, encoding="utf-8"))
    eps = {e["id"]: e for e in d["endpoints"]}
    assert eps["f_oral"]["role"] == "reference"
    assert eps["f_oral"]["shape"] == "none"
    assert eps["f_oral"]["provenance_classes"] == [
        "assumption", "predicted_proxy", "measured"]
    assert "pass" not in eps["f_oral"] and "fail" not in eps["f_oral"]
    nc = {x["id"]: x for x in d["not_covered_endpoints"]}
    assert {"cyp_induction", "cyp_tdi", "colloidal_aggregation",
            "fluorescence_interference", "redox_cycling"} <= set(nc)
    assert nc["cyp_induction"]["status"] == "not_covered"
    # 新增端点不得引入未登记的规则冲突（4 条既有且全部 LEDGER）
    probs = E.validate_rule_direction()
    assert len(probs) == 4 and all(x.startswith("[LEDGER:") for x in probs)
    assert E.unacknowledged_rule_problems() == []


def test_version_divergence_ledger_is_current():
    from adt import version as V
    from adt import _version
    r = V.audit_version_sources()
    assert r["n_divergences"] == 6
    assert r["undeclared"] == [], r["undeclared"]
    # 2026-11-22：旧断言写死 4.25，材料已到 4.35；改为与单一源 _version 对齐，
    # 仍能抓住"CHANGELOG 与常量脱轨"，但不再因正常文档更新而假红。
    assert r["observed"]["CHANGELOG.md::latest"] == _version.DOC_REVISION.split()[0]
    assert V.main(["--strict"]) == 0


def test_source_health_policy_never_auto_updates():
    reg = SH.load_registry()
    assert {"pkcsm", "admetasar3", "swissadme", "biotransformer"} <= set(reg)
    assert reg["pkcsm"]["status"] == "dead"
    assert reg["admetasar3"]["status"] == "needs_probe"
    # 不联网也能验证策略字段：报告永远不由 GET 推断预测后端可用
    rep = SH.probe(names=[], timeout=1)
    assert rep["n_probed"] == 0 and rep["n_prediction_confirmed"] == 0
    assert rep["policy"]["auto_update_registry"] is False
    assert rep["policy"]["prediction_available_from_get"] is False
    assert rep["policy"]["submits_jobs"] is False


def test_interference_phrasing_audit_positive_negative(tmp_path):
    flags = tmp_path / "flags.csv"
    with io.open(str(flags), "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["compound_id", "flag"])
        w.writeheader()
        w.writerow({"compound_id": "curcumin", "flag": "suspect_interference"})
        w.writerow({"compound_id": "WBLG-A", "flag": "weak_only"})

    clean = tmp_path / "clean.txt"
    io.open(str(clean), "w", encoding="utf-8").write(
        "curcumin 的 hERG 预测值为 0.42，需实测确认。\n")
    assert CA.verify_interference_phrasing(str(flags), [str(clean)])["passed"]

    bad = tmp_path / "bad.txt"
    io.open(str(bad), "w", encoding="utf-8").write(
        "curcumin 未见毒性，可判定安全。\n")
    res = CA.verify_interference_phrasing(str(flags), [str(bad)])
    assert not res["passed"] and res["n_violations"] == 1
    assert res["violations"][0]["compound_id"] == "curcumin"

    marked = tmp_path / "marked.txt"
    io.open(str(marked), "w", encoding="utf-8").write(
        "curcumin 命中 PAINS 警报，需实验确认。\ncurcumin 未见毒性。\n")
    assert CA.verify_interference_phrasing(str(flags), [str(marked)])["passed"]

    # weak_only 不在判定范围
    na = tmp_path / "na.txt"
    io.open(str(na), "w", encoding="utf-8").write("WBLG-A 未见毒性。\n")
    assert CA.verify_interference_phrasing(str(flags), [str(na)])["passed"]

    # 缺 flags 必须 fail，不得静默跳过
    assert not CA.verify_interference_phrasing(
        str(tmp_path / "__missing__.csv"), [str(bad)])["passed"]


def test_cli_interference_selftest_runs():
    from adt import cli
    # --selftest 分支不写盘、返回 0（不抛 SystemExit）
    cli.main(["interference", "--selftest"])


# --------------------------------------------------------------------------- #
# 2026-11-11 第二轮：物理 / 光学 / 反应性干扰结构预警
# --------------------------------------------------------------------------- #
def test_physical_selftest_all_cases_pass():
    rep = IF.physical_selftest()
    assert rep["passed"] is True and rep["n_cases"] >= 7
    assert rep["failures"] == []


def test_c87_catechol_vs_guaiacyl_in_physical_layer():
    """愈创木基（阿魏酸）不得被当成邻苯二酚——C87 在物理层同样成立。"""
    caf = IF.assess("O=C(O)/C=C/c1ccc(O)c(O)c1", "caffeic")
    fer = IF.assess("COc1cc(/C=C/C(=O)O)ccc1O", "ferulic")
    assert caf["physical_interference"]["categories"]["redox_cycling"]["flag"] == "suspect"
    assert fer["physical_interference"]["categories"]["redox_cycling"]["flag"] == "none"
    hq = IF.assess("Oc1ccc(O)cc1", "hydroquinone")
    assert hq["physical_interference"]["categories"]["redox_cycling"]["flag"] == "suspect"


def test_physical_layer_never_votes_or_rejects():
    r = IF.assess("COc1cc(/C=C/C(=O)CC(=O)/C=C/c2ccc(O)c(OC)c2)ccc1O", "curcumin")
    p = r["physical_interference"]
    assert p["not_a_vote"] is True
    assert p["admissible_for_rejection"] is False
    assert p["requires_experiment"] is True
    flags = {c["flag"] for c in p["categories"].values()}
    assert flags <= {"suspect", "possible", "none"}       # 没有 FAIL 态
    assert "fail" not in flags
    for c in p["categories"].values():
        assert c["required_evidence"]                    # 每类都必须给正交实验判据
    # 结构层 flag 不受物理层影响（姜黄素仍是 suspect_interference）
    assert r["flag"] == IF.FLAG_SUSPECT


def test_physical_csv_columns_and_determinism(tmp_path):
    src = os.path.join(ROOT, "out_wbh", "compounds.csv")
    if not os.path.isfile(src):
        pytest.skip("out_wbh/compounds.csv 不存在")
    o1, o2 = tmp_path / "a", tmp_path / "b"
    rows1, p1 = IF.assess_file(src, outdir=str(o1))
    rows2, p2 = IF.assess_file(src, outdir=str(o2))
    for k in p1:
        h1 = hashlib.sha256(io.open(p1[k], "rb").read()).hexdigest()
        h2 = hashlib.sha256(io.open(p2[k], "rb").read()).hexdigest()
        assert h1 == h2, "%s 非确定性" % k
    rd = list(csv.DictReader(io.open(p1["csv"], encoding="utf-8-sig")))
    assert list(rd[0]) == IF.CSV_COLS
    for col in ("phys_aggregation", "phys_fluorescence", "phys_redox_cycling"):
        assert col in IF.CSV_COLS and all(r[col] for r in rd)
    assert all(r["phys_requires_experiment"] == "True" for r in rd)


def test_regalosides_have_no_physical_interference_flag():
    """真实糖苷：logP 负、单芳环、单酚 → 物理三层全 none，不折减既有结论。"""
    src = os.path.join(ROOT, "out_wbh", "compounds.csv")
    if not os.path.isfile(src):
        pytest.skip("out_wbh/compounds.csv 不存在")
    rows, _ = IF.assess_file(src, outdir=str(os.path.join(ROOT, "out_interference")))
    for r in rows:
        assert r["flag"] == IF.FLAG_WEAK_ONLY and r["n_strong"] == 0
        for c in r["physical_interference"]["categories"].values():
            assert c["flag"] == "none"
