# -*- coding: utf-8 -*-
"""API 使用审计：找出"定义了但从未被任何代码/测试/工具引用"的公共函数。

为什么需要：功能堆砌的典型症状不是代码报错，而是"模块在、函数在、永远不跑"。
静态引用不是运行时证明，但它能廉价地把"零调用"从盲区变成清单；
清单里的每一条必须显式登记（兼容入口/演示入口/交互辅助），否则 CI 失败。

用法：
    python tools/api_usage_audit.py --json-out logs/api_usage.json
退出码：0=全部登记；4=存在未登记零引用公共函数；1=输入错误。
"""

from __future__ import annotations

import argparse
import ast
import collections
import io
import json
import os
import sys
import tokenize

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_ALLOWLIST = os.path.join(ROOT, "references", "API_USAGE_ALLOWLIST.json")


def _iter_scan_files():
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [
            d
            for d in dirs
            if d
            not in (
                ".git",
                "__pycache__",
                ".pytest_cache",
                ".pytest_tmp",
                "build",
                "dist",
                "instances",
                ".scratch",
                "out",
                "out2",
                "run6",
            )
        ]
        rel = os.path.relpath(base, ROOT).replace("\\", "/")
        for f in files:
            if not f.endswith(".py"):
                continue
            if (
                rel == "adt"
                or rel.startswith("adt/")
                or rel == "tests"
                or rel.startswith("tests/")
                or rel == "tools"
                or rel.startswith("tools/")
                or (rel == "." and (f.startswith("run_") or f == "bootstrap.py"))
            ):
                yield os.path.join(base, f)


def _definitions():
    out = {}
    adt = os.path.join(ROOT, "adt")
    for fn in sorted(os.listdir(adt)):
        if not fn.endswith(".py"):
            continue
        p = os.path.join(adt, fn)
        tree = ast.parse(io.open(p, encoding="utf-8").read())
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not node.name.startswith("_"):
                    out["%s.%s" % (fn[:-3], node.name)] = node.lineno
            elif isinstance(node, ast.ClassDef):
                for sub in node.body:
                    if isinstance(
                        sub, (ast.FunctionDef, ast.AsyncFunctionDef)
                    ) and not sub.name.startswith("_"):
                        out["%s.%s.%s" % (fn[:-3], node.name, sub.name)] = sub.lineno
    return out


def _name_counts():
    counts = collections.Counter()
    for p in _iter_scan_files():
        try:
            with open(p, "rb") as fh:
                for tok in tokenize.tokenize(fh.readline):
                    if tok.type == tokenize.NAME:
                        counts[tok.string] += 1
        except (OSError, tokenize.TokenError):
            continue
    return counts


def audit(allowlist_path=DEFAULT_ALLOWLIST):
    defs = _definitions()
    counts = _name_counts()
    allow = {}
    if os.path.exists(allowlist_path):
        allow = json.load(io.open(allowlist_path, encoding="utf-8")).get("allowed", {})
    zero = []
    for key, line in sorted(defs.items()):
        name = key.split(".")[-1]
        if counts[name] <= 1:  # 只出现于 def 本身
            zero.append(
                {
                    "api": key,
                    "line": line,
                    "allowlisted": key in allow,
                    "reason": allow.get(key),
                }
            )
    unregistered = [z for z in zero if not z["allowlisted"]]
    return {
        "n_defs": len(defs),
        "n_zero": len(zero),
        "n_unregistered": len(unregistered),
        "zero": zero,
        "unregistered": unregistered,
        "allowlist_path": allowlist_path,
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--allowlist", default=DEFAULT_ALLOWLIST)
    ap.add_argument("--json-out", default="")
    a = ap.parse_args(argv)
    try:
        r = audit(a.allowlist)
    except Exception as exc:
        print("api_usage_audit failed: %s" % exc)
        return 1
    if a.json_out:
        os.makedirs(os.path.dirname(os.path.abspath(a.json_out)), exist_ok=True)
        with io.open(a.json_out, "w", encoding="utf-8") as fh:
            json.dump(r, fh, ensure_ascii=False, indent=1)
    print(
        "[api-usage] defs=%d zero=%d unregistered=%d"
        % (r["n_defs"], r["n_zero"], r["n_unregistered"])
    )
    for z in r["unregistered"]:
        print(
            "  UNREGISTERED %s (adt/%s:%d)"
            % (z["api"], z["api"].split(".")[0] + ".py", z["line"])
        )
    return 0 if not r["unregistered"] else 4


if __name__ == "__main__":
    sys.exit(main())
