# -*- coding: utf-8 -*-
"""本轮新增协议的单元测试：硬门 / 状态敏感性 / 措辞封顶 / 独立组计票 / ledger。

跑法: python tests/test_gates_protocol.py
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from rdkit import Chem, RDLogger
RDLogger.DisableLog("rdApp.*")

from adt.normalize import hard_gates, state_sensitivity   # noqa: E402
from adt.phrasing import allowed_statement                # noqa: E402
from adt.reliability import evaluate                      # noqa: E402
from adt.ledger import build, write                       # noqa: E402

PASS = 0
FAIL = []


def check(name, cond, detail=""):
    global PASS
    if cond:
        PASS += 1
        print("  ok  %s" % name)
    else:
        FAIL.append(name)
        print("FAIL  %s  %s" % (name, detail))


M_TRUE = ("CC(=O)O[C@@H](COC(=O)/C=C/c1ccc(O)c(O)c1)"
          "CO[C@@H]1O[C@H](CO)[C@@H](O)[C@H](O)[C@H]1O")

print("== 1) B2 硬门 ==")
check("真 M 无问题", hard_gates(Chem.MolFromSmiles(M_TRUE)) == [])
check("[CH3] 拦截(奇电子)", any(p.startswith("odd_electron")
                              for p in hard_gates(Chem.MolFromSmiles("[CH3]"))))
check("[CH3] 拦截(radical)", any(p.startswith("radical_spec")
                                for p in hard_gates(Chem.MolFromSmiles("[CH3]"))))
# [NH2]c1ccccc1 是普通苯胺（NH2 与芳基成键价=3），不是自由基——必须不拦
check("苯胺不误拦", hard_gates(Chem.MolFromSmiles("[NH2]c1ccccc1")) == [])
check("甲烷不拦", hard_gates(Chem.MolFromSmiles("C")) == [])

print("== 2) C2 状态敏感性（阈值 dTPSA>3 或 dClogP>0.2，实测校准）==")
check("真 M 不敏感", state_sensitivity(Chem.MolFromSmiles(M_TRUE))["state_sensitive"] is False)
ss = state_sensitivity(Chem.MolFromSmiles("CC(=O)[O-]"))
check("醋酸根敏感（dClogP=%.2f）" % ss["dclogp"], ss["state_sensitive"] is True)
check("水杨酸根敏感", state_sensitivity(Chem.MolFromSmiles("[O-]C(=O)c1ccccc1O"))["state_sensitive"])

print("== 3) A1 措辞封顶 ==")
s1 = allowed_statement("PASS", "medium", n_indep=2)
check("2 组一致 -> consistent_pred", s1["tier"] == "consistent_pred")
s2 = allowed_statement("PASS", "medium", n_indep=1)
check("1 组 -> single_group（同组证据不叠加）", s2["tier"] == "single_group")
check("单组禁止跨源一致类表述",
      any("跨源一致" in f for f in s2["forbidden"]))
s3 = allowed_statement("UNDETERMINED", "low", action="补实测")
check("UNDETERMINED 带 action", "补实测" in s3["template"])
check("UNDETERMINED 禁方向结论", "任何方向性结论" in s3["forbidden"])
s4 = allowed_statement("PASS", "medium", n_indep=2, non_ranking=True)
check("饱和端点禁止排序", any("名次" in f for f in s4["forbidden"]))

print("== 4) C1 源独立性计票 ==")
RULES = {"herg": {"shape": "down", "pass": 0.1, "fail": 0.5,
                  "axis": "safety", "require_sources": 2}}
rows_same_group = [  # 3 个域内源，但全部同组 -> 独立组只有 1
    dict(compound_id="A", endpoint="herg", value=0.05, unit="probability",
         source="s1", domain_flag="predicted"),
    dict(compound_id="A", endpoint="herg", value=0.06, unit="probability",
         source="s2", domain_flag="predicted"),
    dict(compound_id="A", endpoint="herg", value=0.04, unit="probability",
         source="s3", domain_flag="predicted"),
]
groups = {"s1": "descriptor_ml", "s2": "descriptor_ml", "s3": "descriptor_ml"}
recs = evaluate(rows_same_group, RULES, source_groups=groups)
r = recs[0]
check("同组 3 源 -> n_indep_groups=1", r["n_indep_groups"] == 1,
      str(r["n_indep_groups"]))
check("独立组 1 < require 2 -> UNDETERMINED", r["verdict"] == "UNDETERMINED")
recs0 = evaluate(rows_same_group, RULES)          # 旧行为：每源一票
check("无分组时保持旧判定 PASS", recs0[0]["verdict"] == "PASS")
rows_cross = rows_same_group[:2] + [
    dict(compound_id="A", endpoint="herg", value=0.07, unit="probability",
         source="s4", domain_flag="predicted")]
groups["s4"] = "deep_learning"
recs2 = evaluate(rows_cross, RULES, source_groups=groups)
check("跨 2 组一致 -> PASS(medium)", recs2[0]["verdict"] == "PASS"
      and recs2[0]["confidence"] == "medium")

print("== 5) A2 ledger ==")
meas = [dict(compound_id="A", endpoint="herg", value="0.05", source="s1",
             domain_flag="predicted", unit="probability")]
rel = [dict(compound_id="A", endpoint="herg", verdict="PASS", value_used=0.05,
            confidence="low", n_in_domain=1, n_measured=0, n_indep_groups=1,
            action="")]
ax = [dict(compound_id="A", axis="safety", geo_mean="1.0", coverage="1.0",
           flag="ok", n_audited=1, endpoints_audited="herg")]
led = build(rel, ax, meas)
check("结论级 supported", led[0]["status"] == "supported")
check("轴级 supported", led[1]["status"] == "supported")
rel_bad = [dict(rel[0], verdict="FAIL", n_in_domain=0, value_used="")]
led2 = build(rel_bad, [], [])
check("无域内支撑的 FAIL -> unsupported", led2[0]["status"] == "unsupported")

print()
print("passed %d / failed %d" % (PASS, len(FAIL)))
if FAIL:
    print("FAILED:", FAIL)
    sys.exit(1)
print("ALL OK")
