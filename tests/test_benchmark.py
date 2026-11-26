# -*- coding: utf-8 -*-
"""独立分类基准测试（移植 E8，按 ADMET 分类域改造的验收点）。

验收点：
  1) AUROC 已知值：完美=1.0、反向=0.0、全并列=0.5
  2) AUPRC 完美=1.0
  3) 单一类别 -> 无法算 AUROC（note 明确写"单一类别"）
  4) 覆盖率 = 有预测的真值对 / 真值对总数
  5) 消融：median vs mean 的 AUROC 差（delta_median_vs_mean）被输出
  6) demo 能跑通且 AUROC∈[0,1]

跑法: python tests/test_benchmark.py
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from adt import benchmark as bm  # noqa: E402

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


print("== 1) AUROC 已知值 ==")
check("完美排列=1.0", abs(bm._auroc([0.1, 0.2, 0.3, 0.4], [0, 0, 1, 1]) - 1.0) < 1e-12)
check("反向排列=0.0", abs(bm._auroc([0.4, 0.3, 0.2, 0.1], [0, 0, 1, 1]) - 0.0) < 1e-12)
check("全并列=0.5", abs(bm._auroc([0.5, 0.5, 0.5, 0.5], [0, 0, 1, 1]) - 0.5) < 1e-12)

print("== 2) AUPRC ==")
check("完美 AP=1.0", abs(bm._auprc([0.1, 0.2, 0.3, 0.4], [0, 0, 1, 1]) - 1.0) < 1e-12)

print("== 3) 单一类别 ==")
rules = {}
pred = [dict(compound_id="C%d" % i, endpoint="e", value=str(0.9 - 0.1 * i),
             domain_flag="predicted", source="s") for i in range(4)]
truth1 = [dict(compound_id="C%d" % i, endpoint="e", truth_value=0,
               truth_class="PASS") for i in range(4)]
out1, _ = bm.build(pred, truth1, rules)
check("全 PASS -> auroc 空", out1[0]["auroc"] == "", str(out1[0]))
check("note 写'单一类别'", "单一类别" in out1[0]["note"], out1[0]["note"])

print("== 4) 覆盖率 ==")
truth2 = [dict(compound_id="C0", endpoint="e", truth_value=0, truth_class="PASS"),
          dict(compound_id="C1", endpoint="e", truth_value=1, truth_class="FAIL"),
          dict(compound_id="C2", endpoint="e", truth_value=1, truth_class="FAIL"),
          dict(compound_id="C3", endpoint="e", truth_value=0, truth_class="PASS")]
# 只给 C0..C2 预测，C3 无预测 -> 覆盖 3/4
pred2 = [dict(compound_id="C0", endpoint="e", value="0.1", domain_flag="predicted", source="s"),
         dict(compound_id="C1", endpoint="e", value="0.9", domain_flag="predicted", source="s"),
         dict(compound_id="C2", endpoint="e", value="0.8", domain_flag="predicted", source="s")]
out2, _ = bm.build(pred2, truth2, rules)
check("覆盖率=0.75", abs(out2[0]["coverage"] - 0.75) < 1e-9, str(out2[0]))

print("== 5) 消融列存在 ==")
check("输出 delta_median_vs_mean 列", "delta_median_vs_mean" in out2[0], str(out2[0].keys()))

print("== 6) demo 跑通 ==")
p, t, cl = bm.demo_data(n_compounds=40)
demo_out, summ = bm.build(p, t, rules, cl, B=200, demo=True)
check("demo 有可算 AUROC", summ["n_auroc"] >= 1, str(summ))
check("demo AUROC∈[0,1]",
      all(0.0 <= r["auroc"] <= 1.0 for r in demo_out if isinstance(r["auroc"], float)),
      [r["auroc"] for r in demo_out])
check("demo 标 DEMO", all("DEMO" in r["note"] for r in demo_out))

print()
print("passed %d / failed %d" % (PASS, len(FAIL)))
if FAIL:
    print("FAILED:", FAIL)
    sys.exit(1)
print("ALL OK")
