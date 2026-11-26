# -*- coding: utf-8 -*-
"""C83/C84/C85 回归：hERG IC50 只能靠"类似物实测锚点"，且必须按档位表达。

背景（本次实测得出来的三条纪律）：
  C83 hERG 的三个计算源都不给 IC50（浓度）：ADMETlab/ADMET-AI 给概率、vNN 给 Yes/No。
      唯一有浓度的是 ChEMBL 的类似物实测——18 个目标分子邻居里 hERG 记录 **0 条**，
      而咖啡酸有 1 条（类型是 Potency 2.51 µM，**不是 IC50**）、CAPE 有 2 条但
      **数值为 None**。"记录存在" ≠ "有可用的数"。
  C84 同一分子（curcumin）手工膜片钳 5.55 µM vs 自动化平台 >100 µM，差 20 倍
      → IC50 不确定度 ≥10×，禁止报精确 Margin，只报档位。
  C85 糖苷不必然是阻断剂：人参皂苷 Rg3 是 hERG 激动剂；taxifolin 糖苷最大抑制仅 36.9%
      （relative IC50），CAPE 在 AP clamp 下反而增大 I_hERG → 尾电流 IC50 高估扭转风险。

跑法: python tests/test_herg_anchor.py
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from adt import pbpk          # noqa: E402

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


print("== 1) 资产可读且已分级 ==")
rows = pbpk.load_herg_anchors()
check("资产存在且有数值行", len(rows) >= 8, str(len(rows)))
check("每行都带 provenance_level",
      all(r["level"] for r in rows), str([r["name"] for r in rows if not r["level"]]))
check("ChEMBL Potency 被单独标注（不混作 IC50）",
      any(r["level"] == "chembl_potency" for r in rows))

print("== 2) 关键锚点数值在位 ==")
by = {r["name"].lower(): r["ic50"] for r in rows}
check("CAPE = 10.6 µM", abs(by.get("cape (caffeic acid phenethyl ester)", -1) - 10.6) < 1e-9,
      str(by.get("cape (caffeic acid phenethyl ester)")))
check("taxifolin 糖苷 = 9.6 µM",
      abs(by.get("taxifolin 3-o-beta-d-glucopyranoside", -1) - 9.6) < 1e-9,
      str(by.get("taxifolin 3-o-beta-d-glucopyranoside")))
check("EPMC（肉桂酸酯）= 53 µM",
      abs(by.get("ethyl p-methoxycinnamate", -1) - 53) < 1e-9)
check("咖啡酸 Potency = 2.51 µM",
      abs(by.get("caffeic acid (qhts potency)", -1) - 2.5119) < 1e-3)

print("== 3) C84：平台差异必须 ≥10 倍（这就是不能报精确 Margin 的理由）==")
cur = [r["ic50"] for r in rows if r["name"].lower().startswith("curcumin")]
check("curcumin 至少 2 个平台值", len(cur) >= 2, str(cur))
check("最大/最小 ≥ 10 倍", len(cur) >= 2 and max(cur) / min(cur) >= 10,
      "%.1f×" % (max(cur) / min(cur)) if cur else "-")

print("== 4) 证据锚点：最接近骨架的 3 个的几何均值 ==")
a = pbpk.evidence_ic50_anchor()
check("命中 3 个（咖啡酸/CAPE/EPMC）", a["n"] == 3, str(a["n"]))
check("点估计 11.2 µM（±0.2）", abs(a["point"] - 11.22) < 0.2, "%.2f" % a["point"])
check("范围 2.51–53 µM", abs(a["lo"] - 2.5119) < 1e-2 and abs(a["hi"] - 53.0) < 1e-2,
      "%.2f–%.2f" % (a["lo"], a["hi"]))
check("全集中位 ≈30 µM（未被低值带偏）", abs(a["median_all"] - 29.9) < 0.5,
      "%.1f" % a["median_all"])
check("几何均值高于最小值、低于中位（合理性）",
      a["lo"] < a["point"] < a["median_all"], "%.2f" % a["point"])

print("== 5) 用锚点算 J 的 Margin（与报告数字对齐）==")
m = pbpk.margin_table(444.6, [a["point"], 2.5119])
check("IC50=11.2 µM 时 J 约 25×（±2）", abs(m[0]["margin"] - 25.2) < 2.0,
      "%.1f" % m[0]["margin"])
check("IC50=2.5 µM 时 J 约 5.6×（落入 FAIL）",
      abs(m[1]["margin"] - 5.65) < 0.3 and m[1]["tier"] == "FAIL",
      "%.2f %s" % (m[1]["margin"], m[1]["tier"]))

print("== 6) 缺资产时优雅降级（不抛异常）==")
b = pbpk.evidence_ic50_anchor(path="/nonexistent/x.csv")
check("返回 nan 而不是崩溃", b["point"] != b["point"] and b["n"] == 0, str(b["point"]))

print()
print("passed %d / failed %d" % (PASS, len(FAIL)))
if FAIL:
    print("FAILED:", FAIL)
    sys.exit(1)
print("ALL OK")
