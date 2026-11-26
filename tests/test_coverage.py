# -*- coding: utf-8 -*-
"""v2.3 覆盖率矩阵测试（合成数据）。

验收点：
  1) 有值比例决定 flag（usable / insufficient_coverage / no_prediction）
  2) 全 NoPrediction 绝不能读作阴性（flag 必须单独标出）
  3) 整源平均覆盖率 <0.30 -> background_only（G6）
  4) 所有源都没有可判值的端点 -> 进入 zero_endpoints

跑法: python tests/test_coverage.py
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from adt import schema          # noqa: E402
from adt.coverage import build  # noqa: E402

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


def m(cid, ep, src, v="0.5", flag="predicted"):
    return schema.measurement(cid, ep, v, "class", src, "t", flag)


rows = []
# 源 A：endpoint x 5 个里 3 个可判；endpoint y 全 NoPrediction
for i in range(3):
    rows.append(m("C%d" % i, "x", "A"))
for i in range(3, 5):
    rows.append(m("C%d" % i, "x", "A", v="", flag="out_of_domain"))
for i in range(5):
    rows.append(m("C%d" % i, "y", "A", v="", flag="out_of_domain"))
# 源 B：endpoint x 5 个里 1 个可判（低覆盖）
rows.append(m("C0", "x", "B"))
for i in range(1, 5):
    rows.append(m("C%d" % i, "x", "B", v="", flag="out_of_domain"))
# 源 B 的 endpoint y 全零
for i in range(5):
    rows.append(m("C%d" % i, "y", "B", v="", flag="out_of_domain"))

matrix, summ = build(rows)
by = {(r["source"], r["endpoint"]): r for r in matrix}

print("== 1) flag 分档 ==")
check("A/x 覆盖 0.6 -> usable", by[("A", "x")]["flag"] == "usable",
      str(by[("A", "x")]))
check("B/x 覆盖 0.2 -> insufficient_coverage",
      by[("B", "x")]["flag"] == "insufficient_coverage", str(by[("B", "x")]))
check("A/y 全域外 -> no_prediction", by[("A", "y")]["flag"] == "no_prediction",
      str(by[("A", "y")]))

print("== 2) 全 NoPrediction 不得读作阴性 ==")
check("no_prediction 行 note 明确写'不得读作阴性'",
      "不得读作阴性" in by[("A", "y")]["note"], by[("A", "y")]["note"])
check("n_usable=0 且 n_out_of_domain=5",
      by[("A", "y")]["n_usable"] == 0 and by[("A", "y")]["n_out_of_domain"] == 5)

print("== 3) 整源判定（G6）==")
check("源 A 覆盖 0.3 -> 边界值判 usable（>=0.30）",
      summ["by_source"]["A"]["coverage"] >= 0.30, str(summ["by_source"]["A"]))
check("源 B 覆盖 <0.30 -> background_only",
      summ["by_source"]["B"]["verdict"] == "background_only",
      str(summ["by_source"]["B"]))

print("== 4) 端点级汇总 ==")
check("x 的端点级覆盖 = 4/10 = 0.4",
      abs(summ["by_endpoint"]["x"] - 0.4) < 1e-9, str(summ["by_endpoint"]["x"]))
check("y 进入 zero_endpoints（两源都零）",
      "y" in summ["zero_endpoints"], str(summ["zero_endpoints"]))

print()
print("passed %d / failed %d" % (PASS, len(FAIL)))
if FAIL:
    print("FAILED:", FAIL)
    sys.exit(1)
print("ALL OK")
