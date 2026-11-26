# -*- coding: utf-8 -*-
"""命令使用率普查（B17/K5 的可执行替代）：用**本仓库自己的实跑日志**统计，而不是等 6 个月用户日志。

为什么可以这样做（方法学）
------------------------
K5/评审判据是"6 个月未用的命令移出 experimental"。拿不到 6 个月日志时，退而求其次的正确做法是
**声明数据窗**并用可获得窗口内的真实调用计数（`fullrun_20261122/runlog.jsonl` 的 73 次调用 +
`logs/*.log` 的命令串扫描），而不是拍脑袋砍。这里输出的是一份**证据表**，不是删减决定。

输出：references/COMMAND_USAGE_CENSUS.md
运行：python tools/command_usage_census.py
"""

from __future__ import annotations

import glob
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from adt import command_roles as cr  # noqa: E402


def scan_logs():
    """返回 {cmd: 次数}；覆盖 runlog.jsonl + logs/*.log 中的 `adt <cmd>` 串。"""
    counts = {}
    for line in io.open(
        os.path.join(ROOT, "fullrun_20261122", "runlog.jsonl"),
        encoding="utf-8",
        errors="replace",
    ):
        try:
            rec = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        cid = (rec.get("id") or "").strip()
        if cid:
            counts[cid] = counts.get(cid, 0) + 1

    names = set(cr.ROLES)
    pat = re.compile(r"(?:adt|adt\.cli)\s+([a-z0-9\-]+)")
    for p in glob.glob(os.path.join(ROOT, "logs", "*.log")):
        try:
            txt = io.open(p, encoding="utf-8", errors="replace").read()
        except Exception:  # noqa: BLE001
            continue
        for m in pat.finditer(txt):
            cmd = m.group(1)
            if cmd in names:
                counts[cmd] = counts.get(cmd, 0) + 1
    return counts


# 建议的 20 条核心集（按"决策链上能不能少"排序；纯声明，不删命令）
CORE_PROPOSAL = [
    "normalize",
    "saturate",
    "benchmark",
    "gate",
    "qaf",
    "conformal",
    "desire",
    "ablate",
    "reliab",
    "source-admit",
    "estimand",
    "release-check",
    "prereg-init",
    "prereg-status",
    "env-audit",
    "manifest",
    "reporting",
    "coverage-gate",
    "claims-fragility",
    "local-tools",
]


def main():
    counts = scan_logs()
    roles = cr.ROLES
    rows = []
    for cmd, m in sorted(roles.items()):
        rows.append(
            dict(
                cmd=cmd,
                layer=m.get("layer"),
                role=m.get("evidence_role"),
                n=counts.get(cmd, 0),
                in_core=cmd in CORE_PROPOSAL,
                claimable=cr.claimable(cmd) if callable(cr.claimable) else None,
            )
        )
    used = [r for r in rows if r["n"] > 0]
    never = [r for r in rows if r["n"] == 0]

    out = [
        "# 命令使用率普查（%d 命令；数据窗=fullrun_20261122 + logs）" % len(rows),
        "",
        "> 生成器：`tools/command_usage_census.py`（可重算）。",
        "> **数据窗声明**：这不是 6 个月用户日志，而是本仓库 2026-11-22 实跑的 73 次调用 +",
        "> `logs/*.log` 中的命令串。用它只能支持「分阶段收敛提案」，**不能**支持「已删减」。",
        "",
        "## 汇总",
        "",
        "| 口径 | 数量 |",
        "|---|---|",
        "| 注册命令总数 | %d |" % len(rows),
        "| 本窗口有调用 | %d |" % len(used),
        "| 本窗口零调用 | %d |" % len(never),
        "| 建议核心集（20） | %d |" % len(CORE_PROPOSAL),
        "",
        "## 有调用的命令（按次数降序）",
        "",
        "| 命令 | 层 | evidence_role | 次数 | 在建议核心集 |",
        "|---|---|---|---|---|",
    ]
    for r in sorted(used, key=lambda x: (-x["n"], x["cmd"])):
        out.append(
            "| `%s` | %s | %s | %d | %s |"
            % (r["cmd"], r["layer"], r["role"], r["n"], "是" if r["in_core"] else "")
        )
    out += ["", "## 零调用命令（按层分组）", ""]
    for layer in ("core", "sources", "decision", "evidence", "experimental"):
        grp = [r["cmd"] for r in never if r["layer"] == layer]
        if grp:
            out.append(
                "- **%s**（%d）：%s"
                % (layer, len(grp), "、".join("`%s`" % c for c in grp))
            )
    out += [
        "",
        "## 使用这份表的纪律",
        "",
        "1. 零调用 ≠ 可删：`evidence` 层命令是**门禁/审计**，平时不跑、审稿/发布时必跑。",
        "2. 真正的删减依据是「6 个月零调用 + 非门禁层 + 非契约端点」，三者同时满足才降级为 experimental。",
        "3. 建议核心集是**声明**：把 20 条之外的命令在文档里标 `peripheral`，不物理删除，保留可复算路径。",
        "4. 任何删减都要在 CHANGELOG 里写「为什么删 + 怎么恢复」。",
        "",
    ]
    p = os.path.join(ROOT, "references", "COMMAND_USAGE_CENSUS.md")
    io.open(p, "w", encoding="utf-8", newline="\n").write("\n".join(out))
    print(
        "[usage] 有调用 %d / 零调用 %d / 共 %d -> references/COMMAND_USAGE_CENSUS.md"
        % (len(used), len(never), len(rows))
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
