# -*- coding: utf-8 -*-
"""PBPK MC 排名概率测试（移植外部会话 exp8-A 的验收点）。

验收点：
  1) p_top / p_bottom ∈ [0,1]
  2) Σ p_top ≈ top（每次模拟恰好 top 个进前 top）
  3) 清除率最低（Cmax 最高）的分子 p_top 最大、平均名次最好
  4) 结果按平均名次升序

跑法: python tests/test_pbpk_mcrank.py   （n 取小值以求快）
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from adt.pbpk import mc_rank_probability  # noqa: E402

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


# 5 个合成分子的 clint 从低到高：低清除 -> Cmax 高 -> 名次好
pairs = [
    ("LOW", 600.0, 0.0, 5.0, 30.0),
    ("B", 600.0, 0.0, 15.0, 30.0),
    ("C", 600.0, 0.0, 30.0, 30.0),
    ("D", 600.0, 0.0, 50.0, 30.0),
    ("HIGH", 600.0, 0.0, 80.0, 30.0),
]
out = mc_rank_probability(pairs, dose_mg=100.0, n=80, seed=11, top=2)
by = {r["compound_id"]: r for r in out}

check("返回 5 个分子", len(out) == 5, len(out))
check("p_top∈[0,1]", all(0.0 <= r["p_top"] <= 1.0 for r in out),
      [r["p_top"] for r in out])
check("p_bottom∈[0,1]", all(0.0 <= r["p_bottom"] <= 1.0 for r in out),
      [r["p_bottom"] for r in out])
s = sum(r["p_top"] for r in out)
check("Σp_top≈top(2)（每次恰 2 个进前 2；容差含 3 位舍入）", abs(s - 2.0) < 0.02, s)
check("低清除 LOW 的 p_top 最大",
      by["LOW"]["p_top"] == max(r["p_top"] for r in out),
      {k: v["p_top"] for k, v in by.items()})
check("低清除 LOW 平均名次最好", by["LOW"]["mean_rank"] == min(r["mean_rank"] for r in out),
      {k: v["mean_rank"] for k, v in by.items()})
check("按平均名次升序",
      all(out[i]["mean_rank"] <= out[i + 1]["mean_rank"] for i in range(len(out) - 1)),
      [r["mean_rank"] for r in out])

print()
print("passed %d / failed %d" % (PASS, len(FAIL)))
if FAIL:
    print("FAILED:", FAIL)
    sys.exit(1)
print("ALL OK")
