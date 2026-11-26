# -*- coding: utf-8 -*-
"""U3 回归：TDC 标准切分与真值适配（TDC 2021, NeurIPS, arXiv:2102.09548）。

验收点：
  1) Bemis-Murcko 骨架：同骨架不同取代基 → 同一簇；不同环系 → 不同簇；无环 → ACYCLIC
  2) scaffold_split：**同一骨架绝不跨集**（这是防泄漏的核心断言）
  3) scaffold_split：切分确定（同输入两次结果一致）
  4) load_tdc_truth：Drug_ID/Y → truth_class 映射正确（1=FAIL）
  5) load_tdc_truth：列名缺失时报错而不是静默返回空
"""
import csv
import io
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from adt import benchmark as bm  # noqa: E402

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


print("== 1) 骨架聚类 ==")
comps = [
    dict(compound_id="benzA", smiles="c1ccccc1C(=O)O"),         # 苯甲酸
    dict(compound_id="benzB", smiles="c1ccccc1C(=O)N"),         # 苯甲酰胺 → 同骨架
    dict(compound_id="naph", smiles="c1ccc2ccccc2c1CC(=O)O"),   # 萘 → 不同骨架
    dict(compound_id="acy1", smiles="CCCCCC"),                  # 无环
    dict(compound_id="acy2", smiles="CCCCN"),                   # 无环
    dict(compound_id="bad", smiles="这不是SMILES"),              # 解析失败
]
cl = bm.scaffold_clusters(comps)
by = {r["compound_id"]: r["cluster"] for r in cl}
check("同骨架（苯甲酸/苯甲酰胺）同簇", by["benzA"] == by["benzB"], (by["benzA"], by["benzB"]))
check("不同环系（萘）不同簇", by["naph"] != by["benzA"], (by["naph"], by["benzA"]))
check("无环分子归入 ACYCLIC", by["acy1"] == bm.ACYCLIC and by["acy2"] == bm.ACYCLIC, by["acy1"])
check("解析失败也归 ACYCLIC（不抛异常）", by["bad"] == bm.ACYCLIC, by["bad"])

print("== 2) 整簇切分不跨集 ==")
# 用骨架足够多的批次才能三集都非空（现实里同系类似物系列做不到——见 2b）
rings = ["c1ccccc1", "c1ccc2ccccc2c1", "c1ccncc1", "c1cc[nH]c1",
         "c1ccc2[nH]ccc2c1", "C1CCCCC1", "c1ccoc1", "c1ccsc1"]
many = []
for j, ring in enumerate(rings):
    for i in range(3):
        many.append(dict(compound_id="r%d_%d" % (j, i),
                         smiles=ring + "C" * (i + 1) + "C(=O)O"))
many += [dict(compound_id="a%02d" % i, smiles="C" * (3 + i)) for i in range(5)]
cl2 = bm.scaffold_clusters(many)
sp, info = bm.scaffold_split(cl2)
cross = {}
for r in sp:
    cross.setdefault(r["cluster"], set()).add(r["split"])
bad = {k: v for k, v in cross.items() if len(v) > 1}
check("无骨架跨集", not bad, bad)
check("切分覆盖全部分子", len(sp) == len(many), (len(sp), len(many)))
check("骨架足够多时三集都非空", {r["split"] for r in sp} == {"train", "val", "test"},
      (info["sizes"], info["note"]))

print("== 2b) 骨架太少必须显式报退化 ==")
few = [dict(compound_id="x%d" % i, smiles="c1ccccc1C(=O)O") for i in range(6)]
few += [dict(compound_id="y%d" % i, smiles="c1ccc2ccccc2c1C(=O)O") for i in range(4)]
sp_f, info_f = bm.scaffold_split(bm.scaffold_clusters(few))
cross_f = {}
for r in sp_f:
    cross_f.setdefault(r["cluster"], set()).add(r["split"])
check("退化时仍不跨集", all(len(v) == 1 for v in cross_f.values()), cross_f)
check("degenerate=True", info_f["degenerate"] is True, info_f)
check("空集被列出", bool(info_f["empty_splits"]), info_f)
check("note 说明原因", "无法做三集切分" in info_f["note"], info_f["note"])

print("== 3) 确定性 ==")
sp2, _ = bm.scaffold_split(bm.scaffold_clusters(many))
check("两次切分完全一致", sp == sp2)

print("== 4) TDC 真值适配 ==")
tmp = os.path.join(HERE, "_tdc_tmp.csv")
with io.open(tmp, "w", encoding="utf-8", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["Drug_ID", "Y"])
    w.writerow(["D001", 1])
    w.writerow(["D002", 0])
    w.writerow(["D003", ""])   # 缺失标签：必须跳过
truth, meta = bm.load_tdc_truth(tmp, "DILI")
check("解析 2 条（跳过空标签）", len(truth) == 2, (len(truth), meta))
check("Y=1 -> FAIL", truth[0]["truth_class"] == "FAIL", truth[0])
check("Y=0 -> PASS", truth[1]["truth_class"] == "PASS", truth[1])
check("端点名写入", all(t["endpoint"] == "DILI" for t in truth), truth[0])
check("provenance 指向 TDC", all("tdcommons" in t["provenance_url"] for t in truth), truth[0])

print("== 5) 列名缺失必须报错 ==")
bad_path = os.path.join(HERE, "_tdc_bad.csv")
with io.open(bad_path, "w", encoding="utf-8", newline="") as fh:
    fh.write("foo,bar\n1,2\n")
raised = False
try:
    bm.load_tdc_truth(bad_path, "DILI")
except ValueError as e:
    raised = "id / label" in str(e)
check("缺列 -> ValueError", raised)

for p_ in (tmp, bad_path):
    if os.path.exists(p_):
        os.remove(p_)

print()
print("passed %d / failed %d" % (PASS, len(FAIL)))
if FAIL:
    print("FAILED:", FAIL)
    sys.exit(1)
print("ALL OK")
