#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""导出 TDC ADME 6 个基准集为 skill 长表（模块 L 的第三个独立 curation 数据集）。

移植自 2026-10-30 的一次性脚本：去掉了指向特定 venv 的 sys.path 硬编码，
输出默认落在 skill 目录内。当前主环境已装 pytdc==1.1.15（--no-deps），
`from tdc.single_pred import ADME` 实测可导入，因此无需独立 venv。

注意：本脚本**需要联网**从 TDC 服务器取数，且 TDC 会限流。离线复现请直接用
随包快照 `instances/v350/tdc/tdc_adme_measurements.csv`（17,528 行），
两者内容一致；仅在需要重新取数时运行本脚本。

用法：
    python tools/tdc_export.py                      # 完整冷却 + 重试
    python tools/tdc_export.py --no-cooldown       # 本地快速重试（可能被限流）
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import sys
import time

from tdc.single_pred import ADME

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DATASETS = [
    ("Caco2_Wang", "tdc_caco2_permeability", "logPapp", "reg"),
    ("HIA_Hou", "tdc_hia", "fraction_absorbed", "cls"),
    ("Pgp_Broccatelli", "tdc_pgp_substrate", "binary", "cls"),
    ("Bioavailability_Ma", "tdc_bioavailability", "binary", "cls"),
    ("Lipophilicity_AstraZeneca", "tdc_logp", "logP", "reg"),
    ("Solubility_AqSolDB", "tdc_aqsol_logs", "logS", "reg"),
]
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
RETRIEVED_AT = "2026-10-30T00:00:00"  # 快照取数时刻，属数据内容，保证逐位可比对


def load_with_retry(tdc_name, max_tries=6):
    delay = 10
    for attempt in range(1, max_tries + 1):
        try:
            d = ADME(name=tdc_name)
            return d.get_data()
        except Exception as e:
            msg = str(e)
            if "429" in msg or "Too Many" in msg or "rate" in msg.lower():
                print(
                    "  [限流] %s 第%d次遇 429，%ds 后重试..."
                    % (tdc_name, attempt, delay)
                )
                time.sleep(delay)
                delay = min(delay * 2, 120)
                continue
            raise
    raise RuntimeError("%s 重试 %d 次仍失败" % (tdc_name, max_tries))


def main(argv=None):
    ap = argparse.ArgumentParser(description="从 TDC 重新导出 ADME 长表")
    ap.add_argument(
        "--out",
        default=os.path.join(
            ROOT, "instances", "v350", "tdc", "tdc_adme_measurements.csv"
        ),
    )
    ap.add_argument("--no-cooldown", action="store_true", help="跳过 30s/15s 冷却")
    a = ap.parse_args(argv)

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    first, total, failed = True, 0, []
    if not a.no_cooldown:
        print("起步冷却 30s，避免触发 TDC 限流...")
        time.sleep(30)
    for tdc_name, ep, unit, kind in DATASETS:
        try:
            df = load_with_retry(tdc_name)
            n = len(df)
            rows = []
            for _, r in df.iterrows():
                cid = str(r.get("Drug_ID") or r.get("Drug") or "")[:60]
                val = r.get("Y")
                if val is None or (isinstance(val, float) and val != val):
                    continue
                rows.append(
                    dict(
                        compound_id=cid,
                        endpoint=ep,
                        value=val,
                        unit=unit,
                        source="TDC_ADME",
                        source_version="1.1.15",
                        retrieved_at=RETRIEVED_AT,
                        domain_flag="measured",
                        uncertainty="",
                        provenance_url="https://tdcommons.ai/",
                        note="TDC %s n=%d" % (tdc_name, n),
                    )
                )
            with io.open(
                a.out, "w" if first else "a", encoding="utf-8-sig", newline=""
            ) as f:
                w = csv.DictWriter(f, fieldnames=COLS)
                if first:
                    w.writeheader()
                for r in rows:
                    w.writerow(r)
            first = False
            total += len(rows)
            print("  OK %-26s n=%d  累计行数=%d" % (tdc_name, n, total))
        except Exception as e:
            failed.append(tdc_name)
            print("  FAIL %-24s %s" % (tdc_name, e))
        if not a.no_cooldown:
            time.sleep(15)
    print("完成。输出: %s 总行数=%d 失败数据集=%s" % (a.out, total, failed or "无"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
