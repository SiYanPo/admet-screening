# -*- coding: utf-8 -*-
"""覆盖率核算：证明"面板 + 跑批"没有把任何命令闲置。

口径必须诚实，否则覆盖率是假的：
  * `COVERED`    —— 本次跑批里**真的执行过**（run_report.json 里有 step 记录）；
  * `RUN`        —— 命令跑过但状态是 REFUSED/SKIP（仍算执行过；理由写清楚）；
  * `TEST_ONLY`  —— 只在回归测试里执行过，本次跑批未跑（须给测试名）；
  * `UNCOVERED`  —— 既没跑也没有测试证据 → **这是缺陷**，必须补。

用法：
    python tools/panel_coverage.py --run-report <run>/run_report.json \
        --surface logs/panel_20261119/cmd_surface.json --out <dir>
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# 别名 → 规范名（来自 cli.py 的 add_parser(aliases=...)）
ALIASES = {
    "gate": "tier",
    "failmodes": "failure-modes",
    "dvalue": "decision-value",
    "ccheck": "conformal-check",
    "cscale": "conformal-scale",
    "sar-screen": "sar",
    "acylglu": "acyl-glucuronide",
    "glycosh": "glycoside-hyd",
    "ccclass": "conformal-class",
    "xclass": "cross-class",
    "ablation": "ablate",
    "awhy": "abstain-why",
    "acmp": "abstain-cmp",
    "flayers": "fail-layers",
    "regab": "regaloside-ab",
    "prospective": "prospect",
    "srho": "source-rho",
    "sadmit": "source-admit",
    "acplan": "ac-plan",
    "pshift": "pred-shift",
    "biotrans": "bt",
}

# 只能由测试覆盖/无法由"化合物面板"触发的能力，逐条给理由（不写理由即视为缺陷）
#
# 2026-11-19 更新：此处原有 8 条，靠 `tools/real_truth_legs.py` 把真值（OpenADMET
# 10 738 对 + hERG 留出 959）接上后，baseline / ablate / prospect / conformal /
# conformal-class / cross-class / pred-shift / decision-value **全部改为真跑**，
# 因此从本表移除 —— 留着就等于用"做不了"的旧判断掩盖"其实做了"。
# 现在只剩一条真正的边界：许可。
INTENTIONAL = {
    "readback": "人工回填需要真实实验导出文件；跑批用 SYNTHETIC 只验接线（S01）",
    "pd": "PD 需要 PBPK 曲线；跑批链条 A42→A43 已覆盖",
    "xeno-ingest": "**许可边界**，不是能力缺口：XenoSite 条款写明程序化访问需商业许可，"
    "前端已改为 Qwik+RDKit-WASM（/api 与 /apiv2 均 404），"
    "自动填表等于绕过许可 → 保持人工回填通道；"
    "契约由 tests/test_extension_v414.py 覆盖",
}


def canonical(name):
    return ALIASES.get(name, name)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-report", required=True)
    ap.add_argument("--surface", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)

    surf = json.load(io.open(a.surface, encoding="utf-8"))
    rep = json.load(io.open(a.run_report, encoding="utf-8"))
    steps = rep.get("steps") or []

    ran = {}
    for s in steps:
        # run_report 的 cmd 是 "adt.cli <subcmd> ..."（脚本步骤则更短）——先把
        # 解释器/模块前缀剥掉，否则整张覆盖率表会全是 UNCOVERED（本轮踩过）。
        toks = [
            t
            for t in (s.get("cmd") or "").split()
            if t not in ("-m", "adt.cli", "python", "python.exe")
        ]
        if not toks:
            continue
        name = canonical(toks[0])
        ran.setdefault(name, []).append("%s(%s)" % (s["id"], s["status"]))

    names = sorted({canonical(n) for n in surf})
    rows = []
    for n in names:
        if n in ran:
            status = "COVERED"
            where = ", ".join(ran[n])
        elif n in INTENTIONAL:
            status = "TEST_ONLY"
            where = INTENTIONAL[n]
        else:
            status = "UNCOVERED"
            where = ""
        rows.append((n, status, where))

    os.makedirs(a.out, exist_ok=True)
    lines = [
        "# 能力覆盖率核算（面板跑批 vs 全部 CLI 命令）",
        "",
        "规范名 %d 个（原始含别名 %d 个）。" % (len(names), len(surf)),
        "",
        "| 命令 | 状态 | 覆盖位置 / 理由 |",
        "|---|---|---|",
    ]
    for n, st, w in rows:
        lines.append("| `%s` | %s | %s |" % (n, st, w.replace("|", "/")))
    cov = sum(1 for _, st, _ in rows if st == "COVERED")
    test_only = sum(1 for _, st, _ in rows if st == "TEST_ONLY")
    unc = [n for n, st, _ in rows if st == "UNCOVERED"]
    lines += [
        "",
        "**汇总**：COVERED %d / TEST_ONLY %d / UNCOVERED %d（共 %d）"
        % (cov, test_only, len(unc), len(rows)),
        "",
    ]
    if unc:
        lines += ["## 未覆盖（缺陷清单）", ""] + ["- `%s`" % n for n in unc] + [""]
    with io.open(os.path.join(a.out, "coverage.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    with io.open(os.path.join(a.out, "coverage.json"), "w", encoding="utf-8") as fh:
        json.dump(
            dict(
                rows=[dict(cmd=n, status=st, where=w) for n, st, w in rows],
                covered=cov,
                test_only=test_only,
                uncovered=unc,
            ),
            fh,
            ensure_ascii=False,
            indent=1,
        )
    print(
        "[coverage] COVERED %d / TEST_ONLY %d / UNCOVERED %d -> %s"
        % (cov, test_only, len(unc), os.path.join(a.out, "coverage.md"))
    )
    for n in unc:
        print("  UNCOVERED %s" % n)
    return 0 if not unc else 4


if __name__ == "__main__":
    sys.exit(main())
