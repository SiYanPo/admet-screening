# -*- coding: utf-8 -*-
"""Merge keystone result files into one per-endpoint collection.

Why this exists
---------------
The deposit accumulates results in separate directories as endpoints are added:
the three preregistered endpoints, the two transferability endpoints, the six
small extension endpoints, and the two large CYP endpoints (which are run
separately because a 10k-molecule endpoint costs roughly fifty times a
500-molecule one). Reporting a cross-endpoint distribution requires them in one
file, with the seed count per endpoint preserved rather than silently pooled.

The merge is deliberately explicit about unequal seeds: CYP2C9_Veith and
CYP2D6_Veith carry fewer seeds than the rest, and the output records that so the
interval widths can be read correctly.

Usage
-----
    python tools/merge_keystone_results.py --outdir out_keystone_all13
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DEFAULT_SOURCES = [
    "out_keystone_v43/results.json",
    "out_keystone_transfer/results.json",
    "out_keystone_ext/results.json",
    "out_keystone_ext_big/results.json",
    "out_keystone_ext_big2/results.json",
]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", nargs="*", default=DEFAULT_SOURCES)
    ap.add_argument("--outdir", default="out_keystone_all13")
    a = ap.parse_args(argv)

    per_run = []
    seen = set()
    seeds_by_ep = defaultdict(set)
    source_of = {}
    for rel in a.sources:
        p = rel if os.path.isabs(rel) else os.path.join(ROOT, rel)
        if not os.path.exists(p):
            print("[merge] skip (absent): %s" % rel)
            continue
        d = json.load(io.open(p, encoding="utf-8"))
        n = 0
        for r in d["per_run"]:
            key = (r["endpoint"], r["strategy"], r["cost_point"], r["seed"])
            if key in seen:
                continue
            seen.add(key)
            per_run.append(r)
            seeds_by_ep[r["endpoint"]].add(r["seed"])
            source_of.setdefault(r["endpoint"], rel)
            n += 1
        print("[merge] %-40s +%d records" % (rel, n))

    if not per_run:
        print("[merge] nothing to merge")
        return 2

    os.makedirs(os.path.join(ROOT, a.outdir), exist_ok=True)
    out = {
        "schema_version": "merged-1",
        "endpoints": sorted(seeds_by_ep),
        "seeds_by_endpoint": {k: len(v) for k, v in sorted(seeds_by_ep.items())},
        "sources": [s for s in a.sources if s in set(source_of.values())],
        "note": (
            "Merged from separate keystone runs. Seed counts are NOT equal across "
            "endpoints: the two large CYP endpoints were run with fewer seeds "
            "because their sample size makes a full sweep disproportionately "
            "expensive. Interval widths must be read with seeds_by_endpoint in view."
        ),
        "per_run": per_run,
    }
    dest = os.path.join(ROOT, a.outdir, "results.json")
    io.open(dest, "w", encoding="utf-8", newline="\n").write(
        json.dumps(out, ensure_ascii=False, indent=1)
    )

    print("\n[merge] %d endpoints, %d records -> %s" % (len(seeds_by_ep), len(per_run), dest))
    print("%-34s %s" % ("endpoint", "seeds"))
    for ep in sorted(seeds_by_ep):
        print("%-34s %d" % (ep, len(seeds_by_ep[ep])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
