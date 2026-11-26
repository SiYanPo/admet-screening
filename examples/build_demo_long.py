# -*- coding: utf-8 -*-
"""构造一张真实的多源长表：14 个分子 × 3 个端点（DILI / Ames / hERG）× 4 个源。

数据全部来自本项目 2026-10-27 的实际运行结果，不是编的：
  W1  admetlab_results.csv        概率 0-1
  W2  web_results/w2_protox.csv   类别 0/1（unit=class）
  W3  web_results/admetai_predictions.csv  概率 0-1
  W5  w5_output/w5_vnnadmet.csv   Yes/No/NoPrediction

用途：验证 s5 可靠性裁决在"四源分歧"这种真实场景下的行为。
"""
import csv
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
sys.path.insert(0, SKILL)
PROJ = os.path.abspath(os.path.join(SKILL, "..", "admet-pipeline"))

from rdkit import Chem  # noqa: E402
from adt import schema  # noqa: E402


def can(s):
    m = Chem.MolFromSmiles(str(s))
    return Chem.MolToSmiles(m) if m else None


def load_names():
    pairs = []
    with io.open(os.path.join(PROJ, "smiles_v5.txt"), encoding="utf-8") as fh:
        for ln in fh:
            if ln.strip() and not ln.startswith("#"):
                p = ln.rstrip("\n").split("\t")
                pairs.append((p[0].strip(), p[1].strip()))
    return pairs


def main():
    pairs = load_names()
    can2name = {can(s): n for n, s in pairs}
    rows = []

    # W1 ADMETlab 3.0
    p = r"D:/WorkBuddy/pharma-tools/mm_work/admetlab_results.csv"
    if os.path.exists(p):
        for r in csv.DictReader(io.open(p, encoding="utf-8-sig")):
            n = can2name.get(can(r.get("smiles")))
            if not n:
                continue
            for ep, col in (("DILI", "DILI"), ("Ames", "Ames"), ("hERG", "hERG"),
                            ("nr_ar_lbd", "NR-AR-LBD"), ("sr_p53", "SR-p53"),
                            ("sr_are", "SR-ARE")):
                v = r.get(col)
                if v in (None, ""):
                    continue
                rows.append(schema.measurement(n, ep, round(float(v), 4), "probability",
                                               "admetlab3", "3.0", "predicted"))

    # W2 ProTox-III（类别标签，不是概率）
    p = os.path.join(PROJ, "web_results", "w2_protox.csv")
    if os.path.exists(p):
        for r in csv.DictReader(io.open(p, encoding="utf-8-sig")):
            n = r.get("name")
            for ep, col in (("DILI", "dili_pred"), ("Ames", "mutagen_pred")):
                v = r.get(col)
                if v in (None, ""):
                    continue
                rows.append(schema.measurement(n, ep, int(float(v)), "class",
                                               "protox3", "III", "predicted",
                                               note="类别标签（0/1），非概率"))

    # W3 ADMET-AI
    p = os.path.join(PROJ, "web_results", "admetai_predictions.csv")
    if os.path.exists(p):
        for r in csv.DictReader(io.open(p, encoding="utf-8-sig")):
            n = can2name.get(can(r.get("smiles")))
            if not n:
                continue
            for ep, col in (("DILI", "DILI"), ("Ames", "AMES"), ("hERG", "hERG")):
                v = r.get(col)
                if v in (None, ""):
                    continue
                rows.append(schema.measurement(n, ep, round(float(v), 4), "probability",
                                               "admet_ai", "2.0", "predicted"))

    # W5 vNN-ADMET（Yes/No/NoPrediction）
    p = os.path.join(PROJ, "w5_output", "w5_vnnadmet.csv")
    if os.path.exists(p):
        for r in csv.DictReader(io.open(p, encoding="utf-8-sig")):
            n = r.get("ID")
            for ep, col in (("DILI", "DILI"), ("Ames", "AMES"), ("hERG", "hERG")):
                v = (r.get(col) or "").strip()
                if not v:
                    continue
                if v == "NoPrediction":
                    rows.append(schema.measurement(n, ep, "", "probability", "vnn_admet",
                                                   "1.3.3", "out_of_domain",
                                                   note="适用域外，源拒绝预测"))
                else:
                    rows.append(schema.measurement(n, ep, 1 if v == "Yes" else 0,
                                                   "probability", "vnn_admet", "1.3.3",
                                                   "predicted", note="Yes/No 二值"))

    out = os.path.join(SKILL, "out", "measurements_demo.csv")
    n = schema.write_measurements_checked(out, rows)
    probs = schema.validate(rows)
    print("wrote %s  (%d 行)" % (out, n))
    print("schema problems:", probs if probs else "none")
    eps = sorted({r["endpoint"] for r in rows})
    print("端点:", eps, "| 源:", sorted({r["source"] for r in rows}))


if __name__ == "__main__":
    main()
