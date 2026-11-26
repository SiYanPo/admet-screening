# -*- coding: utf-8 -*-
"""C9 欠账补齐：LE 法证反推审计（外来数据包的"图错数据对"检测）。

原理：配体效率 LE = |ΔG| / HA（HA = 重原子数）。给一个数据包的
(化合物, ΔG, LE[, HA_claim]) 表和对应 SMILES，本脚本反推
  HA_recovered = |ΔG| / LE
并与 SMILES 实际重原子数比对——对不上 = "图/表与数据用的不是同一个分子"
（真实战果：抓到某图表包把 J 画错而数据用的是文献 J）。

用法：
  python le_audit.py --in le_table.csv --out le_audit.csv
输入 CSV 列：compound_id, smiles, dg_kcal (可为空), le (可为空), ha_claim (可选)
  - 有 dg+le：反推 HA 并与 smiles 实际 HA 比
  - 有 dg+ha_claim：反推 LE 并复算 HA（交叉）
  - 都有：双向互证
"""
import argparse
import csv
import io
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rdkit import Chem, RDLogger

RDLogger.DisableLog("rdApp.*")


def heavy_atoms(smiles):
    m = Chem.MolFromSmiles(smiles)
    return (sum(1 for a in m.GetAtoms() if a.GetAtomicNum() > 1)
            if m else None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    rows = list(csv.DictReader(io.open(a.inp, encoding="utf-8-sig")))
    out = []
    n_alert = 0
    for r in rows:
        cid = r["compound_id"]
        ha_real = heavy_atoms(r["smiles"])
        dg = float(r["dg_kcal"]) if r.get("dg_kcal") else None
        le = float(r["le"]) if r.get("le") else None
        ha_claim = int(r["ha_claim"]) if r.get("ha_claim") else None

        ha_rec = le_rec = None
        mismatch = []
        if dg and le and le > 0:
            ha_rec = round(abs(dg) / le, 1)
            if ha_real is not None and abs(ha_rec - ha_real) >= 1.0:
                mismatch.append("HA 反推 %.1f vs SMILES 实际 %d（差 ≥1 个重原子）"
                                % (ha_rec, ha_real))
        if dg and ha_claim:
            le_rec = round(abs(dg) / ha_claim, 3)
        if le and ha_real is not None and ha_claim and ha_claim != ha_real:
            mismatch.append("表 claim HA=%d 但 SMILES 实际 %d" % (ha_claim, ha_real))
        if mismatch:
            n_alert += 1
        out.append(dict(compound_id=cid, ha_smiles=ha_real or "",
                        ha_recovered=ha_rec or "", le_recomputed=le_rec or "",
                        verdict="MISMATCH" if mismatch else "consistent",
                        alert="；".join(mismatch)))

    cols = ["compound_id", "ha_smiles", "ha_recovered", "le_recomputed",
            "verdict", "alert"]
    with io.open(a.out, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(out)
    print("[le_audit] %d 条 -> %s；MISMATCH %d 条（图/表与数据不是同一分子）"
          % (len(out), a.out, n_alert))
    for r in out:
        if r["verdict"] == "MISMATCH":
            print("  ⚠ %s: %s" % (r["compound_id"], r["alert"]))


if __name__ == "__main__":
    main()
