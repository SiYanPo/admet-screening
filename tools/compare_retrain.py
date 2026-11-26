# -*- coding: utf-8 -*-
"""Compare two per-seed result files and quantify retraining drift.

Why this exists
---------------
The manuscript claims that table generation is byte-reproducible while model
retraining is reproducible "to tolerance rather than byte for byte". That
sentence is worthless until the tolerance is measured, so this script measures
it: it pairs every (endpoint, strategy, cost_point, seed) record between a
baseline and a retrain, and reports how far they moved.

What is compared
----------------
`utility`, `coverage` and `risk_decided`, all of which the pipeline already
rounds to four decimals. A record is called identical when all three match
exactly at that precision; anything else is drift.

Reported
--------
  * how many records are identical, and the identity rate
  * max / median absolute difference per field
  * the seed-level sign of the primary contrast (S4 - S1) before and after, to
    show whether a retrain can change a conclusion rather than only a digit
  * the resulting c* on both sides, since that is the quantity the paper reports

Usage
-----
    python tools/compare_retrain.py \
        --baseline /tmp/full_baseline/results_primary.json \
        --retrain out_keystone_v43/results.json \
        --out-md references/RETRAIN_DRIFT.md
"""

from __future__ import annotations

import argparse
import io
import json
import os
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

FIELDS = ("utility", "coverage", "risk_decided")


def index(per_run):
    out = {}
    for r in per_run:
        key = (r["endpoint"], r["strategy"], r["cost_point"], r["seed"])
        out[key] = r
    return out


def compare(base, retr):
    a, b = index(base), index(retr)
    common = sorted(set(a) & set(b))
    only_a = len(set(a) - set(b))
    only_b = len(set(b) - set(a))

    stats = {f: {"max": 0.0, "diffs": []} for f in FIELDS}
    identical = 0
    for k in common:
        same = True
        for f in FIELDS:
            va, vb = a[k].get(f), b[k].get(f)
            if va is None or vb is None:
                same = False
                continue
            d = abs(float(vb) - float(va))
            stats[f]["max"] = max(stats[f]["max"], d)
            stats[f]["diffs"].append(d)
            if d != 0:
                same = False
        if same:
            identical += 1

    per_field = {}
    for f in FIELDS:
        ds = stats[f]["diffs"]
        per_field[f] = {
            "max_abs": round(stats[f]["max"], 6),
            "median_abs": round(statistics.median(ds), 6) if ds else None,
            "mean_abs": round(statistics.mean(ds), 6) if ds else None,
            "n": len(ds),
        }

    return {
        "n_common": len(common),
        "n_only_baseline": only_a,
        "n_only_retrain": only_b,
        "n_identical": identical,
        "identity_rate": round(identical / len(common), 6) if common else None,
        "per_field": per_field,
        "common_keys": common,
        "a": a,
        "b": b,
    }


def sign_contrast(cmp, endpoints):
    """Sign of S4 - S1 at the reference cost point, per endpoint, both sides."""
    rows = []
    for ep in endpoints:
        s4a = {
            k[3]: v["utility"]
            for k, v in cmp["a"].items()
            if k[0] == ep and k[1] == "S4_full_admission" and k[2] == "ref"
        }
        s1a = {
            k[3]: v["utility"]
            for k, v in cmp["a"].items()
            if k[0] == ep and k[1] == "S1_naive_majority" and k[2] == "ref"
        }
        s4b = {
            k[3]: v["utility"]
            for k, v in cmp["b"].items()
            if k[0] == ep and k[1] == "S4_full_admission" and k[2] == "ref"
        }
        s1b = {
            k[3]: v["utility"]
            for k, v in cmp["b"].items()
            if k[0] == ep and k[1] == "S1_naive_majority" and k[2] == "ref"
        }
        sa = [s4a[s] - s1a[s] for s in sorted(set(s4a) & set(s1a))]
        sb = [s4b[s] - s1b[s] for s in sorted(set(s4b) & set(s1b))]
        if not sa or not sb:
            continue
        da, db = statistics.median(sa), statistics.median(sb)
        rows.append(
            {
                "endpoint": ep,
                "baseline": round(da, 4),
                "retrain": round(db, 4),
                "delta": round(db - da, 4),
                "same_sign": (da > 0) == (db > 0),
                "n_pos_baseline": sum(1 for x in sa if x > 0),
                "n_pos_retrain": sum(1 for x in sb if x > 0),
            }
        )
    return rows


