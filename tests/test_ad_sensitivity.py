# -*- coding: utf-8 -*-
"""U6 回归：适用域阈值摄动（Sahigara 2012, Molecules 17:4791-4810）。

要证明的三件事：
  1) 收紧票数门控（require 2→3）会让"只靠 2 组支撑"的判定**丢失**，
     必须计入 n_lost_decided（只统计翻转会漏掉整类变化）；
  2) 放松 AD（域外行当可用）会**新增**判定，必须计入 n_new_decided；
  3) 门控不变时不得有任何变化（稳定性）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adt import sensitivity as S  # noqa: E402

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


RULES = {
    "mmp": dict(id="mmp", unit="probability", role="quality", axis="safety",
                shape="down", **{"pass": 0.3, "fail": 0.7},
                require_sources=2),
    "cyp": dict(id="cyp", unit="probability", role="reference"),
}
SGROUPS = {"s1": "descriptor_ml", "s2": "neighbor_qsar", "s3": "neighbor_qsar"}


def mk(cid, src, val, flag="predicted"):
    return dict(compound_id=cid, endpoint="mmp", value=str(val), unit="probability",
                source=src, domain_flag=flag, source_version="v1")


print("== 1) 收紧门控 -> 丢失判定 ==")
# A: 两组都说低 -> PASS（2 组）
# B: 只有 s1 在域内 -> UNDETERMINED（1 组）
ms = [mk("A", "s1", 0.05), mk("A", "s2", 0.06),
      mk("B", "s1", 0.05),
      mk("C", "s1", 0.05), mk("C", "s3", 0.06)]
rows, summ = S.ad_analyze(ms, RULES, source_groups=SGROUPS,
                          require_grid=(2, 3), domain_modes=("strict",))
by = {r["variant"]: r for r in rows}
r2 = by["domain=strict,require=2"]
r3 = by["domain=strict,require=3"]
check("require=2 无变化", r2["n_flipped"] == 0 and r2["n_lost_decided"] == 0, r2)
check("require=3 丢失 2 个判定（A、C）", r3["n_lost_decided"] == 2, r3)
check("丢失被判为 threshold_critical", r3["flag"] == "threshold_critical", r3)
check("summary 指出最坏变体", summ["worst_variant"] == "domain=strict,require=3", summ)

print("== 2) 放松 AD -> 新增判定 ==")
# D: s1 在域内 0.05，s2 域外但值也是 0.06 -> 严格下 1 组 UNDET；放松后 2 组 PASS
ms2 = [mk("D", "s1", 0.05), mk("D", "s2", 0.06, flag="out_of_domain")]
rows2, _ = S.ad_analyze(ms2, RULES, source_groups=SGROUPS,
                        require_grid=(2,), domain_modes=("strict", "loose"))
b2 = {r["variant"]: r for r in rows2}
check("严格下无判定（基数 0）", b2["domain=strict,require=2"]["n_decided_base"] == 0,
      b2["domain=strict,require=2"])
check("放松后新增 1 个判定", b2["domain=loose,require=2"]["n_new_decided"] == 1,
      b2["domain=loose,require=2"])

print("== 3) 参照端点不受门控影响 ==")
ms3 = [mk("E", "s1", 0.05), mk("E", "s2", 0.06)]
ms3 += [dict(compound_id="E", endpoint="cyp", value="0.1", unit="probability",
             source="s1", domain_flag="predicted", source_version="v1")]
rows3, _ = S.ad_analyze(ms3, RULES, source_groups=SGROUPS,
                        require_grid=(1, 3), domain_modes=("strict",))
check("reference 端点不出现在任何翻转/丢失里",
      all("/cyp" not in r["examples"] for r in rows3)
      and all(r["n_new_decided"] == 0 for r in rows3), rows3)

print()
print("passed %d / failed %d" % (PASS, len(FAIL)))
if FAIL:
    print("FAILED:", FAIL)
    sys.exit(1)
print("ALL OK")
