# -*- coding: utf-8 -*-
"""v2.5.0 转运体先验层测试。

这层的**唯一价值**是"告诉你该做哪个实验"，所以测试也围绕这一点：
  T1 化学型识别必须准（尤其邻苯二酚 vs 愈创木基 —— 松 SMARTS 会把阿魏酰误判成邻苯二酚）
  T2 每条先验都必须带实验处方（否则这层没用）
  T3 每条都必须明写"不是预测值"（否则会被误当预测用）
  T4 汇总必须**按分子去重**（同一分子命中多个化学型会重复列同一转运体）
  T5 必须显式声明"无 in-silico 源"

跑法: python tests/test_transport.py
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from adt import transport          # noqa: E402

PASS = 0
FAIL = []

# A = 对香豆酰葡萄糖苷（无邻苯二酚、无甲氧基）
SMI_A = ("O=C(/C=C/c1ccc(O)cc1)OC[C@@H](O)CO[C@@H]1O[C@H](CO)[C@@H](O)"
         "[C@H](O)[C@H]1O")
# C = 咖啡酰葡萄糖苷（有邻苯二酚）
SMI_C = ("O=C(/C=C/c1ccc(O)c(O)c1)OC[C@@H](O)CO[C@@H]1O[C@H](CO)[C@@H](O)"
         "[C@H](O)[C@H]1O")
# F = 阿魏酰葡萄糖苷（愈创木基：4-OH-3-OMe，**不是**邻苯二酚）
SMI_F = ("COc1cc(/C=C/C(=O)OC[C@@H](O)CO[C@@H]2O[C@H](CO)[C@@H](O)[C@H](O)"
         "[C@H]2O)ccc1O")


def check(name, cond, detail=""):
    global PASS
    if cond:
        PASS += 1
        print("  ok  %s" % name)
    else:
        FAIL.append(name)
        print("FAIL  %s  %s" % (name, detail))


pr = transport.load_priors()

print("== T5) 必须声明无 in-silico 源 ==")
check("priors 可读", bool(pr.get("chemotypes")), str(len(pr.get("chemotypes") or [])))
check("in_silico_sources = none",
      (pr.get("data_availability") or {}).get("in_silico_sources") == "none",
      str((pr.get("data_availability") or {}).get("in_silico_sources")))
check("有 backfill_endpoints", len(pr.get("backfill_endpoints") or []) >= 3)

print("== T1) 化学型识别 ==")
hA, _ = transport.chemotype_flags(SMI_A, pr)
hC, tpsaC = transport.chemotype_flags(SMI_C, pr)
hF, _ = transport.chemotype_flags(SMI_F, pr)
check("A 命中 glucopyranoside", "glucopyranoside" in hA, str(hA))
check("A 命中 cinnamoyl_ester", "cinnamoyl_ester" in hA, str(hA))
check("A 不命中 catechol（对香豆酰只有一个 OH）", "catechol" not in hA, str(hA))
check("C 命中 catechol", "catechol" in hC, str(hC))
check("F 命中 guaiacyl", "guaiacyl" in hF, str(hF))
check("F 不命中 catechol（阿魏酰是 OMe+OH，不是两个 OH）",
      "catechol" not in hF, str(hF))
check("三者都命中 high_tpsa（TPSA>140）",
      all("high_tpsa" in h for h in (hA, hC, hF)), str((hA, hC, hF)))
check("TPSA 在 150–200（合理性）", 150 < tpsaC < 200, "%.1f" % tpsaC)
bad, _ = transport.chemotype_flags("CCO", pr)
check("乙醇不命中任何化学型", bad == [], str(bad))
check("空 SMILES 不崩", transport.chemotype_flags("", pr) == ([], None))

print("== T2) 每条先验都要有实验处方 ==")
rows = transport.assess("C", SMI_C, pr)[0]
check("C 产生多条先验", len(rows) >= 4, str(len(rows)))
check("每条都有 recommended_assay",
      all(r["recommended_assay"].strip() for r in rows),
      str([r["transporter"] for r in rows if not r["recommended_assay"].strip()]))
check("每条都有 rationale", all(len(r["rationale"]) > 20 for r in rows))

print("== T3) 必须明写不是预测值 ==")
check("predictive_value 含 none",
      all("none" in r["predictive_value"] for r in rows),
      str({r["predictive_value"] for r in rows}))
check("evidence_level 非空", all(r["evidence_level"] for r in rows))

print("== T4) 汇总按分子去重 ==")
s = transport.summarize(rows)
by = {d["transporter"]: d for d in s}
check("OATP2B1 计数 = 1（不是多化学型叠加）",
      by.get("OATP2B1", {}).get("n") == 1, str(by.get("OATP2B1")))
check("OATP2B1 被标为 medium 及以上", by.get("OATP2B1", {}).get("n_medium_up") == 1)
check("SGLT1 存在但 medium 及以上 = 0（低可能性，诚实标注）",
      by.get("SGLT1", {}).get("n_medium_up") == 0, str(by.get("SGLT1")))
two = transport.summarize(rows + transport.assess("F", SMI_F, pr)[0])
check("两个分子时 OATP2B1 计数 = 2",
      {d["transporter"]: d for d in two}["OATP2B1"]["n"] == 2)

print()
print("passed %d / failed %d" % (PASS, len(FAIL)))
if FAIL:
    print("FAILED:", FAIL)
    sys.exit(1)
print("ALL OK")
