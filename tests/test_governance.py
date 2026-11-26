# -*- coding: utf-8 -*-
"""U4/U5 回归：QAF 四原则 + 三层适用域 + PROBAST 偏倚风险 + tier 联动。

文献锚点：
  OECD QAF 2023 (DOI 10.1787/d96118f6-en)
  Hanser 2016 (DOI 10.1080/1062936X.2016.1250229)
  Wolff PROBAST 2019 (DOI 10.7326/M18-1376)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adt import governance as G  # noqa: E402
from adt import tiers  # noqa: E402

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


COV = [dict(source="s1", endpoint="e1", flag="usable"),
       dict(source="s1", endpoint="e2", flag="no_prediction"),
       dict(source="s2", endpoint="e1", flag="usable"),
       dict(source="s2", endpoint="e2", flag="usable")]
REL = [dict(compound_id="A", endpoint="e1", verdict="PASS"),
       dict(compound_id="A", endpoint="e2", verdict="UNDETERMINED"),
       dict(compound_id="B", endpoint="e1", verdict="PASS"),
       dict(compound_id="B", endpoint="e2", verdict="PASSTHRU")]

print("== 1) QAF P1：端点/单位/版本/manifest ==")
q = G.qaf_assess(n_endpoints=10, n_endpoints_with_unit=10, n_sources=2,
                 n_sources_versioned=2, coverage_rows=COV, reliability_rows=REL,
                 benchmark_rows=[], tier="T2", manifest_present=True)
p1 = q[0]
check("全部声明 -> satisfied", p1["status"] == "satisfied", p1)
q_bad = G.qaf_assess(n_endpoints=10, n_endpoints_with_unit=6, n_sources=2,
                     n_sources_versioned=1, coverage_rows=COV, reliability_rows=REL)
check("缺单位/版本 -> partial", q_bad[0]["status"] == "partial", q_bad[0])
check("缺口写清 4 个端点缺单位", "4/10" in q_bad[0]["gap"], q_bad[0]["gap"])

print("== 2) QAF P2：无覆盖矩阵 = not_met ==")
q2 = G.qaf_assess(n_endpoints=10, n_endpoints_with_unit=10, n_sources=2,
                  n_sources_versioned=2, coverage_rows=[], reliability_rows=REL)
check("无覆盖 -> not_met", q2[1]["status"] == "not_met", q2[1])
q3 = G.qaf_assess(n_endpoints=10, n_endpoints_with_unit=10, n_sources=2,
                  n_sources_versioned=2, coverage_rows=COV, reliability_rows=REL)
check("有覆盖且有 UNDETERMINED -> satisfied", q3[1]["status"] == "satisfied", q3[1])

print("== 3) QAF P3：DEMO 基准不算验证 ==")
demo_bm = [dict(endpoint="e1", auroc="0.9", note="DEMO(合成真值)")]
r = G.qaf_assess(n_endpoints=10, n_endpoints_with_unit=10, n_sources=2,
                 n_sources_versioned=2, coverage_rows=COV, reliability_rows=REL,
                 benchmark_rows=demo_bm)[2]
check("仅 DEMO -> not_met", r["status"] == "not_met", r)
real_bm = [dict(endpoint="e1", auroc="0.8", note="")]
r2 = G.qaf_assess(n_endpoints=10, n_endpoints_with_unit=10, n_sources=2,
                  n_sources_versioned=2, coverage_rows=COV, reliability_rows=REL,
                  benchmark_rows=real_bm, calibration_reported=False)[2]
check("真基准无校准 -> partial", r2["status"] == "partial", r2)
r3 = G.qaf_assess(n_endpoints=10, n_endpoints_with_unit=10, n_sources=2,
                  n_sources_versioned=2, coverage_rows=COV, reliability_rows=REL,
                  benchmark_rows=real_bm, calibration_reported=True)[2]
check("真基准+校准 -> satisfied", r3["status"] == "satisfied", r3)

print("== 4) QAF P4：档位映射 ==")
for t, want in (("T1", "not_met"), ("T2", "partial"), ("T3", "satisfied")):
    rr = G.qaf_assess(n_endpoints=1, n_endpoints_with_unit=1, tier=t)[3]
    check("%s -> %s" % (t, want), rr["status"] == want, rr)

print("== 5) 三层适用域（Hanser）==")
adl = G.ad_levels(REL, COV, dict(tier="T2", max_conclusion="decision_support"))
levels = {r["level"] for r in adl}
check("三层齐全", levels == {"model", "prediction", "decision"}, levels)
s1 = [r for r in adl if r["level"] == "model" and r["id"] == "s1"]
check("s1 有 1/2 端点可用 -> in_domain", s1 and s1[0]["status"] == "in_domain", s1)
zero_src = [r for r in adl if r["level"] == "model" and r["id"] == "zzz"]
check("不存在的源不产出", not zero_src)
dec = [r for r in adl if r["level"] == "decision"][0]
check("T2 -> decision partial", dec["status"] == "partial", dec)

print("== 6) PROBAST：无真值 -> high ==")
rob = G.risk_of_bias(n_compounds=14, n_scaffolds=2, n_sources=3,
                     n_judged_indep2=9, n_measured=0, has_benchmark=False)
check("整体 high", rob["overall"] == "high", rob["overall"])
d1 = [d for d in rob["domains"] if d["domain"].startswith("D1")][0]
check("骨架簇 2 个 -> D1 high", d1["judgement"] == "high", d1)
d3 = [d for d in rob["domains"] if d["domain"].startswith("D3")][0]
check("无实测 -> D3 high", d3["judgement"] == "high", d3)

rob2 = G.risk_of_bias(n_compounds=120, n_scaffolds=30, n_sources=4,
                      n_judged_indep2=5, n_judged=5, n_measured=40,
                      has_benchmark=True, benchmark_ok=True,
                      calibration_reported=True)
check("大样本+实测+基准+校准 -> low", rob2["overall"] == "low", rob2["overall"])

print("== 6b) D2：只有部分端点达 2 组 -> 不得判 low ==")
rob3 = G.risk_of_bias(n_compounds=120, n_scaffolds=30, n_sources=4,
                      n_judged_indep2=5, n_judged=20, n_measured=40,
                      has_benchmark=True, benchmark_ok=True,
                      calibration_reported=True)
check("5/20 达 2 组 -> D2 medium", rob3["overall"] == "medium", rob3["overall"])

print("== 7) tier 与偏倚风险联动 ==")
st = dict(n_measured=5, n_judged_indep2=5, n_judged=5, n_rows=20)
t_hi, _, miss = tiers.assign(st, True, True, True, rob="high")
check("rob=high 不得升 T3", t_hi != "T3", t_hi)
check("缺口里写明偏倚风险", any("偏倚风险" in m for m in miss), miss)
t_lo, _, _ = tiers.assign(st, True, True, True, rob="low")
check("rob=low 且条件齐 -> T3", t_lo == "T3", t_lo)
t_none, _, _ = tiers.assign(st, True, True, True)
check("rob=None 保持旧行为 (T3)", t_none == "T3", t_none)

print()
print("passed %d / failed %d" % (PASS, len(FAIL)))
if FAIL:
    print("FAILED:", FAIL)
    sys.exit(1)
print("ALL OK")
