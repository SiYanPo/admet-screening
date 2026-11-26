# -*- coding: utf-8 -*-
"""名次区间 + 并列集合测试（移植 E7c 的验收点）。

验收点：
  1) n<30 时 status.ok=False（拒绝排名）
  2) 名次区间 p05 <= median <= p95，且排序正确（A>B>C）
  3) 两个完全相同的分子必须判并列（胜率 0.5，tie=Y）—— 曾因按名次而非 composite
     算胜率而误判
  4) 明确优劣对不并列

跑法: python tests/test_rank.py
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from adt import rank as rk  # noqa: E402

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


def rows_of(data):
    out = []
    for c, d in data.items():
        for g, v in d.items():
            out.append(dict(compound_id=c, axis=g, geo_mean=v))
    return out


print("== 1) underpowered 拒绝 ==")
data = {"A": {"s": 1.0, "e": 1.0, "t": 1.0},
        "B": {"s": 0.9, "e": 0.9, "t": 0.9},
        "C": {"s": 1.0, "e": 0.2, "t": 0.9}}
out, pairs, st = rk.build(rows_of(data), bootstrap=500, score_col="geo_mean")
check("n=3<30 -> ok=False", st["ok"] is False, str(st))
check("mode=refused", st["mode"] == "refused", st["mode"])

print("== 2) 排序与区间 ==")
bymed = {r["compound_id"]: r for r in out}
check("A 名次最好（median 1）", bymed["A"]["median_rank"] == 1.0, str(bymed["A"]))
for c in ("A", "B", "C"):
    r = bymed[c]
    check("%s p05<=median<=p95" % c,
          r["rank_p05"] <= r["median_rank"] <= r["rank_p95"], str(r))

print("== 3) 相同分子必须并列 ==")
data2 = {"A": {"s": 0.8, "e": 0.8, "t": 0.8},
         "B": {"s": 0.8, "e": 0.8, "t": 0.8},
         "C": {"s": 0.2, "e": 0.2, "t": 0.2}}
out2, pairs2, _ = rk.build(rows_of(data2), bootstrap=500, score_col="geo_mean")
tie_ab = [p for p in pairs2 if {p["a"], p["b"]} == {"A", "B"}][0]
check("A vs B 胜率=0.5", abs(tie_ab["win_rate"] - 0.5) < 1e-9, str(tie_ab))
check("A vs B 判并列", tie_ab["tie"] == "Y", str(tie_ab))
tg = {r["compound_id"]: r["tie_group"] for r in out2}
check("A、B 同一并列组", tg["A"] == tg["B"] != "", str(tg))

print("== 4) 明确优劣不并列 ==")
tie_ac = [p for p in pairs2 if {p["a"], p["b"]} == {"A", "C"}][0]
check("A vs C 不并列（胜率=1.0）",
      tie_ac["tie"] == "N" and abs(tie_ac["win_rate"] - 1.0) < 1e-9, str(tie_ac))

print()
print("passed %d / failed %d" % (PASS, len(FAIL)))
if FAIL:
    print("FAILED:", FAIL)
    sys.exit(1)
print("ALL OK")
