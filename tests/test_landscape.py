# -*- coding: utf-8 -*-
"""工作包 K 测试：可靠性生态位分工表。

跑法: python tests/test_landscape.py
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from adt import landscape as L  # noqa: E402

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


cfg = os.path.join(HERE, "references", "reliability_landscape.yaml")
thesis, rows = L.load(cfg)
check("thesis 含'证据准入'", "证据准入" in thesis, thesis)
check("6 条策略", len(rows) == 6, str(len(rows)))
names = " ".join(r["strategy"] for r in rows)
for key in ("多数投票", "适用域", "Conformal", "校准", "Dempster", "本框架"):
    check("含 %s" % key, key in names, names)
check("每条有 solves/does_not_solve/relation",
      all(r.get("solves") and r.get("does_not_solve") and r.get("relation")
          for r in rows))
md = L.markdown(thesis, rows)
check("Markdown 有表头", "| 策略 |" in md, md[:80])
check("Markdown 含本框架", "本框架" in md)

print()
if FAIL:
    print("FAILED: %d 条 -> %s" % (len(FAIL), FAIL))
    sys.exit(1)
print("ALL PASS (%d assertions)" % PASS)
