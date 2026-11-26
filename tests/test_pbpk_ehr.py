# -*- coding: utf-8 -*-
"""v2.5.0 肠肝循环（EHR）的结构不变量测试。

加 EHR 时最容易犯的错不是"算错"，而是**悄悄改变原有的量**。所以这里锁死三个不变量：

  I1  fre=0（胆汁全进粪便）时，AUC/t½/Cmax 必须与"无 EHR"**完全一致**
      —— 因为胆汁排泄只是"换了个出口"，总肝清除 clint·c_liv 没变。
  I2  fbile=0 时，fre 无论取多少都不得改变任何结果（没有胆汁流，重吸收无从谈起）。
  I3  fbile 与 fre 同时 >0 时，AUC/t½ 必须**单调递增**（重吸收越多、等效清除越低）。

再加三条物理性质：
  I4  质量守恒在任意组合下 <1e-6（新增的胆汁房室必须计入总量）。
  I5  EHR 主要改终末相（t½）而**几乎不改 Cmax** —— 这是"EHR 不能挽救低暴露"的定量依据。
  I6  ehr_scan 输出结构：组合数、基线 ratio=1.0。

跑法: python tests/test_pbpk_ehr.py
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from adt import pbpk            # noqa: E402

PASS = 0
FAIL = []

MW = 480.0
BASE = dict(dose_mg=100.0, clint_um=25.0, fu=0.35, fa=0.26, clogp=1.0)


def check(name, cond, detail=""):
    global PASS
    if cond:
        PASS += 1
        print("  ok  %s" % name)
    else:
        FAIL.append(name)
        print("FAIL  %s  %s" % (name, detail))


def run(**kw):
    r = pbpk.simulate(**BASE, tmax_h=360.0, n_out=1200, **kw)
    return pbpk.metrics(r, MW), pbpk.mass_balance(r)


ref, mb_ref = run()

print("== I1) fre=0 时 AUC 必须与无 EHR 完全一致 ==")
for fb in (0.2, 0.4, 0.6, 1.0):
    m, mb = run(fbile=fb, fre=0.0)
    d = abs(m["auc_nMh"] - ref["auc_nMh"]) / ref["auc_nMh"]
    check("fbile=%.1f, fre=0 → AUC 偏差 %.1e" % (fb, d), d < 1e-9, "%.2e" % d)
    check("  守恒 %.1e" % mb, mb < 1e-6, "%.2e" % mb)

print("== I2) fbile=0 时 fre 不应有任何影响 ==")
for fr in (0.3, 0.8, 1.0):
    m, _ = run(fbile=0.0, fre=fr)
    d = abs(m["auc_nMh"] - ref["auc_nMh"]) / ref["auc_nMh"]
    check("fbile=0, fre=%.1f → AUC 偏差 %.1e" % (fr, d), d < 1e-9, "%.2e" % d)

print("== I3) 单调性：重吸收越多，AUC 与 t½ 越大 ==")
seq = [(0.0, 0.0), (0.4, 0.2), (0.4, 0.5), (0.4, 0.8)]
aucs, ths = [], []
for fb, fr in seq:
    m, _ = run(fbile=fb, fre=fr)
    aucs.append(m["auc_nMh"])
    ths.append(m["thalf_h"])
check("AUC 严格递增 %s" % ["%.0f" % x for x in aucs],
      all(aucs[i] < aucs[i + 1] for i in range(len(aucs) - 1)), str(aucs))
check("t½ 严格递增 %s" % ["%.2f" % x for x in ths],
      all(ths[i] < ths[i + 1] for i in range(len(ths) - 1)), str(ths))

print("== I4) 极端组合仍守恒 ==")
for kw in (dict(fbile=1.0, fre=1.0), dict(fbile=1.0, fre=0.0),
           dict(fbile=0.0, fre=1.0), dict(fbile=0.7, fre=0.9, kbile=2.0)):
    _m, mb = run(**kw)
    check("%s 守恒 %.1e" % (kw, mb), mb < 1e-6, "%.2e" % mb)

print("== I5) EHR 改 t½ 而几乎不改 Cmax（所以它救不了低暴露）==")
m_hi, _ = run(fbile=0.6, fre=0.8)
d_th = m_hi["thalf_h"] / ref["thalf_h"] - 1
d_cm = m_hi["cmax_nM"] / ref["cmax_nM"] - 1
check("t½ 放大 >50%%（实测 %.0f%%）" % (d_th * 100), d_th > 0.5, "%.2f" % d_th)
check("Cmax 放大 <20%%（实测 %.0f%%）" % (d_cm * 100), d_cm < 0.2, "%.2f" % d_cm)
check("AUC 放大介于两者之间",
      d_cm < (m_hi["auc_nMh"] / ref["auc_nMh"] - 1) < d_th)

print("== I6) ehr_scan 输出结构 ==")
comps = [dict(compound_id="X", mw=MW, clogp=1.0, clint_um=25.0, fu_pct=35.0, fa=0.26)]
sc = pbpk.ehr_scan(comps, 100.0, fbile_grid=(0.0, 0.4), fre_grid=(0.0, 0.5),
                   tmax_h=360.0, n_out=600)
check("组合数 = 2×2 = 4", len(sc) == 4, str(len(sc)))
b = [x for x in sc if x["fbile"] == 0.0 and x["fre"] == 0.0][0]
check("基线 ratio = 1.0", abs(b["auc_ratio"] - 1.0) < 1e-9, str(b["auc_ratio"]))
check("每条都带 mass_err 且 <1e-6", all(x["mass_err"] < 1e-6 for x in sc))

print()
print("passed %d / failed %d" % (PASS, len(FAIL)))
if FAIL:
    print("FAILED:", FAIL)
    sys.exit(1)
print("ALL OK")
