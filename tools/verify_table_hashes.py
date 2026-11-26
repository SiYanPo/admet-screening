# -*- coding: utf-8 -*-
"""Verify (or record) the SHA-256 of the deterministic table outputs.

Why this exists
---------------
The journal's reproducibility criterion is that a third party can check the
reported numbers without trusting the authors. For the cost-dependent tables
this is cheap: every one of them is a pure function of deposited per-seed
records, so the checksum of the regenerated CSV must match the deposited
checksum exactly. A mismatch means either the code or the inputs changed, and
that is exactly the event a reader wants to be told about.

Scope
-----
Only the four CSVs listed below are covered. They are deterministic: no
timestamps, no random draws, no platform-dependent formatting. The rendered
Markdown next to them is NOT covered, because it embeds a data path and is
regenerated on each run; and nothing produced by a model retrain is covered,
because random forests are only reproducible to tolerance across platforms
(see the note in reproduce.sh).

Usage
-----
    python tools/verify_table_hashes.py            # verify
    python tools/verify_table_hashes.py --update   # rewrite after an
                                                   # intentional change
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(ROOT, "deposit", "EXPECTED_SHA256.json")

FILES = [
    "out_sensitivity/table2_paired.csv",
    "out_sensitivity/table_h2_cost_sweep.csv",
    "out_sensitivity/critical_cost.csv",
    "out_sensitivity/critical_cost_transfer.csv",
    # Inputs as well as outputs. The per-seed records are the basis of every
    # number in the paper, so a reader should be able to confirm they received
    # an unaltered copy before regenerating anything from it.
    "out_keystone_v43/results.json",
    "out_keystone_transfer/results.json",
]


def sha256_file(path):
    """SHA-256 with CRLF normalised to LF before hashing.

    Git may check a text file out with CRLF on Windows and LF elsewhere, which
    changes the byte count without changing a single parsed value. Hashing the
    normalised bytes makes the recorded digest a statement about the content
    rather than about the platform, so the check passes on both and a genuine
    edit still fails it.
    """
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk.replace(b"\r\n", b"\n"))
    return h.hexdigest()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--update",
        action="store_true",
        help="rewrite the manifest instead of verifying it",
    )
    a = ap.parse_args(argv)

    digests, missing = {}, []
    for rel in FILES:
        p = os.path.join(ROOT, rel)
        if not os.path.exists(p):
            missing.append(rel)
            continue
        digests[rel] = sha256_file(p)
    if missing:
        print("[hash] missing outputs: " + ", ".join(missing))
        return 2

    if a.update:
        os.makedirs(os.path.dirname(MANIFEST), exist_ok=True)
        payload = {
            "note": (
                "SHA-256 of the four deterministic table outputs and of the two "
                "per-seed result files, computed after normalising CRLF to LF so that "
                "the digest describes content rather than the checkout platform. "
                'Regenerate with "./reproduce.sh"; verify with '
                '"python tools/verify_table_hashes.py". Nothing that depends on a model '
                "retrain is included, because retraining is reproducible to tolerance "
                "rather than byte for byte."
            ),
            "generated_at": datetime.datetime.now()
            .astimezone()
            .isoformat(timespec="seconds"),
            "algorithm": "sha256",
            "files": digests,
        }
        io.open(MANIFEST, "w", encoding="utf-8", newline="\n").write(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        )
        print("[hash] wrote %d entries to deposit/EXPECTED_SHA256.json" % len(digests))
        return 0

    if not os.path.exists(MANIFEST):
        print(
            "[hash] no manifest at deposit/EXPECTED_SHA256.json; "
            "run with --update to create it"
        )
        return 3

    exp = json.load(io.open(MANIFEST, encoding="utf-8"))["files"]
    bad = []
    for rel in FILES:
        want = exp.get(rel)
        got = digests[rel]
        if want is None:
            print("  %-46s NOT-IN-MANIFEST" % rel)
            bad.append(rel)
        elif want == got:
            print("  %-46s OK   %s" % (rel, got[:16]))
        else:
            print("  %-46s DIFF" % rel)
            print("      expected %s" % want)
            print("      obtained %s" % got)
            bad.append(rel)
    if bad:
        print(
            "[hash] %d file(s) differ. If the change was intentional, rerun with "
            "--update and update the manuscript tables." % len(bad)
        )
        return 1
    print("[hash] all %d deterministic table outputs match." % len(FILES))
    return 0


if __name__ == "__main__":
    sys.exit(main())
