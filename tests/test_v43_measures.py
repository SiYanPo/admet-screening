# -*- coding: utf-8 -*-
"""v4.3 新增措施的回归测试：专家规则层 + 定性档位约束 + S5 未校准基线。

这三项都是"改了行为"的改动，必须有测试钉住，否则下次会悄悄退化：
  · 结构警示层若 SMARTS 失效 → 静默变成"永远不命中"，Ames 就回到无专家规则状态；
  · `qualitative_only` 若退回纯标签 → ICH M7 的双方法要求又变成一句空话；
  · S5 若从基石实验里被删掉 → "负面结论是否基线过强"这个问题就再也无法回答。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adt import alerts, endpoints as EP                       # noqa: E402


# --------------------------------------------------------------- 专家规则层
def test_all_smarts_compile_and_rules_are_auditable():
    tbl = alerts.rule_table()
    assert len(tbl) >= 15, "警示规则数异常偏少，可能被截断"
    for r in tbl:
        assert r["id"] and r["smarts"] and r["mechanism"] and r["note"]
    # 编译一遍；任一失败会抛 RuntimeError
    assert alerts._compiled()


def test_known_mutagens_hit_expected_alerts():
    cases = {
        "O=[N+]([O-])c1ccccc1": "aromatic_nitro",      # 硝基苯
        "Nc1ccccc1": "aromatic_amine",                 # 苯胺
        "C1OC1c1ccccc1": "epoxide",                    # 氧化苯乙烯
        "CN(C)N=O": "n_nitroso",                       # NDMA
        "COS(=O)(=O)C": "sulfonate_ester",             # 甲磺酸甲酯
        "CCCl": "alkyl_halide",                        # 氯乙烷
    }
    for smi, want in cases.items():
        ids = {h[0] for h in alerts.alerts_from_smiles(smi)}
        assert want in ids, "%s 未命中 %s，实际 %s" % (smi, want, ids)


def test_benign_molecules_do_not_hit_core_rules():
    # 这三条若命中，说明规则过宽，会把整批对照误升级
    for smi in ("c1ccccc1", "CC(=O)Oc1ccccc1C(=O)O", "Cn1c(=O)c2c(ncn2C)n(C)c1=O"):
        ids = {h[0] for h in alerts.alerts_from_smiles(smi)} - {"n_aryl_amide"}
        assert not ids, "%s 命中核心规则 %s" % (smi, ids)


def test_weak_rule_is_separately_identifiable():
    """弱规则（N-芳基酰胺）必须能单独识别，否则无法给"含/不含"两套验证。"""
    ids = {h[0] for h in alerts.alerts_from_smiles("CC(=O)Nc1ccc2ccccc2c1")}
    assert "n_aryl_amide" in ids


# ------------------------------------------------------- ICH M7 双方法合成
def test_two_method_verdict_matches_ich_m7_logic():
    # 唯一允许放行的组合
    v, why = alerts.two_method_verdict("PASS", alert_hit=False, in_domain=True)
    assert v == "PASS" and "两种互补方法均阴性" in why
    # 任一阳性都不得判 Class 5
    for stat, hit in (("FAIL", False), ("PASS", True), ("FAIL", True)):
        v, _ = alerts.two_method_verdict(stat, alert_hit=hit, in_domain=True)
        assert v == "FAIL"
    # 域外不得判 Class 5（Q&A 6.2）
    v, why = alerts.two_method_verdict("PASS", alert_hit=False, in_domain=False)
    assert v == "UNDETERMINED" and "6.2" in why
    v, _ = alerts.two_method_verdict("UNDETERMINED", alert_hit=False)
    assert v == "UNDETERMINED"


# ------------------------------------------------------- 定性档位的可执行约束
def _rec(**kw):
    base = {"compound_id": "X", "endpoint": "Ames", "verdict": "PASS"}
    base.update(kw)
    return base


def test_ames_is_qualitative_only_and_dili_still_blocked():
    assert EP.endpoint_tier("Ames")[0] == "qualitative_only"
    assert EP.endpoint_tier("DILI")[0] == "not_recommended"
    assert EP.endpoint_tier("carcinogenicity")[0] == "not_recommended"


def test_qualitative_requires_two_sources():
    recs, log = EP.apply_tier_policy([_rec(sources="s1")], False)
    assert recs[0]["verdict"] == "UNDETERMINED"
    assert "two_methods" in log[0]["reason"]


def test_qualitative_requires_expert_rule_layer_for_ames():
    recs, log = EP.apply_tier_policy([_rec(sources="s1;s2")], False)
    assert recs[0]["verdict"] == "UNDETERMINED"
    assert "expert_rules" in log[0]["reason"]


def test_qualitative_passes_only_with_two_sources_and_expert_layer():
    recs, log = EP.apply_tier_policy(
        [_rec(sources="s1;s2", expert_rule_layer=True)], False)
    assert recs[0]["verdict"] == "PASS"
    assert recs[0]["qualitative"] is True
    assert "不得据此推导限量" in recs[0]["tier_note"]
    assert log == []


def test_not_recommended_ignores_expert_layer():
    recs, log = EP.apply_tier_policy(
        [_rec(endpoint="DILI", sources="s1;s2", expert_rule_layer=True)], False)
    assert recs[0]["verdict"] == "UNDETERMINED"


# --------------------------------------------------------------- S5 基线
def test_keystone_strategies_include_uncalibrated_baseline():
    import run_keystone as KS
    assert "S5_uncalibrated_conf" in KS.STRATEGIES
    # paired_vs_baseline 默认应与除基线外的全部策略比较
    rows = []
    for st in KS.STRATEGIES:
        for seed in (0, 1):
            rows.append({"endpoint": "hERG", "strategy": st, "seed": seed,
                         "cost_point": "ref", "utility": 0.5 + 0.1 * seed})
    out = KS.paired_vs_baseline(rows, base="S5_uncalibrated_conf")
    names = {d["compare"] for d in out}
    assert all("S5_uncalibrated_conf" in n for n in names)
    assert len(names) == len(KS.STRATEGIES) - 1
