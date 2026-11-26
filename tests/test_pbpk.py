# -*- coding: utf-8 -*-
"""v2.4.0 PBPK + 安全裕度反推的契约测试。

锁六件事（每条都对应一个曾经踩过或容易踩的坑）：
  1. 质量守恒 < 1e-4（首版漏了粪便汇 → 差 0.766，正好是 1−Fa·Fg）
  2. 剂量线性：Cmax ∝ dose（首版单位混用导致 F 偏 3.7 倍）
  3. t½ 必须能算出来（尾部拟合点太少会 NaN）
  4. 裕度分档边界（Redfern 10/30/100）
  5. dose_at_margin 与 margin_table 必须自洽（反推再正推，回到目标值）
  6. 物理边界：负 CLint / fu>100 必须被拒

跑法: python tests/test_pbpk.py
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from adt import pbpk                                    # noqa: E402

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


# 一个代表性的分子：CLint 25 µL/min/mg、fu 35%、Fa 0.26、logP 1.0、MW 480
CL, FU, FA, LOGP, MW = 25.0, 0.35, 0.26, 1.0, 480.0

print("== 1) 质量守恒 ==")
res = pbpk.simulate(100.0, CL, FU, FA, LOGP)
mb = pbpk.mass_balance(res)
check("守恒误差 < 1e-4", mb < 1e-4, "%.2e" % mb)

print("== 2) 剂量线性（Cmax ∝ dose）==")
c100 = pbpk.metrics(pbpk.simulate(100.0, CL, FU, FA, LOGP), MW)["cmax_nM"]
c200 = pbpk.metrics(pbpk.simulate(200.0, CL, FU, FA, LOGP), MW)["cmax_nM"]
check("200 mg 的 Cmax 是 100 mg 的 2 倍（±2%）",
      abs(c200 / c100 - 2.0) < 0.04, "%.3f" % (c200 / c100))

print("== 3) t½ 可计算且有物理意义 ==")
mt = pbpk.metrics(pbpk.simulate(100.0, CL, FU, FA, LOGP), MW)
check("t½ 不是 NaN", mt["thalf_h"] == mt["thalf_h"], str(mt["thalf_h"]))
check("t½ 在 0.2–50 h（量级合理）", 0.2 < mt["thalf_h"] < 50, "%.2f" % mt["thalf_h"])
check("Cmax 在 1 nM–100 µM", 1 < mt["cmax_nM"] < 1e5, "%.0f" % mt["cmax_nM"])

print("== 4) 裕度分档边界（Redfern 10/30/100）==")
for m, want in ((9.9, "FAIL"), (10.0, "TIGHT"), (29.9, "TIGHT"),
                (30.0, "OK"), (99.9, "OK"), (100.0, "WIDE")):
    tag, _ = pbpk.margin_tier(m)
    check("margin %.1f → %s" % (m, want), tag == want, tag)

print("== 5) 裕度与剂量反推自洽 ==")
cmax = mt["cmax_nM"]
mg = pbpk.margin_table(cmax, [10.0])[0]
check("IC50=10 µM 的裕度 = 10000/Cmax",
      abs(mg["margin"] - 10000.0 / cmax) < 1e-6, "%.1f" % mg["margin"])
d30 = pbpk.dose_at_margin(100.0, cmax, 10.0, 30)
m_at_d30 = pbpk.margin_table(cmax * d30 / 100.0, [10.0])[0]["margin"]
check("在该剂量下裕度回到 30（±1%）", abs(m_at_d30 - 30) < 0.3, "%.2f" % m_at_d30)
check("裕度 30 对应剂量 < 裕度 10 对应剂量（反向关系）",
      pbpk.dose_at_margin(100.0, cmax, 10.0, 30) < pbpk.dose_at_margin(100.0, cmax, 10.0, 10))

print("== 6) 物理边界必须拒 ==")
check("负 CLint 被拒", pbpk.in_phys_range_ok(-4.3, 35.0) is False)
check("CLint=0 允许（无代谢）", pbpk.in_phys_range_ok(0.0, 35.0) is True)
check("fu>100 被拒", pbpk.in_phys_range_ok(25.0, 101.0) is False)
check("fu=0 允许", pbpk.in_phys_range_ok(25.0, 0.0) is True)

print("== 7) 极端输入不应崩（fu=0 / CLint=0）==")
r0 = pbpk.metrics(pbpk.simulate(100.0, 0.0, 0.0, FA, LOGP), MW)
check("CLint=0 且 fu=0 仍能算（Cmax>0）", r0["cmax_nM"] > 0, "%.1f" % r0["cmax_nM"])

print()
print("passed %d / failed %d" % (PASS, len(FAIL)))
if FAIL:
    print("FAILED:", FAIL)
    sys.exit(1)
print("ALL OK")
