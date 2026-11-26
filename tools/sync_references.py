# -*- coding: utf-8 -*-
"""把 references/*.yaml 同步到 adt/_data/（随包分发的判据快照）。

用法：
    python tools/sync_references.py            # 同步
    python tools/sync_references.py --check    # 只检查，有漂移则 exit 1

为什么需要这个脚本：`pip install` 后源码树的 references/ 不在 wheel 里，
而 adt/resref.py 的最后一档回落是包内资源。副本必须与权威源逐字节一致，
否则"我改了 YAML 但装上的版本还在用旧判据"这种事故无法察觉。
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "references")
DST = os.path.join(ROOT, "adt", "_data")

sys.path.insert(0, ROOT)
from adt import resref  # noqa: E402


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    os.makedirs(DST, exist_ok=True)
    missing, drift, same = [], [], []
    for name in resref.SYNCED:
        s = os.path.join(SRC, name)
        d = os.path.join(DST, name)
        if not os.path.isfile(s):
            missing.append(name)
            continue
        if os.path.isfile(d) and sha256(s) == sha256(d):
            same.append(name)
            continue
        drift.append(name)
        if not a.check:
            shutil.copyfile(s, d)
    if a.check:
        for n in missing:
            print("  ✗ 源缺失 %s" % n)
        for n in drift:
            print("  ✗ 未同步 %s" % n)
        print(
            "[sync] 一致 %d / 未同步 %d / 源缺失 %d -> %s"
            % (
                len(same),
                len(drift),
                len(missing),
                "PASS" if not (drift or missing) else "FAIL",
            )
        )
        return 0 if not (drift or missing) else 1
    print(
        "[sync] 复制 %d / 已一致 %d / 源缺失 %d -> %s"
        % (len(drift), len(same), len(missing), DST)
    )
    return 0 if not missing else 1


if __name__ == "__main__":
    sys.exit(main())
