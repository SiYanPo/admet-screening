# -*- coding: utf-8 -*-
"""重新计算 v3 外审材料所需的 A/B/I 真实数字，并落盘为可复现 artifact。

A. 独立性：baseline_rdkit vs baseline_morgan 两独立方法组，逐端点 Spearman rho
   （independence 模块默认只过滤 prob/class 单位故对 OpenADMET 连续端点返回 0 对，
    这里直接用 independence.spearman 在连续预测上重算，证明"模块存在且可被量化"）
B. 框架裁决分布：out_ext/reliability.csv 的 PASS/FAIL/UNDETERMINED 计数（2282 x 9）
I. 确定性修饰符分布：out_review/certainty.csv 的 certainty_modifier 计数
"""
import csv
import json
import os

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "out_review")
import sys
sys.path.insert(0, ROOT)
from adt import independence

# ---------- A: 逐端点 Spearman rho ----------
base_rd = os.path.join(ROOT, "out_ext", "measurements_baseline_rdkit.csv")
base_mo = os.path.join(ROOT, "out_ext", "measurements_baseline_morgan.csv")


def load(path):
    rows = {}
    with open(path, encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            key = (r["compound_id"], r["endpoint"])
            try:
                rows[key] = float(r["value"])
            except (ValueError, KeyError, TypeError):
                pass
    return rows


rd = load(base_rd)
mo = load(base_mo)
common = sorted(set(rd) & set(mo))
# 按端点聚合
by_ep = {}
for k in common:
    by_ep.setdefault(k[1], ([], []))
    by_ep[k[1]][0].append(rd[k])
    by_ep[k[1]][1].append(mo[k])

a_rows = []
rho_list = []
for ep, (x, y) in sorted(by_ep.items()):
    if len(x) >= 10:
        rho = independence.spearman(x, y)
        a_rows.append(dict(endpoint=ep, n=len(x), spearman=round(rho, 3),
                           one_minus_rho=round(1 - rho, 3)))
        rho_list.append(rho)
a_rows.sort(key=lambda d: d["spearman"])
with open(os.path.join(OUT, "independence_recompute.csv"), "w", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=["endpoint", "n", "spearman", "one_minus_rho"])
    w.writeheader()
    w.writerows(a_rows)
print("A. 逐端点 Spearman rho (rdkit vs morgan):")
for r in a_rows:
    print("   %-22s n=%-5d rho=%.3f  (1-rho=%.3f)" % (r["endpoint"], r["n"], r["spearman"], r["one_minus_rho"]))
if rho_list:
    print("   中位 rho = %.3f ; 1-rho 区间 = %.2f–%.2f" % (
        float(np.median(rho_list)), min(1 - x for x in rho_list), max(1 - x for x in rho_list)))

# ---------- B: 框架裁决分布 ----------
rel = os.path.join(ROOT, "out_ext", "reliability.csv")
counts = {"PASS": 0, "FAIL": 0, "UNDETERMINED": 0}
with open(rel, encoding="utf-8-sig") as fh:
    for r in csv.DictReader(fh):
        v = (r.get("verdict") or "").strip()
        if v in counts:
            counts[v] += 1
total = sum(counts.values())
print("\nB. 框架裁决分布 (out_ext/reliability.csv, n=%d):" % total)
for k in ("PASS", "FAIL", "UNDETERMINED"):
    print("   %-14s %6d  (%.1f%%)" % (k, counts[k], 100.0 * counts[k] / total))

# ---------- I: 确定性修饰符分布 ----------
cert = os.path.join(OUT, "certainty.csv")
cm = {}
with open(cert, encoding="utf-8-sig") as fh:
    for r in csv.DictReader(fh):
        m = (r.get("certainty_modifier") or "").strip()
        if m:
            cm[m] = cm.get(m, 0) + 1
ctot = sum(cm.values())
print("\nI. certainty_modifier 分布 (certainty.csv, n=%d):" % ctot)
for k in sorted(cm, key=lambda x: -cm[x]):
    print("   %-22s %6d  (%.1f%%)" % (k, cm[k], 100.0 * cm[k] / ctot))

out = dict(A=dict(rows=a_rows, median_rho=float(np.median(rho_list)) if rho_list else None,
                  one_minus_rho_range=[min(1 - x for x in rho_list), max(1 - x for x in rho_list)]),
           B=dict(total=total, **counts, pct=dict(
               PASS=round(100.0 * counts["PASS"] / total, 1),
               FAIL=round(100.0 * counts["FAIL"] / total, 1),
               UNDETERMINED=round(100.0 * counts["UNDETERMINED"] / total, 1))),
           I=dict(total=ctot, dist=cm, pct={k: round(100.0 * v / ctot, 1) for k, v in cm.items()}))
with open(os.path.join(OUT, "review_numbers_A_B_I.json"), "w", encoding="utf-8") as fh:
    json.dump(out, fh, ensure_ascii=False, indent=2)
print("\n已落盘: out_review/independence_recompute.csv, out_review/review_numbers_A_B_I.json")
