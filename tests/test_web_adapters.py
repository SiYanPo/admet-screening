# -*- coding: utf-8 -*-
"""网页源适配器（admet_ai / admetlab3 / vnn / protox3）的离线逻辑测试。

设计说明（为什么可以离线测）：适配器的 `fetch()` 是唯一触网的部分，
把 `fetch()` 桩掉之后，**对齐、列映射、未映射列审计、人工桥契约**全部是纯逻辑，
可以也必须离线测——否则每次改列映射都要打满限流配额。

跑法: python tests/test_web_adapters.py
"""
import csv
import io
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from adt.adapters.admet_ai import AdmetAIAdapter        # noqa: E402
from adt.adapters.admetlab3 import AdmetlabAdapter      # noqa: E402
from adt.adapters.protox3 import molblock              # noqa: E402
from adt.adapters.vnn import VnnAdapter                 # noqa: E402

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


COMPS = [dict(compound_id="APAP", calc_smiles="CC(=O)NC1=CC=C(O)C=C1"),
         dict(compound_id="CAF", calc_smiles="CN1C=NC2=C1C(=O)N(C)C(=O)N2C")]

print("== 1) ADMET-AI：canonical SMILES 对齐 + 只映射已登记列 ==")
ai = AdmetAIAdapter(verbose=False)
ai.fetch = lambda smis: ([
    dict(smiles="CC(=O)Nc1ccc(O)cc1", DILI="0.2852", AMES="0.2467",
         hERG="0.0793", QED="0.55"),
    dict(smiles="Cn1cnc2c1c(=O)n(C)c(=O)n2C", DILI="0.8746", AMES="0.1819",
         hERG="0.1149"),
    dict(smiles="CCCC", DILI="0.5"),          # 不在本批 -> 必须被丢弃
], "http://x")
r = ai.run(COMPS)
eps = {(m["compound_id"], m["endpoint"]) for m in r.measurements}
check("2 分子 × 3 端点 = 6 行", len(r.measurements) == 6, str(len(r.measurements)))
check("APAP 的 dili 已对齐", ("APAP", "dili") in eps, str(sorted(eps)))
check("未映射列（QED）不入长表",
      all(m["endpoint"] != "QED" for m in r.measurements))
check("未映射列在 meta 里可见", "QED" in r.meta.get("unmapped_columns", []),
      str(r.meta.get("unmapped_columns")))
check("批外分子被丢弃（unmatched 记录）", len(r.meta.get("unmatched_smiles", [])) == 1,
      str(r.meta.get("unmatched_smiles")))

print("== 2) ADMETlab：行序不可信，必须按 canonical SMILES 对齐 ==")
lab = AdmetlabAdapter(verbose=False)
lab.fetch = lambda smis: ([
    dict(raw_smiles="CN1C=NC2=C1C(=O)N(C)C(=O)N2C", smiles="Cn1cnc2c1c(=O)n(C)c(=O)n2C",
         DILI="0.61", Ames="0.72", hERG="0.31"),
    dict(raw_smiles="CC(=O)NC1=CC=C(O)C=C1", smiles="CC(=O)Nc1ccc(O)cc1",
         DILI="0.12", Ames="0.9", hERG="0.05"),
], "http://y")
r2 = lab.run(COMPS)
d = {(m["compound_id"], m["endpoint"]): m["value"] for m in r2.measurements}
check("CAF 拿到自己的值（不是行序第一个）",
      abs(float(d[("CAF", "dili")]) - 0.61) < 1e-9, str(d.get(("CAF", "dili"))))
check("APAP 拿到自己的值", abs(float(d[("APAP", "ames")]) - 0.9) < 1e-9, str(d.get(("APAP", "ames"))))
check("6 行全部映射", len(r2.measurements) == 6, str(len(r2.measurements)))

print("== 3) vNN 人工桥：任务单 + 回填契约 ==")
tmp = tempfile.mkdtemp(prefix="vnn_")
v = VnnAdapter(verbose=False)
p = v.prepare(COMPS, tmp)
check("任务单落盘", os.path.exists(p))
rd = list(csv.DictReader(io.open(p, encoding="utf-8-sig")))
check("任务单 2 行且含 urls", len(rd) == 2 and rd[0]["urls"].startswith("https"))

rb = os.path.join(tmp, "readback.csv")
with io.open(rb, "w", encoding="utf-8-sig", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=["compound_id", "endpoint", "value", "unit", "note"])
    w.writeheader()
    w.writerow(dict(compound_id="APAP", endpoint="DILI", value="1", unit="class", note="Yes"))
    w.writerow(dict(compound_id="APAP", endpoint="hERG", value="", unit="class",
                    note="NoPrediction"))
res = v.ingest(rb)
check("别名归一：DILI -> dili", res.measurements[0]["endpoint"] == "dili",
      res.measurements[0]["endpoint"])
check("空值 -> out_of_domain 且不带数值",
      res.measurements[1]["domain_flag"] == "out_of_domain"
      and res.measurements[1]["value"] == "", str(res.measurements[1]))

bad = os.path.join(tmp, "bad.csv")
io.open(bad, "w", encoding="utf-8-sig").write("compound_id,value\nX,1\n")
try:
    v.ingest(bad)
    check("缺列必须报错", False)
except ValueError as exc:
    check("缺列必须报错", "缺列" in str(exc), str(exc))

print("== 4) ProTox：molblock 生成（提交字段要 molblock 不是 SMILES）==")
mb = molblock("CCO")
check("molblock 有 V2000 头", "V2000" in mb.splitlines()[3], mb.splitlines()[:4])
check("molblock 原子数 3（乙醇重原子）", mb.splitlines()[3].split()[0] == "3",
      mb.splitlines()[3])

print()
print("passed %d / failed %d" % (PASS, len(FAIL)))
if FAIL:
    print("FAILED:", FAIL)
    sys.exit(1)
print("ALL OK")
