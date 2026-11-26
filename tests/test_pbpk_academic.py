# -*- coding: utf-8 -*-
"""U7~U11 回归：PBPK 学术化层。

覆盖文献：
  D3 Pang & Rowland 1977 (DOI 10.1007/BF01059688)  well-stirred 公式
  D4 Obach 2011 (DOI 10.2174/156802611794480873)   IVIVE 假设与敏感性
  D1/D2 FDA 2018 / EMA 2018                       申报口径
  G1 Fagerholm 2008 (DOI 10.1211/jpp.60.5.0001)   EHR 机制前提
  E1 Li 2019 CiPA (PMID 30151907)                 hERG 单通道局限
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adt import pbpk  # noqa: E402

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


print("== 1) well-stirred 教科书自校验（Pang-Rowland）==")
ws = pbpk.well_stirred_selfcheck()
check("自校验整体 PASS", ws["ok"] is True, ws["cases"])
# 本模型 Qh = 肝动脉 364 + 肠 790 = 1154 mL/min ≈ 69.2 L/h
# （文献"总肝血流 ~90 L/h"对应 1500 mL/min；本模型取偏保守一侧，
#   自校验只要求"与模型内部一致"，不要求等于某本教科书的数值）
check("Qh 在 65–75 L/h（模型内部一致）", 65.0 < ws["qh"] < 75.0, ws["qh"])
for c in ws["cases"]:
    check("%s → %.3f" % (c["name"], c["expect"]), c["pass"], c)

print("== 2) C81 回归：fu 必须乘在 CLint 上，不是乘在 Qh 上 ==")
q = pbpk.QH
check("Eh(fu=0.5, CLint=2Qh)=0.5",
      abs(pbpk.eh_well_stirred(0.5, 2 * q) - 0.5) < 1e-9,
      pbpk.eh_well_stirred(0.5, 2 * q))
# 错误实现（fu 乘在 Qh 上）会给出 0.667，必须能被这个断言区分出来
wrong = (2 * q) / (0.5 * q + 2 * q)
check("错误实现会得到 %.3f（≠0.5）→ 断言有区分力" % wrong, abs(wrong - 0.5) > 0.1, wrong)
check("Eh 随 fu 单调增",
      pbpk.eh_well_stirred(0.1, 50) < pbpk.eh_well_stirred(0.5, 50)
      < pbpk.eh_well_stirred(0.9, 50), "monotone")

print("== 3) IVIVE 假设链与 simulate 内部一致（Obach）==")
iv = pbpk.ivive_assumptions(25.8, 35.0)
manual = 25.8 * pbpk.MPPGL * pbpk.LIVER_G / 1000.0 * 0.06 * 0.35
check("CLint_b 与手算一致", abs(iv["clint_b_lh"] - manual) < 0.05,
      (iv["clint_b_lh"], round(manual, 2)))
check("Eh 与公式一致",
      abs(iv["eh"] - pbpk.eh_well_stirred(0.35, iv["clint_b_lh"])) < 0.002,
      iv["eh"])
check("CLh = Qh·Eh", abs(iv["clh_lh"] - pbpk.QH * iv["eh"]) < 0.6, iv["clh_lh"])
check("假设清单含 fu_mic 与 MPPGL",
      any("fu_mic" in a["item"] for a in iv["assumptions"])
      and any("MPPGL" in a["item"] for a in iv["assumptions"]),
      [a["item"] for a in iv["assumptions"]])
check("敏感性 4 条（±2×）", len(iv["sensitivity"]) == 4, iv["sensitivity"])
lo = [s for s in iv["sensitivity"] if "÷2" in s["variant"]][0]
hi = [s for s in iv["sensitivity"] if "×2" in s["variant"]][0]
check("CLint 翻倍 → Eh 升高", hi["eh"] > iv["eh"] > lo["eh"],
      (lo["eh"], iv["eh"], hi["eh"]))

print("== 3b) fu_mic 校正方向 ==")
iv_no = pbpk.ivive_assumptions(25.8, 35.0, fu_mic=1.0)
iv_fm = pbpk.ivive_assumptions(25.8, 35.0, fu_mic=0.5)
check("fu_mic=0.5 使 CLint 翻倍（除以 fu_mic）",
      abs(iv_fm["clint_b_lh"] - 2 * iv_no["clint_b_lh"]) < 0.1,
      (iv_no["clint_b_lh"], iv_fm["clint_b_lh"]))

print("== 4) EHR 机制前提（Fagerholm）：MW 不计分 ==")
e1 = pbpk.ehr_prerequisites(25.8, 35.0, clogp=-1.9, transporter_mediated=True, mw=450)
check("MW 项 met=None（信息项不计分）",
      any(c["item"].startswith("分子量") and c["met"] is None for c in e1["checks"]),
      e1["checks"])
check("极性大 + 有转运体 → uncertain", e1["verdict"] == "uncertain", e1)
e2 = pbpk.ehr_prerequisites(5.0, 60.0, clogp=2.5, transporter_mediated=True, mw=450)
check("低清除 + 亲脂 + 转运体 → plausible", e2["verdict"] == "plausible", e2)
e3 = pbpk.ehr_prerequisites(400.0, 20.0, clogp=0.1, transporter_mediated=False)
check("高清除 + 无转运体 → unlikely", e3["verdict"] == "unlikely", e3)

print("== 5) 申报口径与 CiPA 声明 ==")
qs = pbpk.qualification_statement()
for k in ("intended_use", "platform_qualification", "verification",
          "sensitivity_analysis", "predictive_performance", "limitations",
          "ema_report_sections"):
    check("qualification 含 %s" % k, k in qs and bool(qs[k]), k)
check("明确'不用于剂量选择'", "不用于" in qs["intended_use"], qs["intended_use"])
check("EMA 报告 7 段", len(qs["ema_report_sections"]) == 7, qs["ema_report_sections"])
hr = pbpk.herg_evidence_route()
check("hERG 路线为单通道锚定", hr["route"] == "single_channel_ic50_anchor", hr)
check("给出 CiPA 升级路径", "CiPA" in hr["cipa_route"], hr["cipa_route"])
check("声明只报档位", "档位" in hr["reporting_rule"], hr["reporting_rule"])

print()
print("passed %d / failed %d" % (PASS, len(FAIL)))
if FAIL:
    print("FAILED:", FAIL)
    sys.exit(1)
print("ALL OK")
