#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""OneADMET SI 宽表 + OpenADMET raw 宽表 -> skill 测量长表（模块 L 的可复现输入）。

移植自 2026-10-30 的一次性脚本：映射语义逐字未改，只把硬编码绝对路径换成
相对 skill 根目录的可覆盖参数，使换机后能直接重跑、并与既有产物逐字节比对。

量纲映射已用 tools/probe_oneadmet_dimensions.py 逐列实测核实。原则：
只有同量纲同语义才映射（C52/C70 教训）。Clearance-Microsomal 是 per-kg 体内
清除率，与 clint (uL/min/mg) 语义不同，故不映射；`pX` = -log10(X) 约定已确认。

用法：
    python tools/build_oneadmet_longtables.py
    python tools/build_oneadmet_longtables.py --outdir /somewhere/else
    ADT_ONEADMET_CSV=/path/to/oneADMET.csv python tools/build_oneadmet_longtables.py

说明：retrieved_at 固定为 2026-10-30T17:40:00（SI 获取时刻，属于数据内容而非
运行时刻），故意不用当前时间，以保证输出逐位可比对。SHA256 默认校验，防止
换机时误用不同口径的 SI 却声称复现了既有结论。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import math
import os
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

COLS = [
    "compound_id",
    "endpoint",
    "value",
    "unit",
    "source",
    "source_version",
    "retrieved_at",
    "domain_flag",
    "uncertainty",
    "provenance_url",
    "note",
]
DOI = "https://pubs.acs.org/doi/10.1021/acs.jmedchem.6c00049"
ZEN = "https://zenodo.org/records/21504733"
RETRIEVED_AT = "2026-10-30T17:40:00"

# 2026-11-05 实测：jm6c00049_si_002.zip 内 oneADMET.csv 的 SHA256 与字节数。
EXPECTED_SHA256 = "c0860bf9c47806d9867f95b84bdfda8a62c189f891e1d951765fdd283d51034c"
EXPECTED_BYTES = 1197248494

ONE_COLS = [
    "SMILES",
    "PUBLIC___LogPapp_Caco_Public.csv",  # log10(cm/s)，实测核实
    "PPB_Human_Public.csv",  # % bound，实测核实
    "PUBLIC___LogER_Caco2_Public.csv",  # log10(ER)
    "PUBLIC___LogD74_Public.csv",
]  # logD7.4


def ok(v):
    return v is not None and not (
        isinstance(v, float) and (v != v or abs(v) == float("inf"))
    )


def sha256_of(path):
    h = hashlib.sha256()
    n = 0
    with open(path, "rb") as f:
        while True:
            b = f.read(4 * 1024 * 1024)
            if not b:
                break
            h.update(b)
            n += len(b)
    return h.hexdigest(), n


def verify_input(path, skip_sha256=False):
    if not os.path.isfile(path):
        raise SystemExit(
            "[FAIL] OneADMET SI 缺失: %s\n"
            "       下载与放置见 SETUP_REPRODUCE.md §4.1，"
            "或设 ADT_ONEADMET_CSV 指向已有文件。" % path
        )
    size = os.path.getsize(path)
    if size != EXPECTED_BYTES:
        raise SystemExit(
            "[FAIL] OneADMET SI 字节数 %d != 期望 %d，口径可能不同。"
            % (size, EXPECTED_BYTES)
        )
    with io.open(path, "rb") as fh:
        header = fh.readline().decode("utf-8", "replace").strip()
    missing = [c for c in ONE_COLS if c not in header]
    if missing:
        raise SystemExit("[FAIL] SI 表头缺列: %s" % missing)
    if skip_sha256:
        print("[OK] OneADMET SI size/header 校验通过（SHA256 按要求跳过）")
        return
    digest, _ = sha256_of(path)
    if digest != EXPECTED_SHA256:
        raise SystemExit(
            "[FAIL] OneADMET SI SHA256 %s != 期望 %s；"
            "数据口径已变，不得声称复现既有 L 项结论。" % (digest, EXPECTED_SHA256)
        )
    print("[OK] OneADMET SI SHA256/size/header 校验通过: %s" % path)


def write_rows(path, rows):
    with io.open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print("WROTE %s rows=%d" % (path, len(rows)))


def build_oneadmet(path):
    rows = []
    for chunk in pd.read_csv(path, usecols=ONE_COLS, chunksize=100000):
        for _, r in chunk.iterrows():
            cid = r["SMILES"]
            if not isinstance(cid, str) or not cid.strip():
                continue
            cid = cid.strip()
            v = r["PUBLIC___LogPapp_Caco_Public.csv"]
            if ok(v):
                rows.append(
                    dict(
                        compound_id=cid,
                        endpoint="caco2_papp_ab",
                        value=round(float(v), 4),
                        unit="log10(cm/s)",
                        source="OneADMET",
                        source_version="SI_2026",
                        retrieved_at=RETRIEVED_AT,
                        domain_flag="measured",
                        uncertainty="",
                        provenance_url=DOI,
                        note="SI LogPapp_Caco",
                    )
                )
            v = r["PPB_Human_Public.csv"]
            if ok(v):
                rows.append(
                    dict(
                        compound_id=cid,
                        endpoint="ppb_fu",
                        value=round(100 - float(v), 4),
                        unit="percent",
                        source="OneADMET",
                        source_version="SI_2026",
                        retrieved_at=RETRIEVED_AT,
                        domain_flag="measured",
                        uncertainty="",
                        provenance_url=DOI,
                        note="SI PPB_Human %bound->fu%",
                    )
                )
            v = r["PUBLIC___LogER_Caco2_Public.csv"]
            if ok(v):
                rows.append(
                    dict(
                        compound_id=cid,
                        endpoint="efflux_ratio",
                        value=round(10 ** float(v), 4),
                        unit="ratio",
                        source="OneADMET",
                        source_version="SI_2026",
                        retrieved_at=RETRIEVED_AT,
                        domain_flag="measured",
                        uncertainty="",
                        provenance_url=DOI,
                        note="SI LogER->ER=10^x",
                    )
                )
            v = r["PUBLIC___LogD74_Public.csv"]
            if ok(v):
                rows.append(
                    dict(
                        compound_id=cid,
                        endpoint="logd_74",
                        value=round(float(v), 4),
                        unit="log10",
                        source="OneADMET",
                        source_version="SI_2026",
                        retrieved_at=RETRIEVED_AT,
                        domain_flag="measured",
                        uncertainty="",
                        provenance_url=DOI,
                        note="SI LogD74",
                    )
                )
    return rows


