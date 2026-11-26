# -*- coding: utf-8 -*-
"""全生命周期 run_report（K5/"6 个月日志"的可执行替代）。

问题：评审要求"6 个月 run_report"才能做命令收敛决策。但本 skill 首次提交是
2026-11-05（见 logs/bootstrap_20261105_*），截至今天生命周期仅约 3 周，
**物理上不存在 6 个月日志**。等待 6 个月不是"欠账"，而是时间未到。

正确做法：把已经存在的**全生命周期**真实调用记录汇总成一份带数据窗声明的
run_report，作为收敛决策的证据表（不是删减决定）。等真实 6 个月窗口到达后，
重跑本脚本即可自动扩展窗口，无需改代码。

数据源（全部只读，不修改）：
  - fullrun_20261122/runlog.jsonl   逐条命令 + rc + 秒数
  - logs/*.log                      命令串扫描
  - references/COMMAND_USAGE_CENSUS.md 里已登记的窗口外调用

输出：references/RUN_REPORT_LIFECYCLE.md
运行：python tools/run_report_lifecycle.py
"""

from __future__ import annotations

import glob
import io
import json
import os
import re
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from adt import command_roles as cr  # noqa: E402


def file_mtime(p):
    try:
        return datetime.fromtimestamp(os.path.getmtime(p))
    except Exception:  # noqa: BLE001
        return None


def scan():
    """返回 (records, window_start, window_end, sources)。records: list of dict."""
    recs = []
    dates = []
    sources = []

    # 1) fullrun runlog（结构化，最可信）
    rl = os.path.join(ROOT, "fullrun_20261122", "runlog.jsonl")
    n_runlog = 0
    if os.path.exists(rl):
        mt = file_mtime(rl)
        if mt:
            dates.append(mt)
        for line in io.open(rl, encoding="utf-8", errors="replace"):
            try:
                d = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            recs.append(
                dict(
                    cmd=(d.get("id") or "").strip(),
                    rc=d.get("rc"),
                    ok=d.get("ok"),
                    seconds=d.get("seconds"),
                    src="runlog",
                )
            )
            n_runlog += 1
        sources.append("`fullrun_20261122/runlog.jsonl`（%d 条结构化调用）" % n_runlog)

    # 2) logs/*.log 命令串扫描 + 时间窗
    names = set(cr.ROLES)
    pat = re.compile(r"(?:adt|adt\.cli)\s+([a-z0-9\-]+)")
    n_logs = 0
    logfiles = glob.glob(os.path.join(ROOT, "logs", "*.log"))
    for p in logfiles:
        mt = file_mtime(p)
        if mt:
            dates.append(mt)
        try:
            txt = io.open(p, encoding="utf-8", errors="replace").read()
        except Exception:  # noqa: BLE001
            continue
        for m in pat.finditer(txt):
            cmd = m.group(1)
            if cmd in names:
                recs.append(
                    dict(
                        cmd=cmd, rc=None, ok=None, seconds=None, src=os.path.basename(p)
                    )
                )
                n_logs += 1
    if logfiles:
        sources.append(
            "`logs/*.log`（%d 个日志文件，%d 条命令串）" % (len(logfiles), n_logs)
        )

    start = min(dates).strftime("%Y-%m-%d") if dates else "unknown"
    end = max(dates).strftime("%Y-%m-%d") if dates else "unknown"
    return recs, start, end, sources


def main():
    recs, start, end, sources = scan()
    counts = {}
    fails = 0
    secs = 0.0
    for r in recs:
        c = r["cmd"]
        if not c:
            continue
        counts[c] = counts.get(c, 0) + 1
        if r["ok"] is False or (isinstance(r["rc"], int) and r["rc"] >= 400):
            fails += 1
        if isinstance(r["seconds"], (int, float)):
            secs += float(r["seconds"])

    roles = cr.ROLES
    registered = len(roles)
    used = len([c for c in counts if c in roles])
    days = "未知"
    try:
        d0 = datetime.strptime(start, "%Y-%m-%d")
        d1 = datetime.strptime(end, "%Y-%m-%d")
        days = "%d 天" % (d1 - d0).days
    except Exception:  # noqa: BLE001
        pass

    lines = [
        "# 全生命周期 run_report（命令收敛决策证据表）",
        "",
        "> 生成器：`tools/run_report_lifecycle.py`（可重算）。",
        "> **数据窗声明**：本 skill 首次提交 2026-11-05，生命周期约 3 周（%s → %s，%s）。"
        % (start, end, days),
        "> 因此**不存在 6 个月日志**——这不是欠账，而是时间未到。本表是"
        "已观测窗口的真实证据，只支持分阶段收敛提案，不支持「已删减」结论。",
        "> 6 个月窗口到达后重跑本脚本即可自动扩展，无需改代码。",
        "",
        "## 1. 数据源",
        "",
    ]
    for s in sources:
        lines.append("- " + s)
    lines += [
        "",
        "## 2. 汇总",
        "",
        "| 口径 | 数值 |",
        "|---|---|",
        "| 观测数据窗 | %s → %s（%s） |" % (start, end, days),
        "| 注册命令总数 | %d |" % registered,
        "| 窗口内有调用的命令 | %d |" % used,
        "| 窗口内零调用的命令 | %d |" % (registered - used),
        "| 结构化调用条数（runlog） | %d |"
        % len([r for r in recs if r["src"] == "runlog"]),
        "| 日志命令串条数 | %d |" % len([r for r in recs if r["src"] != "runlog"]),
        "| runlog 记录失败数 | %d |" % fails,
        "| runlog 累计执行秒数 | %.1f |" % secs,
        "",
        "## 3. 高频命令（Top 20）",
        "",
        "| 命令 | 层 | evidence_role | 调用次数 |",
        "|---|---|---|---|",
    ]
    for cmd, n in sorted(counts.items(), key=lambda x: (-x[1], x[0]))[:20]:
        m = roles.get(cmd, {})
        lines.append(
            "| `%s` | %s | %s | %d |"
            % (cmd, m.get("layer", "?"), m.get("evidence_role", "?"), n)
        )
    lines += [
        "",
        "## 4. 收敛决策纪律",
        "",
        "1. 本表**不是**删减决定：evidence 层命令（门禁/审计）平时零调用、发布/审稿时必跑，"
        "   零调用 ≠ 可删。",
        "2. 真正的删减门槛仍是「6 个月零调用 + 非门禁层 + 非契约端点」三者同时满足；"
        "   当前窗口只有 3 周，任何命令都**尚未**满足时间条件。",
        "3. 建议的「核心 20 / peripheral 58」仅作文档分层声明，不物理删除，保留可复算路径。",
        "4. 本表取代旧的「等 6 个月」待办：时间到达后重跑即可，无需人工复算。",
        "",
    ]

    p = os.path.join(ROOT, "references", "RUN_REPORT_LIFECYCLE.md")
    io.open(p, "w", encoding="utf-8", newline="\n").write("\n".join(lines))
    print(
        "[run_report] 数据窗 %s→%s；有调用 %d/%d；%d 条调用 -> references/RUN_REPORT_LIFECYCLE.md"
        % (start, end, used, registered, len(recs))
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
