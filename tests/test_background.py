# -*- coding: utf-8 -*-
"""稳健 Z 背景归一化测试（移植 E6a 的验收点）。

验收点：
  1) MAD 尺度抗单点（一个极端值不把 scale 抬高）
  2) SCALE_CONFLICT 在 z_mad 与 z_sd 差 >1.5 时必须触发
  3) 背景 n < min_bg -> BG_TOO_FEW，不计算 Z
  4) 域外/空值 -> missing，不赋分
  5) within-set 留一法：背景不含自身
  6) 定向：shape=up -> z_favorable=+z；shape=down -> -z

跑法: python tests/test_background.py
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from adt import background as bg  # noqa: E402

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


def row(cid, ep, v, flag="predicted"):
    return dict(compound_id=cid, endpoint=ep, value=v, unit="", domain_flag=flag)


print("== 1) MAD 抗单点 ==")
vals = [1, 2, 3, 4, 5, 6, 7, 8, 100]
c, s, m, d = bg.robust_scale(vals, "mad", 0.30)
check("median=5", abs(c - 5.0) < 1e-9, str(c))
check("MAD scale=1.4826*2=2.965（< SD）", abs(s - 2.9652) < 1e-3, str(s))
_, s_sd, _, _ = bg.robust_scale(vals, "sd", 0.30)
check("SD scale 被极端值抬高（>10）", s_sd > 10, str(s_sd))
check("MAD 远小于 SD（稳健）", s < s_sd / 5, "%s vs %s" % (s, s_sd))

print("== 2) SCALE_CONFLICT ==")
# 背景含一个极端值 -> MAD 小、SD 大 -> 同一个 S 的 z 与 z_sd 差异大
rows = [row("X", "e", "10", "predicted")]
bgrows = [row("b%d" % i, "e", str(v)) for i, v in enumerate([1, 2, 3, 4, 5, 100])]
out = bg.build(rows, bgrows, {"e": {"shape": "up"}}, min_bg=5)
r = out[0]
check("SCALE_CONFLICT 触发", "SCALE_CONFLICT" in r["qc_flag"], r["qc_flag"])
check("同时报 z 与 z_sd（不静默取一个）",
      r["z"] != "" and r["z_sd"] != "", "%s / %s" % (r["z"], r["z_sd"]))

print("== 3) BG_TOO_FEW ==")
out2 = bg.build(rows, bgrows[:3], {"e": {"shape": "up"}}, min_bg=5)
check("n<min_bg -> BG_TOO_FEW 且无 Z",
      out2[0]["flag"] == "BG_TOO_FEW" and out2[0]["z"] == "", str(out2[0]))

print("== 4) 缺失不赋分 ==")
out3 = bg.build([row("Y", "e", "", "out_of_domain")], bgrows, {"e": {"shape": "up"}},
                min_bg=5)
check("out_of_domain -> missing，无 Z",
      out3[0]["flag"] == "missing" and out3[0]["z"] == "", str(out3[0]))

print("== 5) within-set 留一法 ==")
tgt = [row("A", "e", "1"), row("B", "e", "2"), row("C", "e", "3"), row("D", "e", "4")]
out4 = bg.build(tgt, None, {"e": {"shape": "up"}}, min_bg=2, within_set=True)
check("每个分子背景 = n-1 = 3",
      all(r["n_bg"] == 3 for r in out4), [r["n_bg"] for r in out4])

print("== 6) 定向 ==")
out_up = bg.build([row("S", "e", "10")], bgrows, {"e": {"shape": "up"}}, min_bg=5)[0]
out_dn = bg.build([row("S", "e", "10")], bgrows, {"e": {"shape": "down"}}, min_bg=5)[0]
check("up: z_favorable = +z", abs(float(out_up["z_favorable"]) - float(out_up["z"])) < 1e-9,
      "%s vs %s" % (out_up["z_favorable"], out_up["z"]))
check("down: z_favorable = -z", abs(float(out_dn["z_favorable"]) + float(out_dn["z"])) < 1e-9,
      "%s vs %s" % (out_dn["z_favorable"], out_dn["z"]))

print()
print("passed %d / failed %d" % (PASS, len(FAIL)))
if FAIL:
    print("FAILED:", FAIL)
    sys.exit(1)
print("ALL OK")