def build_openadmet_raw(path):
    if not os.path.isfile(path):
        raise SystemExit("[FAIL] OpenADMET raw 缺失: %s" % path)
    raw = pd.read_csv(path)
    rows = []
    skipped_zero = 0
    for _, r in raw.iterrows():
        cid = r.get("SMILES")
        if not isinstance(cid, str) or not cid.strip():
            continue
        cid = cid.strip()
        v = pd.to_numeric(r.get("Caco-2 Permeability Papp A>B"), errors="coerce")
        if ok(v):
            v = float(v)
            if v <= 0:
                skipped_zero += 1  # 低于检测限，log 无法定义，不计入并诚实计数
            else:
                rows.append(
                    dict(
                        compound_id=cid,
                        endpoint="caco2_papp_ab",
                        value=round(math.log10(v * 1e-6), 4),
                        unit="log10(cm/s)",
                        source="OpenADMET_raw",
                        source_version="expansion_raw",
                        retrieved_at=RETRIEVED_AT,
                        domain_flag="measured",
                        uncertainty="",
                        provenance_url=ZEN,
                        note="Papp 1e-6cm/s->log10",
                    )
                )
        for col in ["HLM CLint", "RLM CLint", "MLM CLint"]:
            v = pd.to_numeric(r.get(col), errors="coerce")
            if ok(v):
                rows.append(
                    dict(
                        compound_id=cid,
                        endpoint="clint_microsome",
                        value=round(float(v), 4),
                        unit="uL/min/mg",
                        source="OpenADMET_raw",
                        source_version="expansion_raw",
                        retrieved_at=RETRIEVED_AT,
                        domain_flag="measured",
                        uncertainty="",
                        provenance_url=ZEN,
                        note="raw %s" % col,
                    )
                )
        for col in ["MPPB", "MBPB", "MGMB"]:
            v = pd.to_numeric(r.get(col), errors="coerce")
            if ok(v):
                rows.append(
                    dict(
                        compound_id=cid,
                        endpoint="ppb_fu",
                        value=round(100 - float(v), 4),
                        unit="percent",
                        source="OpenADMET_raw",
                        source_version="expansion_raw",
                        retrieved_at=RETRIEVED_AT,
                        domain_flag="measured",
                        uncertainty="",
                        provenance_url=ZEN,
                        note="raw %s %%bound->fu%%" % col,
                    )
                )
        v = pd.to_numeric(r.get("LogD"), errors="coerce")
        if ok(v):
            rows.append(
                dict(
                    compound_id=cid,
                    endpoint="logd_74",
                    value=round(float(v), 4),
                    unit="log10",
                    source="OpenADMET_raw",
                    source_version="expansion_raw",
                    retrieved_at=RETRIEVED_AT,
                    domain_flag="measured",
                    uncertainty="",
                    provenance_url=ZEN,
                    note="raw LogD",
                )
            )
        v = pd.to_numeric(r.get("Caco-2 Permeability Efflux"), errors="coerce")
        if ok(v):
            rows.append(
                dict(
                    compound_id=cid,
                    endpoint="efflux_ratio",
                    value=round(float(v), 4),
                    unit="ratio",
                    source="OpenADMET_raw",
                    source_version="expansion_raw",
                    retrieved_at=RETRIEVED_AT,
                    domain_flag="measured",
                    uncertainty="",
                    provenance_url=ZEN,
                    note="raw Efflux",
                )
            )
    print("OpenADMET raw Papp<=0 跳过数: %d" % skipped_zero)
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description="重建模块 L 的两组测量长表")
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
    ap.add_argument(
        "--outdir", default=os.path.join(ROOT, "instances", "v350", "oneadmet")
    )
    ap.add_argument(
        "--skip-sha256",
        action="store_true",
        help="跳过 1.2 GB 文件的完整哈希（不推荐）",
    )
    a = ap.parse_args(argv)

    verify_input(a.oneadmet_csv, skip_sha256=a.skip_sha256)
    os.makedirs(a.outdir, exist_ok=True)
    write_rows(
        os.path.join(a.outdir, "oneadmet_measurements.csv"),
        build_oneadmet(a.oneadmet_csv),
    )
    write_rows(
        os.path.join(a.outdir, "openadmet_raw_measurements.csv"),
        build_openadmet_raw(a.openadmet_raw),
    )
    print("[DONE] 输出目录: %s" % a.outdir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
