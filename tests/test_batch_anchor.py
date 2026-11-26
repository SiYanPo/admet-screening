# -*- coding: utf-8 -*-
"""C56 回归测试：B1 跨批锚点必须**每批强制执行**（离线，用桩替代网络）。

验收点：
  1) Adapter.run() 在跑分子之前调用 pre_batch（顺序断言）
  2) 有漂移 -> meta["batch_drift"] 非空，且日志可见
  3) BioTransformerAdapter.pre_batch 按 option 展开 controls，并标出出界项

跑法: python tests/test_batch_anchor.py
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from adt.adapters.base import Adapter, AdapterResult          # noqa: E402
from adt.adapters.biotransformer import BioTransformerAdapter  # noqa: E402

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


class FakeAdapter(Adapter):
    name = "fake"

    def __init__(self, drift):
        Adapter.__init__(self, verbose=False)
        self.drift = drift
        self.order = []

    def pre_batch(self, compounds, chemical_class="", **kw):
        self.order.append("pre_batch")
        return [dict(source=self.name, option="X", control="c1", observed=1,
                     expected_min=5, expected_max=99, drift=self.drift)]

    def run_one(self, compound, chemical_class="", **kw):
        self.order.append("run_one")
        return AdapterResult([])


print("== 1) pre_batch 先于 run_one 执行 ==")
a = FakeAdapter(drift="")
res = a.run([dict(compound_id="P", calc_smiles="CCO")])
check("顺序 = pre_batch -> run_one", a.order[:2] == ["pre_batch", "run_one"], str(a.order))
check("batch_qa 进入 meta", len(res.meta.get("batch_qa", [])) == 1, str(res.meta))
check("无漂移时 meta 无 batch_drift", "batch_drift" not in res.meta, str(res.meta))

print("== 2) 出界 -> batch_drift 标记 ==")
b = FakeAdapter(drift="c1=1 不在 [5,99]")
res2 = b.run([dict(compound_id="P", calc_smiles="CCO")])
check("batch_drift 有 1 条", len(res2.meta.get("batch_drift", [])) == 1, str(res2.meta))

print("== 3) bt 的 pre_batch 按 option 展开 controls（桩掉网络）==")
bt = BioTransformerAdapter(verbose=False, options=["CYP450", "PHASEII"])
bt.control = lambda option="CYP450", controls=("acetaminophen", "phenol"): {
    "acetaminophen": 6 if option == "CYP450" else 1, "phenol": 2}
bt._expected = lambda cid, opt: (5.0, 99.0) if opt == "CYP450" else (None, None)
qa = bt.pre_batch([])
check("2 个 option × 2 个对照 = 4 条 QA", len(qa) == 4, str(len(qa)))
dr = [q for q in qa if q["drift"]]
check("出界项被标 drift（CYP450 的 phenol=2 < 5；PHASEII 无期望区间不判）",
      len(dr) == 1 and dr[0]["control"] == "phenol", str(dr))
check("QA 记录含期望区间", all("expected_min" in q for q in qa))

print("== 4) 化学类白名单仍优先（被禁类不跑对照，不浪费配额）==")
c = FakeAdapter(drift="")
c.reg = dict(blocked_classes=[{"class": "forbidden", "reason": "test"}])
res3 = c.run([dict(compound_id="P", calc_smiles="CCO")], chemical_class="forbidden")
check("被禁类直接 SKIP", res3.meta.get("skipped") == "test", str(res3.meta))
check("被禁类未调 pre_batch", c.order == [], str(c.order))

print()
print("passed %d / failed %d" % (PASS, len(FAIL)))
if FAIL:
    print("FAILED:", FAIL)
    sys.exit(1)
print("ALL OK")
