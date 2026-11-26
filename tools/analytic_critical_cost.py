# -*- coding: utf-8 -*-
"""CLI wrapper around :mod:`adt.cost_boundary` (the c* boundary estimator).

This script predates the ``adt cstar`` subcommand and is kept so that the
manuscript's commands and the recorded SHA-256 outputs remain reproducible.
The estimator itself lives in ``adt/cost_boundary.py``; this file only parses
arguments, loads the results JSON, and calls into the library.

Usage
-----
    # primary analysis (default, reproduces references/ANALYTIC_CRITICAL_COST.md)
    python tools/analytic_critical_cost.py

    # transferability demo on endpoints outside the preregistered set
    python tools/analytic_critical_cost.py \
        --results out_keystone_transfer/results.json \
        --endpoints Ames,CYP3A4_Veith \
        --out-md references/CRITICAL_COST_TRANSFER.md \
        --out-csv out_sensitivity/critical_cost_transfer.csv \
        --title 'Critical cost, transferability demo'

The estimator is identical in both runs; only the data file and endpoint list
change. That is the point of the demo: c* must be recomputable on endpoints the
analysis was not designed around.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from adt.cost_boundary import render_markdown, solve_all, write_csv  # noqa: E402

DEFAULT_RESULTS = os.path.join(ROOT, "out_keystone_v43", "results.json")
DEFAULT_EPS = "hERG,DILI,BBB_Martins"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=DEFAULT_RESULTS)
    ap.add_argument("--endpoints", default=DEFAULT_EPS)
    ap.add_argument("--out-md", default="references/ANALYTIC_CRITICAL_COST.md")
    ap.add_argument("--out-csv", default="out_sensitivity/critical_cost.csv")
    ap.add_argument("--title", default="Analytic critical abstention cost c*")
    ap.add_argument(
        "--interim",
        action="store_true",
        help="label this output as a transferability demonstration "
        "rather than a primary result",
    )
    a = ap.parse_args(argv)

    results = a.results if os.path.isabs(a.results) else os.path.join(ROOT, a.results)
    d = json.load(io.open(results, encoding="utf-8"))
    eps = [x for x in a.endpoints.split(",") if x]

    rows = solve_all(d["per_run"], eps)
    if not rows:
        print("[c*] no endpoint produced a solution; check --results and --endpoints")
        return 2

    csv_path = a.out_csv if os.path.isabs(a.out_csv) else os.path.join(ROOT, a.out_csv)
    os.makedirs(os.path.dirname(csv_path), exist_ok=True)
    write_csv(rows, csv_path)

    md = render_markdown(
        rows,
        a.title,
        os.path.relpath(results, ROOT).replace("\\", "/"),
        interim=a.interim,
        generator="tools/analytic_critical_cost.py",
    )
    md_path = a.out_md if os.path.isabs(a.out_md) else os.path.join(ROOT, a.out_md)
    os.makedirs(os.path.dirname(md_path), exist_ok=True)
    io.open(md_path, "w", encoding="utf-8", newline="\n").write(md)

    print(
        "[c*] "
        + " | ".join(
            "%s=%.4f[%.4f,%.4f]" % (r["endpoint"], r["c_star"], r["ci_lo"], r["ci_hi"])
            for r in rows
        )
    )
    print("[c*] -> %s, %s" % (a.out_md, a.out_csv))
    return 0


if __name__ == "__main__":
    sys.exit(main())
