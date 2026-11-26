# -*- coding: utf-8 -*-
"""U12 回归：split conformal（Norinder 2014, JCIM 54:1596-1603）。

验收点：
  1) 分位秩 k=ceil((n+1)(1−α))，q 取第 k 个绝对残差
  2) 经验覆盖率 ≥ 1−α（构造性质）
  3) n 太小时给 ±∞ 而不是编一个窄区间
  4) 目标分子若也在校准集里 → 标 self_calibrated（不参与覆盖率统计）
  5) 无实测真值 → 不可用
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adt import conformal as CP  # noqa: E402

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


print("== 1) 分位秩与 q ==")
pairs = [(0.0, float(i)) for i in range(1, 101)]      # |残差| = 1..100
c = CP.calibrate(pairs, alpha=0.1)
check("k=ceil(101×0.9)=91", c["k"] == 91, c["k"])
check("q=91", abs(c["q"] - 91.0) < 1e-9, c["q"])
check("经验覆盖率 0.91 ≥ 0.90", c["empirical"] >= 0.9, c["empirical"])
check("note 声明'构造保证'", "构造保证" in c["note"], c["note"])

print("== 2) 覆盖率性质（随机数据）==")
import random  # noqa: E402
random.seed(7)
ok_all = True
for _ in range(20):
    ps = [(random.gauss(0, 1), random.gauss(0, 1)) for _ in range(200)]
    cc = CP.calibrate(ps, alpha=0.2)
    if cc["empirical"] < 0.8 - 1e-9:
        ok_all = False
check("20 次抽样经验覆盖率均 ≥0.80", ok_all)

print("== 3) 小样本必须退化 ==")
c2 = CP.calibrate([(0, 1), (0, 2), (0, 3)], alpha=0.1)
check("n=3, α=0.1 → degenerate", c2["degenerate"] is True, c2)
check("q=∞", c2["q"] == float("inf"), c2["q"])
check("说明 k>n", "k=" in c2["note"], c2["note"])
lo, hi = CP.predict_one(5.0, c2)
check("区间为 (-∞, +∞)", lo == -float("inf") and hi == float("inf"), (lo, hi))

print("== 4) 目标/校准重叠标记 ==")
pred = [dict(compound_id="T%02d" % i, endpoint="e", value=str(i + 0.4),
             unit="x", domain_flag="predicted") for i in range(10)]
pred.append(dict(compound_id="Z", endpoint="e", value="5.0", unit="x",
                 domain_flag="predicted"))
truth = [dict(compound_id="T%02d" % i, endpoint="e", truth_value=str(i + 0.5))
         for i in range(10)]
rows, summ = CP.build(pred, truth, "e", alpha=0.2, min_n=5)
by = {r["compound_id"]: r for r in rows}
check("有 11 个目标分子", len(rows) == 11, len(rows))
check("T00/T05 标 self_calibrated", by["T00"]["flag"] == "self_calibrated"
      and by["T05"]["flag"] == "self_calibrated",
      (by["T00"]["flag"], by["T05"]["flag"]))
check("Z 为正常预测", by["Z"]["flag"] == "ok", by["Z"]["flag"])
check("区间覆盖点估计", float(by["Z"]["lo"]) <= 5.0 <= float(by["Z"]["hi"]), by["Z"])
check("区间宽度 = 2q", abs(float(by["Z"]["width"]) - 2 * float(by["Z"]["q"])) < 1e-6,
      by["Z"])
check("summary 记录 self 数", summ["n_self_calibrated"] == 10, summ)

print("== 5) 无实测 ==")
rows2, summ2 = CP.build(pred, [], "e", alpha=0.2, min_n=2)
check("无可校准 → insufficient", summ2["flag"] == "insufficient", summ2)
check("n_cal=0", summ2["n_cal"] == 0, summ2)

print("== 6) 量纲无关：非概率端点同样适用 ==")
c3 = CP.calibrate([(0.0, 1.0), (0.0, 2.0), (0.0, 3.0), (0.0, 4.0)], alpha=0.25)
check("α=0.25, n=4 → k=4, q=4", c3["k"] == 4 and abs(c3["q"] - 4.0) < 1e-9, c3)

print()
print("passed %d / failed %d" % (PASS, len(FAIL)))
if FAIL:
    print("FAILED:", FAIL)
    sys.exit(1)
print("ALL OK")
