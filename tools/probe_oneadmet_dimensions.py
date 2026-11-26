#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""OneADMET / OpenADMET 列量纲探针（模块 L 映射前的强制步骤）。

2026-10-30 用真实数值核实了 `pX = -log10(X)` 约定、PPB 是 %bound、
Clearance-Microsomal 是 per-kg 体内清除率（与 clint uL/min/mg 语义不同，
因此不映射）。换机 / 换 SI 版本后应先重跑本探针再谈映射。

用法：python tools/probe_oneadmet_dimensions.py [--rows 5000]
"""

from __future__ import annotations

import argparse
import os
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ONE_COLS = [
    "SMILES",
    "PUBLIC___LogPapp_Caco_Public.csv",
    "PUBLIC___LogER_Caco2_Public.csv",
    "PUBLIC___LogD74_Public.csv",
    "PUBLIC___LogS_Water_Public.csv",
    "PUBLIC___LogPow_Public.csv",
    "PPB_Human_Public.csv",
    "Half-Life_Human-Plasma-pHours_Public.csv",
    "Clearance-Microsomal_Rat-pmL%min%kg_Public.csv",
    "pLD50-po-Rat-pmg%kg_Public.csv",
]
RAW_COLS = [
    "LogD",
    "KSOL",
    "HLM CLint",
    "RLM CLint",
    "MLM CLint",
    "Caco-2 Permeability Papp A>B",
    "Caco-2 Permeability Efflux",
    "MPPB",
    "MBPB",
    "MGMB",
]


def main(argv=None):
    ap = argparse.ArgumentParser(description="核实 OneADMET / OpenADMET 列数值范围")
    ap.add_argument(
        "--oneadmet-csv",
        default=os.environ.get("ADT_ONEADMET_CSV", "")
        or os.path.join(ROOT, "assets", "external", "oneadmet", "oneADMET.csv"),
    )
    ap.add_argument(
        "--openadmet-raw",
        default=os.environ.get("ADT_OPENADMET_RAW", "")
        or os.path.join(
            ROOT, "assets", "external", "openadmet", "expansion_data_raw.csv"
        ),
    )
    ap.add_argument("--rows", type=int, default=5000)
    a = ap.parse_args(argv)

    if not os.path.isfile(a.oneadmet_csv):
        raise SystemExit("[FAIL] OneADMET SI 缺失: %s" % a.oneadmet_csv)
    df = pd.read_csv(a.oneadmet_csv, usecols=ONE_COLS, nrows=a.rows)
    print("=== OneADMET 前 %d 行采样统计 ===" % a.rows)
    for c in ONE_COLS[1:]:
        s = pd.to_numeric(df[c], errors="coerce").dropna()
        if len(s):
            print(
                "%-46s n=%5d min=%8.3f p50=%8.3f max=%8.3f"
                % (c[:44], len(s), s.min(), s.median(), s.max())
            )
        else:
            print("%-46s n=0 (全空)" % c[:44])

    raw = pd.read_csv(a.openadmet_raw)
    print("\n=== OpenADMET raw 全量 %d 行 ===" % len(raw))
    for c in RAW_COLS:
        s = (
            pd.to_numeric(raw[c], errors="coerce").dropna()
            if c in raw.columns
            else pd.Series(dtype=float)
        )
        if len(s):
            print(
                "%-32s n=%5d min=%8.3f p50=%8.3f max=%8.3f"
                % (c[:30], len(s), s.min(), s.median(), s.max())
            )
        else:
            print("%-32s n=0 (全空)" % c[:30])
    return 0


if __name__ == "__main__":
    sys.exit(main())
