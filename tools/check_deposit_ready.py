# -*- coding: utf-8 -*-
"""Pre-submission readiness check for the deposit and the manuscript.

Why this exists
---------------
Two placeholders in the manuscript cannot be filled by the authors of the code:
the public repository URL and the minted Zenodo DOI. Both depend on an account
action, and both are the kind of thing that gets forgotten in the last hour
before a submission window closes. This script turns "did we remember?" into a
command with an exit code.

It checks three classes of problem:

  1. Declared artefacts that do not exist (a checklist that names files which
     are not in the repository is worse than no checklist).
  2. Unfilled placeholders anywhere in the deposit or the manuscript.
  3. Repository state: tag present, working tree clean, remote configured.

Usage
-----
    python tools/check_deposit_ready.py
    python tools/check_deposit_ready.py --paper ../manuscript.md
    python tools/check_deposit_ready.py --strict   # warnings become failures

Exit codes: 0 ready, 1 blocking problems, 2 usage error.
"""

from __future__ import annotations

import argparse
import io
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Files the Declarations section promises the reader will find.
DECLARED = [
    ("LICENSE", "licence text at the repository root"),
    ("README.md", "installation, minimal example, table-to-command map"),
    ("reproduce.sh", "minimal reproduction entry point"),
    ("Makefile", "wrapper for the entry point"),
    ("requirements.lock", "environment lock"),
    ("docker/Dockerfile.repro", "container recipe"),
    ("deposit/EXPECTED_SHA256.json", "checksum manifest"),
    ("references/RETRAIN_DRIFT.md", "retraining comparison"),
    ("PREREG_STAGE1_PACKAGE.md", "frozen protocol"),
    (".zenodo.json", "deposit metadata"),
    ("CITATION.cff", "citation metadata"),
    ("DEPOSIT_CHECKLIST.md", "the account actions only the author can perform"),
]

# Patterns that must not survive into a submitted manuscript or deposit.
# Each is (regex, human label). Order matters only for readability.
PLACEHOLDERS = [
    (r"\[https?://github\.com/ORG/", "repository URL placeholder"),
    (r"zenodo\.x{4,}", "Zenodo DOI placeholder"),
    (r"zenodo\.XXXXXXX", "Zenodo DOI placeholder"),
    (r"\[OSI-approved", "licence placeholder"),
    (r"sha256:\[\.\.\.\]", "container digest placeholder"),
    (r"\[作者填写\]", "author placeholder"),
    (r"AUTHOR NAME", "author placeholder"),
    (r"\[AUTHOR", "author placeholder"),
]

# Scanned by default. The manuscript is added via --paper because it normally
# lives outside the repository.
DEFAULT_SCAN = [
    "README.md",
    ".zenodo.json",
    "CITATION.cff",
    "reproduce.sh",
    "PREREG_STAGE1_PACKAGE.md",
]


