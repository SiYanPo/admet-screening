# -*- coding: utf-8 -*-
"""C62/C63 回归：饱和结论写回长表后，语义必须保持"可判阈值、不可排序"。

此前两个缺陷：
  1) `saturated` 是合法 domain_flag，但**没有写入路径**（契约漂移）；
  2) 即使写回，reliab 的 in_domain 集合不含 saturated，会把正确的
     红旗结论退化成"全部源域外 UNDETERMINED"。

跑法: python tests/test_saturation_mark.py
"""
import csv
import io
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from adt import schema                       # noqa: E402
from adt.cli import _mark_measurements       # noqa: E402
from adt.reliability import evaluate         # noqa: E402

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


tmp = tempfile.mkdtemp(prefix="satmark_")
src = os.path.join(tmp, "measurements.csv")
rows = [
    schema.measurement("X", "herg", 0.62, "probability", "s1"),
    schema.measurement("X", "herg", 0.71, "probability", "s2"),
    schema.measurement("X", "dili", 0.9, "probability", "s1"),
]
schema.write_measurements(src, rows)

print("== 1) 写回：宽表列名 hERG 与长表端点 herg 必须能对上 ==")
out = _mark_measurements(src, tmp, {"hERG"}, set())
res = list(csv.DictReader(io.open(out, encoding="utf-8-sig")))
flags = {r["endpoint"]: r["domain_flag"] for r in res}
check("herg 被标 saturated", flags["herg"] == "saturated", str(flags))
check("未涉及的 dili 保持 predicted", flags["dili"] == "predicted", str(flags))

print("== 2) 裁决：saturated 仍可判阈值，但 confidence=low 且禁排序 ==")
RULES = {"herg": {"shape": "down", "pass": 0.1, "fail": 0.5, "require_sources": 1}}
rel = evaluate(res, RULES)
h = [r for r in rel if r["endpoint"] == "herg"][0]
check("verdict=FAIL（0.665 > 0.5，未被当域外丢弃）", h["verdict"] == "FAIL",
      str(h["verdict"]))
check("confidence=low", h["confidence"] == "low", h["confidence"])
check("reason 写明不能排序", "不能排序" in h["reason"], h["reason"])

print("== 3) invalid 的数值必须降级为 error（禁止下游使用）==")
src2 = os.path.join(tmp, "m2.csv")
schema.write_measurements(src2, [schema.measurement("Y", "caco2", -13.4, "log",
                                                    "dp")])
out2 = _mark_measurements(src2, tmp, set(), {"caco2"})
r2 = list(csv.DictReader(io.open(out2, encoding="utf-8-sig")))[0]
check("flag=error", r2["domain_flag"] == "error", r2["domain_flag"])
check("note 留下降级原因", "invalid" in r2["note"], r2["note"])

print()
print("passed %d / failed %d" % (PASS, len(FAIL)))
if FAIL:
    print("FAILED:", FAIL)
    sys.exit(1)
print("ALL OK")
