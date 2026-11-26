# -*- coding: utf-8 -*-
"""一条命令的换机自检：环境 → API 死代码 → 默认测试 → 发布门禁。

不是"跑通即通过"：每一步都保留返回码与输出尾部，失败即停并给出可定位信息。
用法：
    python tools/verify_all.py --quick      # 跳过 15 分钟 smoke，只做静态/环境
    python tools/verify_all.py              # 完整
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run(name, cmd, *, ok_codes=(0,), timeout=1200):
    t0 = time.time()
    p = subprocess.run(
        cmd,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    ok = p.returncode in ok_codes
    print(
        "[%s] %s rc=%s %.1fs"
        % ("OK" if ok else "FAIL", name, p.returncode, time.time() - t0)
    )
    if not ok:
        print((p.stdout or "")[-2500:])
        print((p.stderr or "")[-1500:])
    return {
        "name": name,
        "ok": ok,
        "rc": p.returncode,
        "tail": ((p.stdout or "") + (p.stderr or ""))[-1200:],
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--json-out", default="logs/verify_all.json")
    a = ap.parse_args(argv)
    steps = [
        run(
            "env-audit",
            [sys.executable, "-m", "adt", "env-audit", "--quiet"],
            ok_codes=(0, 2),
            timeout=600,
        ),
        run("api-usage", [sys.executable, "tools/api_usage_audit.py"], timeout=300),
        run(
            "version-audit",
            [sys.executable, "-m", "adt.version", "--strict"],
            timeout=300,
        ),
    ]
    if not a.quick:
        steps.append(
            run(
                "smoke",
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "tests/test_smoke_pytest.py",
                    "-q",
                    "-x",
                ],
                timeout=3600,
            )
        )
    steps.append(
        run(
            "release-check", [sys.executable, "-m", "adt", "release-check"], timeout=600
        )
    )
    ok = all(s["ok"] for s in steps)
    os.makedirs(os.path.dirname(os.path.join(ROOT, a.json_out)), exist_ok=True)
    with open(os.path.join(ROOT, a.json_out), "w", encoding="utf-8") as fh:
        json.dump({"ok": ok, "steps": steps}, fh, ensure_ascii=False, indent=1)
    print("VERIFY_OK" if ok else "VERIFY_FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
