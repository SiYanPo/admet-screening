# -*- coding: utf-8 -*-
"""工作包 J 测试：失效模式检测 + precision/recall。

跑法: python tests/test_failure_modes.py
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from adt import failure_modes as F  # noqa: E402

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


def m(cid, ep, src, v, unit="probability", flag="predicted", ver="1.0"):
    return dict(compound_id=cid, endpoint=ep, value=str(v), unit=unit,
                source=src, source_version=ver, domain_flag=flag)


print("== 1) 单位异构 ==")
rows = [m("X", "DILI", "s1", 0.9, "probability"),
        m("X", "DILI", "s2", 1, "class")]
h = F.detect(rows, rules={})
check("检出 unit_isomerism",
      any(x["mode"] == "unit_isomerism" for x in h), str(h))

print("== 2) 物理边界（大写端点要能匹配 rule） ==")
rows2 = [m("X", "DILI", "s1", 5.0, "probability")]
rules = {"dili": dict(phys_range=[0, 1])}
h2 = F.detect(rows2, rules=rules)
check("检出 phys_range_violation",
      any(x["mode"] == "phys_range_violation" for x in h2), str(h2))

print("== 3) 版本漂移 ==")
rows3 = [m("X", "DILI", "s1", 0.2, ver="2.0.1-local"),
         m("X", "DILI", "s1", 0.3, ver="2.0")]
h3 = F.detect(rows3, rules={})
check("检出 version_drift",
      any(x["mode"] == "version_drift" for x in h3), str(h3))

print("== 4) 门控绕过（PASS 但独立组不足） ==")
rel = [dict(compound_id="X", endpoint="DILI", verdict="PASS", n_indep_groups=1)]
h4 = F.detect([], reliability=rel, rules={"dili": dict(require_sources=2)})
check("检出 single_group_verdict",
      any(x["mode"] == "single_group_verdict" for x in h4), str(h4))

print("== 5) 域外端点未接线 ==")
reg = dict(sources=[dict(name="s1", blocked_endpoints_in_class={
    "cls": [dict(endpoint="DILI", evidence="14/14")]})])
h5 = F.detect(rows2, rules={}, registry=reg, chemical_class="cls")
check("检出 domain_block_unwired",
      any(x["mode"] == "domain_block_unwired" for x in h5), str(h5))

print("== 6) 静默空源 ==")
h6 = F.detect([m("X", "DILI", "s1", 0.2)], rules={},
              expect_sources=["s1", "s2"])
check("检出 silent_empty_source",
      any(x["mode"] == "silent_empty_source" for x in h6), str(h6))

print("== 7) precision / recall ==")
hits = [dict(mode="A", compound_id="X", endpoint="e", source="", detail=""),
        dict(mode="B", compound_id="Y", endpoint="e", source="", detail="")]
labels = [dict(mode="A", compound_id="X", endpoint="e", is_failure="1"),
          dict(mode="A", compound_id="Z", endpoint="e", is_failure="1"),
          dict(mode="B", compound_id="Y", endpoint="e", is_failure="1")]
ev = F.evaluate_detectors(hits, labels)
a = ev["per_mode"]["A"]
check("A precision=1.0", a["precision"] == 1.0, str(a))
check("A recall=0.5", a["recall"] == 0.5, str(a))
b = ev["per_mode"]["B"]
check("B recall=1.0", b["recall"] == 1.0, str(b))
check("label_source=labels", ev["label_source"] == "labels", str(ev))

print("== 8) 无标签只报计数 ==")
ev2 = F.evaluate_detectors(hits, None)
check("precision=None", ev2["per_mode"]["A"]["precision"] is None, str(ev2))
check("label_source=none", ev2["label_source"] == "none", str(ev2))

print()
if FAIL:
    print("FAILED: %d 条 -> %s" % (len(FAIL), FAIL))
    sys.exit(1)
print("ALL PASS (%d assertions)" % PASS)
