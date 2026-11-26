# -*- coding: utf-8 -*-
"""同行评审 §3 疑点 1 / §3 疑点 6 的可复现审计工具。

B12：统计默认 smoke 里每个脚本是否真的执行断言——AST 数 assert 语句 +
     "自定义 check 函数"调用；只 print 不 assert 的脚本被标为 no_assertion，
     必须人工确认其退出码来自真正的检查而非"打印即 rc=0"。
B17：统计 CLI 命令的静态引用率（在 tests/tools/其它命令里被引用），
     6 个月未用无法从静态得知——本工具只给"零静态引用"候选清单，
     真实使用率须用户附 run_report.json；不把静态引用当运行时证明。

用法：python tools/peer_review_audit.py [--json-out logs/peer_review_audit.json]
退出码恒 0（审计报告，不是门禁；是否设门禁由 CI 决定）。
"""

from __future__ import annotations

import argparse
import ast
import io
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _smoke_scripts():
    """从 tests/test_smoke_pytest.py 解析 SCRIPTS 列表，不重复硬编码。"""
    p = os.path.join(ROOT, "tests", "test_smoke_pytest.py")
    tree = ast.parse(io.open(p, encoding="utf-8").read())
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "SCRIPTS":
                    return [ast.literal_eval(e) for e in node.value.elts]
    return []


def audit_smoke_assertions():
    scripts = _smoke_scripts()
    rows = []
    for rel in scripts:
        path = os.path.join(ROOT, rel)
        if not os.path.exists(path):
            rows.append(
                dict(
                    script=rel,
                    exists=False,
                    n_assert=0,
                    check_calls=0,
                    classification="MISSING",
                )
            )
            continue
        try:
            tree = ast.parse(io.open(path, encoding="utf-8").read())
        except SyntaxError as ex:
            rows.append(
                dict(
                    script=rel,
                    exists=True,
                    n_assert=0,
                    check_calls=0,
                    classification="SYNTAX_ERROR",
                    note=str(ex),
                )
            )
            continue
        n_assert = sum(1 for n in ast.walk(tree) if isinstance(n, ast.Assert))
        # 统计 check(...)/check_eq(...) 这类自定义断言函数调用
        n_check = sum(
            1
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and (n.func.id.startswith("check") or n.func.id.startswith("assert"))
        )
        # 是否有 sys.exit(非0) 用于失败信号
        has_exit = any(
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr in ("exit",)
            for n in ast.walk(tree)
        )
        cls = "HAS_ASSERTION" if (n_assert or n_check) else "NO_ASSERTION_FOUND"
        rows.append(
            dict(
                script=rel,
                exists=True,
                n_assert=n_assert,
                check_calls=n_check,
                has_sys_exit=has_exit,
                classification=cls,
            )
        )
    n_no = sum(1 for r in rows if r["classification"] == "NO_ASSERTION_FOUND")
    return dict(
        n_scripts=len(rows),
        n_with_assertion=len(rows) - n_no,
        n_no_assertion=n_no,
        rows=rows,
        note="NO_ASSERTION_FOUND 仅表示静态未见 assert/check；须人工核对"
        "退出码是否来自真实检查（脚本式测试可能用 sys.exit(1)）",
    )


def audit_command_static_usage():
    p = os.path.join(ROOT, "adt", "cli.py")
    src = io.open(p, encoding="utf-8").read()
    cmds = sorted(set(re.findall(r'add_parser\(\s*["\']([\w\-]+)["\']', src)))
    # 在所有 py 文件里找命令名作为字符串出现（排除 cli.py 自身定义行）
    corpus = []
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
                "out",
                "out2",
                "run6",
                "logs",
            )
        ]
        for f in files:
            if f.endswith(".py"):
                fp = os.path.join(base, f)
                if os.path.abspath(fp) == os.path.abspath(p):
                    continue
                try:
                    corpus.append(
                        io.open(fp, encoding="utf-8", errors="replace").read()
                    )
                except Exception:
                    pass
    blob = "\n".join(corpus)
    zero = [c for c in cmds if ("'%s'" % c) not in blob and ('"%s"' % c) not in blob]
    return dict(
        n_commands=len(cmds),
        n_zero_static_reference=len(zero),
        zero_static_reference=zero,
        note="静态零引用≠真实未使用；请用户附 6 个月 run_report.json 再定去留",
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json-out", default=None)
    a = ap.parse_args()
    report = dict(
        smoke_assertions=audit_smoke_assertions(),
        command_static_usage=audit_command_static_usage(),
    )
    if a.json_out:
        os.makedirs(os.path.dirname(os.path.abspath(a.json_out)), exist_ok=True)
        with io.open(a.json_out, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)
    print(
        "smoke: %d scripts, %d with static assertion, %d NO_ASSERTION_FOUND"
        % (
            report["smoke_assertions"]["n_scripts"],
            report["smoke_assertions"]["n_with_assertion"],
            report["smoke_assertions"]["n_no_assertion"],
        )
    )
    print(
        "commands: %d total, %d zero static reference"
        % (
            report["command_static_usage"]["n_commands"],
            report["command_static_usage"]["n_zero_static_reference"],
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