def critical_cost(cmp, side, ep, points=None):
    """Per-seed c* for one side, solved the same way as the paper."""
    points = points or [
        ("abstain=0.05", 0.05),
        ("abstain=0.10", 0.10),
        ("abstain=0.20", 0.20),
        ("abstain=0.50", 0.50),
        ("abstain=1.00", 1.00),
    ]
    src = cmp[side]
    seeds = sorted({k[3] for k in src if k[0] == ep})
    out = []
    for seed in seeds:
        xs, ys = [], []
        for cp, x in points:
            ka = (ep, "S4_full_admission", cp, seed)
            kb = (ep, "S1_naive_majority", cp, seed)
            if ka in src and kb in src:
                xs.append(x)
                ys.append(float(src[ka]["utility"]) - float(src[kb]["utility"]))
        if len(xs) < 5:
            continue
        n = len(xs)
        mx, my = sum(xs) / n, sum(ys) / n
        den = sum((x - mx) ** 2 for x in xs)
        if den == 0:
            continue
        slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den
        intercept = my - slope * mx
        if slope != 0:
            out.append(-intercept / slope)
    return statistics.median(out) if out else None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--retrain", required=True)
    ap.add_argument("--endpoints", default="hERG,DILI,BBB_Martins,Ames,CYP3A4_Veith")
    ap.add_argument("--out-md", default=None)
    a = ap.parse_args(argv)

    base = json.load(io.open(a.baseline, encoding="utf-8"))["per_run"]
    retr = json.load(io.open(a.retrain, encoding="utf-8"))["per_run"]
    cmp = compare(base, retr)
    eps = [
        x
        for x in a.endpoints.split(",")
        if x and any(k[0] == x for k in cmp["common_keys"])
    ]
    contrast = sign_contrast(cmp, eps)

    L = []
    L.append("Retraining drift: baseline vs fresh retrain")
    L.append("")
    L.append("| Metric | Value |")
    L.append("|---|---|")
    L.append("| Paired records | %d |" % cmp["n_common"])
    L.append(
        "| Identical after 4-decimal rounding | %d (%.4f%%) |"
        % (cmp["n_identical"], 100 * (cmp["identity_rate"] or 0))
    )
    L.append(
        "| Only in baseline / only in retrain | %d / %d |"
        % (cmp["n_only_baseline"], cmp["n_only_retrain"])
    )
    L.append("")
    L.append("| Field | max abs diff | median abs diff | mean abs diff |")
    L.append("|---|---|---|---|")
    for f in FIELDS:
        s = cmp["per_field"][f]
        L.append(
            "| %s | %.6f | %s | %s |"
            % (
                f,
                s["max_abs"],
                "%.6f" % s["median_abs"] if s["median_abs"] is not None else "n/a",
                "%.6f" % s["mean_abs"] if s["mean_abs"] is not None else "n/a",
            )
        )
    L.append("")
    L.append("Sign of the primary contrast S4 - S1 at c_ref:")
    L.append("")
    L.append(
        "| Endpoint | baseline | retrain | delta | same sign | seeds positive (base -> retrain) |"
    )
    L.append("|---|---|---|---|---|---|")
    for r in contrast:
        L.append(
            "| %s | %+.4f | %+.4f | %+.4f | %s | %d -> %d |"
            % (
                r["endpoint"],
                r["baseline"],
                r["retrain"],
                r["delta"],
                "yes" if r["same_sign"] else "NO",
                r["n_pos_baseline"],
                r["n_pos_retrain"],
            )
        )
    L.append("")
    L.append("Critical cost c* on both sides:")
    L.append("")
    L.append("| Endpoint | baseline c* | retrain c* | delta |")
    L.append("|---|---|---|---|")
    for ep in eps:
        ca = critical_cost(cmp, "a", ep)
        cb = critical_cost(cmp, "b", ep)
        if ca is None or cb is None:
            continue
        L.append("| %s | %.4f | %.4f | %+.4f |" % (ep, ca, cb, cb - ca))

    text = "\n".join(L) + "\n"
    print(text)
    if a.out_md:
        p = a.out_md if os.path.isabs(a.out_md) else os.path.join(ROOT, a.out_md)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        io.open(p, "w", encoding="utf-8", newline="\n").write(text)
        print("[drift] -> %s" % a.out_md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
