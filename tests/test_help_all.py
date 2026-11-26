# -*- coding: utf-8 -*-
"""全部 CLI 子命令 --help 冒烟测试（防 argparse %% 崩溃类静默缺陷）。

背景（来自反向 skill 的真实事故）：`argparse` 会对 help 字符串做 % 格式化，
help 里裸写 "%" ("默认 10%，须预注册") 会抛
`ValueError: unsupported format character`。该缺陷只影响 --help，不影响主流程，
因此原有功能断言全过、长期潜伏。**脚本自身也必须被审计。**

本测试对每个子命令跑 `python -m adt.cli <cmd> --help`，断言：
  1) 退出码 0
  2) 输出里没有 "Traceback"
  3) 有 "usage:" 行

跑法: python tests/test_help_all.py
"""
import contextlib
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from adt import cli as CLI  # noqa: E402

CMDS = [
    "normalize", "saturate", "bt", "xeno-prep", "xeno-ingest", "chembl",
    "validate", "web", "reliab", "sensitize", "coverage", "background",
    "rank", "benchmark", "tier", "gate", "desire", "ledger", "transport",
    "pbpk", "report", "merge",
    # v3.0.0 新增
    "qaf", "conformal", "reporting",
    # v3.1.0 学术化升级
    "independence", "certainty", "selective", "failure-modes", "failmodes",
    "perturb", "decision-value", "dvalue", "dst",
    # v3.1.1 外部公开数据接入（B/G）
    "external", "baseline",
    # v3.2.0 工作包 F/K
    "conformal-check", "ccheck", "conformal-scale", "cscale", "landscape",
    # 2026-11-19 loop 注册（add_parser(_name) 不在静态 regex 里，必须显式列出）
    "evidence-streams", "silent-failure", "perm-contribution", "deviation",
    "retrieval-card", "power-analysis", "external-compare", "local-tools",
]


def _discover_cmds():
    """从 adt/cli.py 源码里抓出所有 add_parser("x") 的子命令名。

    C-2026-11-03：此前 CMDS 是手写清单，实际只覆盖 41/60 个子命令——24 个从未做过
    --help 冒烟（含本文件开头描述的 argparse `%` 崩溃类缺陷的藏身处）。手写清单必然
    继续腐烂，故改为**自动发现 + 静态清单并集**：新增子命令无需改测试也会被审计。
    """
    import re
    src = os.path.join(HERE, "adt", "cli.py")
    try:
        with open(src, encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return []
    return sorted(set(re.findall(r'add_parser\(\s*"([a-z0-9-]+)"', text)))


CMDS = sorted(set(CMDS) | set(_discover_cmds()))

PASS = 0
FAIL = []


def check(name, cond, detail=""):
    global PASS
    if cond:
        PASS += 1
        print("  ok  %s" % name)
    else:
        FAIL.append(name)
        print("FAIL  %s  %s" % (name, detail))


for cmd in CMDS:
    # 2026-11-22 性能修复：旧实现对 104 个子命令各起一次 `python -m adt.cli`，
    # 在 Windows 上单次导入 rdkit + 解析 4.7k 行 CLI 可达数十秒，600s 超时
    # 直接把默认 smoke 拖红。改为同进程调用 main([cmd,"--help"])，
    # 只测 argparse 帮助渲染，不启动 104 个进程；耗时从 ~15min 降到秒级。
    buf = io.StringIO()
    rc = 0
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            CLI.main([cmd, "--help"])
    except SystemExit as exc:
        rc = int(exc.code or 0)
    out = buf.getvalue()
    ok = (rc == 0 and "Traceback" not in out and "usage:" in out)
    detail = ""
    if not ok:
        detail = "rc=%s %s" % (rc, out[-300:])
    check("%s --help" % cmd, ok, detail)

print()
print("passed %d / failed %d" % (PASS, len(FAIL)))
if FAIL:
    print("FAILED:", FAIL)
    sys.exit(1)
print("ALL OK")