def sh(cmd):
    p = subprocess.run(
        cmd,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()


def check_declared():
    problems, notes = [], []
    print("[1] Declared artefacts")
    for rel, why in DECLARED:
        p = os.path.join(ROOT, rel)
        if os.path.exists(p):
            print("    OK        %-34s %s" % (rel, _short_note(rel, p)))
        else:
            print("    MISSING   %-34s (%s)" % (rel, why))
            problems.append("%s is declared in the manuscript but absent" % rel)
    # Licence must actually be an OSI licence, not an empty file.
    lic = os.path.join(ROOT, "LICENSE")
    if os.path.exists(lic):
        head = io.open(lic, encoding="utf-8", errors="replace").read(400)
        m = re.search(
            r"MIT License|Apache License|BSD 3-Clause|Mozilla Public License",
            head,
            re.I,
        )
        if m:
            notes.append("LICENSE identified as: %s" % m.group(0))
        else:
            problems.append(
                "LICENSE does not name a recognisable OSI licence in its first 400 chars"
            )
    return problems, notes


def _short_note(rel, path):
    if rel == "deposit/EXPECTED_SHA256.json":
        try:
            import json

            d = json.load(io.open(path, encoding="utf-8"))
            return "%d digests" % len(d.get("files", {}))
        except Exception:
            return "unreadable"
    if rel == "reproduce.sh":
        return "executable" if os.access(path, os.X_OK) else "NOT executable"
    return "%d bytes" % os.path.getsize(path)


def check_placeholders(paper):
    problems = []
    print("[2] Placeholder scan")
    targets = [os.path.join(ROOT, r) for r in DEFAULT_SCAN]
    if paper:
        targets.append(os.path.abspath(paper))
    hit = False
    for path in targets:
        if not os.path.exists(path):
            continue
        rel = os.path.relpath(path, ROOT) if path.startswith(ROOT) else path
        for lineno, line in enumerate(
            io.open(path, encoding="utf-8", errors="replace"), 1
        ):
            for rx, label in PLACEHOLDERS:
                if re.search(rx, line):
                    hit = True
                    print("    FOUND     %s:%d  %s" % (rel, lineno, label))
                    problems.append("%s:%d %s" % (rel, lineno, label))
    if not hit:
        print("    none")
    return problems


def check_git(strict):
    problems, warnings = [], []
    print("[3] Repository state")
    rc, out, _ = sh(["git", "rev-parse", "--is-inside-work-tree"])
    if rc != 0:
        print("    NOT a git repository")
        problems.append("deposit is not a git repository")
        return problems, warnings
    rc, branch, _ = sh(["git", "branch", "--show-current"])
    print("    branch    %s" % (branch or "(detached)"))
    rc, tags, _ = sh(["git", "describe", "--tags", "--abbrev=0"])
    if rc == 0 and tags:
        print("    tag       %s" % tags)
    else:
        print("    tag       NONE")
        problems.append("no annotated tag; the manuscript cites one")
    rc, dirty, _ = sh(["git", "status", "--porcelain"])
    n = len([x for x in dirty.splitlines() if x.strip()])
    print("    dirty     %d file(s)" % n)
    if n:
        problems.append("%d uncommitted change(s)" % n)
    rc, remote, _ = sh(["git", "remote", "-v"])
    if remote:
        print("    remote    %s" % remote.splitlines()[0])
    else:
        print("    remote    NONE  <-- not pushed; the URL in the paper cannot resolve")
        problems.append("no git remote: the repository is local only")
    rc, unpushed, _ = sh(
        ["git", "log", "--oneline", "--branches", "--not", "--remotes"]
    )
    if rc == 0 and unpushed:
        warnings.append("%d commit(s) not on any remote" % len(unpushed.splitlines()))
    return problems, warnings


def check_hashes():
    problems = []
    print("[4] Deterministic table checksums")
    p = subprocess.run(
        [sys.executable, os.path.join(ROOT, "tools", "verify_table_hashes.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    tail = (p.stdout or "").strip().splitlines()
    print("    %s" % (tail[-1] if tail else "(no output)"))
    if p.returncode != 0:
        problems.append("table checksums do not match the manifest")
    return problems


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--paper", default=None, help="path to the manuscript markdown to scan as well"
    )
    ap.add_argument("--strict", action="store_true", help="treat warnings as failures")
    a = ap.parse_args(argv)

    print("admet-screening deposit readiness")
    print("=" * 62)

    p1, notes1 = check_declared()
    p2 = check_placeholders(a.paper)
    p3, w3 = check_git(a.strict)
    p4 = check_hashes()

    print("=" * 62)
    for n in notes1:
        print("note:      %s" % n)
    for w in w3:
        print("warning:   %s" % w)
    blocking = p1 + p2 + p3 + p4
    if blocking:
        print("NOT READY (%d blocking problem(s)):" % len(blocking))
        for b in blocking:
            print("  - %s" % b)
        if a.strict and w3:
            print("  (plus %d warning(s) under --strict)" % len(w3))
            return 1
        return 1
    if a.strict and w3:
        print("NOT READY under --strict (%d warning(s))" % len(w3))
        return 1
    print("READY: all declared artefacts present, no placeholders, remote configured.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
