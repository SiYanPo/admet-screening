# -*- coding: utf-8 -*-
"""为统计腿构造**合成**预测/真值对（仅验证 conformal/benchmark 的接线与数学）。

为什么要造：conformal 需要 (pred, truth) 配对，而面板本身只有预测、没有实测真值；
随包 OpenADMET/NPASS 长表是**实测值**（domain_flag=measured），把它们当"预测"
去比"真值"是循环论证（skill 自己的 benchmark 会打印这条警告）。

因此本脚本显式造一对**带固定种子的合成对**：
    truth_value = 实测值（真实，来自 measurements_test.csv）
    pred_value  = truth_value × (1 + U(-0.08, 0.08))（合成扰动，确定性）
并在产物里写 `SYNTHETIC_pipeline_wiring_test` 标记。**任何结论表都不得引用它。**

用法：
    python tools/panel_legb_split.py --measurements <legB/measurements_test.csv> \
        --outdir <legB> [--min-n 20] [--seed 20261119]
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import random
import sys

FIELDS_PRED = [
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
FIELDS_TRUTH = [
    "compound_id",
    "endpoint",
    "truth_value",
    "truth_class",
    "source",
    "assay",
    "provenance_url",
    "note",
]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--measurements", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--min-n", type=int, default=20)
    ap.add_argument("--seed", type=int, default=20261119)
    ap.add_argument("--noise", type=float, default=0.08)
    a = ap.parse_args(argv)

    if not os.path.exists(a.measurements):
        print(
            "[legb] ✗ 缺 %s（先跑 external --dataset openadmet --split test）"
            % a.measurements,
            file=sys.stderr,
        )
        return 2
    with io.open(a.measurements, encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))

    by_ep = {}
    for r in rows:
        v = str(r.get("value") or "").strip()
        if not v:
            continue
        try:
            float(v)
        except ValueError:
            continue
        by_ep.setdefault(r["endpoint"], []).append(r)
    keep = {ep: rs for ep, rs in by_ep.items() if len(rs) >= a.min_n}
    if not keep:
        print(
            "[legb] ✗ 没有端点达到 --min-n %d（最大 %d），无法构造配对"
            % (a.min_n, max((len(v) for v in by_ep.values()), default=0)),
            file=sys.stderr,
        )
        return 3

    rng = random.Random(a.seed)
    pred, truth = [], []
    for ep, rs in sorted(keep.items()):
        for r in rs:
            v = float(r["value"])
            pred.append(
                dict(
                    compound_id=r["compound_id"],
                    endpoint=ep,
                    value=round(v * (1 + rng.uniform(-a.noise, a.noise)), 6),
                    unit=r.get("unit", ""),
                    source="SYNTHETIC_pred",
                    source_version="wiring-test",
                    retrieved_at="2026-11-19T00:00:00",
                    domain_flag="predicted",
                    uncertainty="",
                    provenance_url="synthetic://panel-wiring-test",
                    note="SYNTHETIC_pipeline_wiring_test",
                )
            )
            truth.append(
                dict(
                    compound_id=r["compound_id"],
                    endpoint=ep,
                    truth_value=v,
                    truth_class=r.get("truth_class", "") or "",
                    source=r.get("source", ""),
                    assay=r.get("assay", ""),
                    provenance_url=r.get("provenance_url", ""),
                    note="truth 真实；pred 为合成扰动",
                )
            )

    os.makedirs(a.outdir, exist_ok=True)
    p1 = os.path.join(a.outdir, "synthetic_pred.csv")
    p2 = os.path.join(a.outdir, "synthetic_truth.csv")
    with io.open(p1, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS_PRED)
        w.writeheader()
        w.writerows(pred)
    with io.open(p2, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS_TRUTH)
        w.writeheader()
        w.writerows(truth)
    with io.open(
        os.path.join(a.outdir, "SYNTHETIC_README.txt"), "w", encoding="utf-8"
    ) as fh:
        fh.write(
            "本目录的 synthetic_pred.csv / synthetic_truth.csv 为**合成**数据：\n"
            "truth 取真实实测值，pred 为 ±%.0f%% 确定性扰动（seed=%d）。\n"
            "用途：仅验证 conformal/benchmark/cross-class 的接线与数学。\n"
            "禁止：把这里的任何数值写入结论、报告或论文。\n" % (a.noise * 100, a.seed)
        )
    print(
        "[legb] 端点 %d 个 / 配对 %d 条 -> %s | %s"
        % (len(keep), len(pred), os.path.basename(p1), os.path.basename(p2))
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
