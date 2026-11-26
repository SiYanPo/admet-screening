# -*- coding: utf-8 -*-
"""未覆盖端点强制声明闸门 —— 把「登记」接进「生产链路」。

## 为什么要这个模块（C82 教训的直接复发）

2026-11-11 在 `references/03_endpoint_rules.yaml` 新增了
`not_covered_endpoints`（CYP 诱导 / TDI / 胶体聚集 / 荧光干扰 / 成醌）。
静态核查发现：**只有 tests/test_interference.py 读它，adt/ 下零生产调用点**。
这正是 `07_case_lessons.md` C82 已记录过的坑：

> 「registry 里登记完整，但没有任何代码读取 ——『写了但没接线』」
> 「任何『登记表驱动』的规则必须有一条 e2e：改 registry → 跑 CLI → 看产物是否变」

静默缺失是可信度漏洞：报告只报 CYP 抑制，读者会默认「DDI 已评估」，
而诱导与时间依赖抑制（TDI）根本未覆盖，方向可能相反。

## 本模块做什么 / 不做什么

- **做**：把登记表渲染成一段**可机器校验**的强制声明（每个未覆盖端点带 HTML
  注释标记 `<!-- coverage:<id> -->`）；`cmd_report` 生成结论段时**无条件追加**；
  `claims_audit --coverage-declaration` 校验对外文本里出现 CYP/DDI 类结论时
  声明是否齐全。改 registry → 声明自动变化 → 缺标记即报错，闭环成立。
- **不做**：不产生 verdict、不进 `reliab` 计票、不自动改写注册表、不把
  `not_covered` 伪装成「已评估阴性」、不给 CYP 诱导/TDI 编造计算值
  （这两项 `required_evidence` 明确是湿实验，代码补不出来）。
- **边界**：结构干扰预警（`adt/interference.py`）补的是**光学/聚集/成醌的
  结构红旗**，不是实验判据；因此这些端点在本表里只从 `not_covered`
  升到 `partially_covered`，仍必须出现在声明中。

## 确定性

声明段不含时间戳；条目按 id 排序；同样输入逐字节一致。
"""

from __future__ import annotations

import io
import os
import re
from collections import OrderedDict

try:
    import yaml
except Exception as _e:  # pragma: no cover
    yaml = None
    _YAML_ERROR = _e
else:
    _YAML_ERROR = None


# 以包位置解析，避免调用方 cwd 不同时静默读不到表（C05 跨目录污染的同类坑）
DEFAULT_RULES = os.path.normpath(
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "references",
        "03_endpoint_rules.yaml",
    )
)
VALID_STATUS = frozenset({"not_covered", "partially_covered"})
REQUIRED_FIELDS = ("id", "label", "status", "reason")

# 出现这些词就说明文本在谈 DDI / 代谢抑制类结论，必须带声明。
# 刻意用「端点名 + 结论词」组合，避免把纯方法学讨论也判违规。
TRIGGER_PATTERNS = (
    r"\bDDI\b",
    r"药物.{0,4}相互作用",
    r"cyp[0-9a-z_]*inhibition",
    r"CYP\s*(?:1A2|2C19|2C9|2D6|3A4).{0,12}抑制",
    r"无.{0,4}(?:相互作用|DDI).{0,6}风险",
    r"未见.{0,4}相互作用",
    r"时间依赖.{0,4}抑制",
    r"\bTDI\b",
    r"CYP\s*诱导",
)
# 声明必须覆盖的「高风险」id：只要文本触发，这两个一个都不能少。
MUST_DECLARE_IDS = ("cyp_induction", "cyp_tdi")

MARKER_TMPL = "<!-- coverage:%s -->"
DECLARATION_TITLE = "## 未覆盖端点声明（强制 · 由 coverage_gate 自动生成）"


def marker(eid):
    return MARKER_TMPL % eid


def load_not_covered(path=DEFAULT_RULES):
    """读取并校验 `not_covered_endpoints`。任何结构异常都抛错，不静默返回空表。

    静默返回空表 == 声明段变空 == 漏洞复发，所以这里必须 fail loud。
    """
    if yaml is None:
        raise RuntimeError("PyYAML 不可用，无法读取端点规则表：%r" % (_YAML_ERROR,))
    path = path or DEFAULT_RULES  # CLI 传 "" 或 None 时回落到随包规则表
    if not os.path.isfile(path):
        raise FileNotFoundError("端点规则表不存在：%s" % path)
    d = yaml.safe_load(io.open(path, encoding="utf-8")) or {}
    items = d.get("not_covered_endpoints")
    if not isinstance(items, list) or not items:
        raise ValueError("%s 缺少非空的 not_covered_endpoints" % path)
    out, seen = [], set()
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            raise ValueError("not_covered_endpoints[%d] 不是映射" % i)
        miss = [k for k in REQUIRED_FIELDS if not str(it.get(k) or "").strip()]
        if miss:
            raise ValueError("not_covered_endpoints[%d] 缺字段 %s" % (i, miss))
        eid = str(it["id"]).strip()
        if eid in seen:
            raise ValueError("not_covered_endpoints 出现重复 id %r" % eid)
        if it["status"] not in VALID_STATUS:
            raise ValueError(
                "端点 %r 的 status=%r 不在 %s"
                % (eid, it["status"], sorted(VALID_STATUS))
            )
        seen.add(eid)
        out.append(
            OrderedDict(
                [
                    ("id", eid),
                    ("label", str(it["label"]).strip()),
                    ("status", it["status"]),
                    ("reason", str(it["reason"]).strip()),
                    (
                        "required_evidence",
                        str(it.get("required_evidence") or "未登记").strip(),
                    ),
                    ("covered_by", str(it.get("covered_by") or "").strip()),
                    ("note", str(it.get("note") or "").strip()),
                ]
            )
        )
    return sorted(out, key=lambda x: x["id"])


def declaration_lines(entries):
    """渲染声明段（list[str]）。不含时间戳，按 id 排序 → 逐字节确定。"""
    lines = [
        DECLARATION_TITLE,
        "",
        "> 本节由 `adt/coverage_gate.py` 读 `03_endpoint_rules.yaml` 自动生成；",
        "> **任何 CYP / DDI / 安全性结论都必须连同本节一起引用**。",
        "> 未覆盖 ≠ 阴性结论；`partially_covered` 仅表示有结构级预警，",
        "> 仍无实验判据，不得据此下 PASS/FAIL。",
        "",
    ]
    for e in entries:
        mark = marker(e["id"])
        status_cn = {
            "not_covered": "未覆盖",
            "partially_covered": "部分覆盖（仅结构预警）",
        }[e["status"]]
        lines.append(
            "- %s **%s**（%s）：**%s**。" % (mark, e["id"], e["label"], status_cn)
        )
        if e["covered_by"]:
            lines.append("  - 现有覆盖：%s" % e["covered_by"])
        lines.append("  - 缺口：%s" % e["reason"])
        lines.append("  - 所需证据：%s" % e["required_evidence"])
        if e["note"]:
            lines.append("  - 约束：%s" % e["note"])
    lines.append("")
    lines.append("> 登记与产物一致性：改 `not_covered_endpoints` 后本段自动变化；")
    lines.append("> 缺任一 `<!-- coverage:<id> -->` 标记即视为声明不完整（可用")
    lines.append("> `python -m adt.claims_audit --coverage-declaration` 校验）。")
    lines.append("")
    return lines


def declaration_text(entries):
    return "\n".join(declaration_lines(entries))


def _triggered(text):
    return any(re.search(p, text, flags=re.IGNORECASE) for p in TRIGGER_PATTERNS)


def verify_declaration(text, entries):
    """声明完整性校验：每个登记端点都必须有对应 marker。

    返回 dict(passed, n_expected, n_missing, missing, applicable)。
    文本未触发 DDI/CYP 类结论时 `applicable=False`（不误伤纯方法学文本）。
    """
    triggered = _triggered(text)
    missing = [e["id"] for e in entries if marker(e["id"]) not in text]
    # 触发了结论词时，MUST_DECLARE_IDS 属于硬要求（即便条目被误删也要报）
    hard = [
        i
        for i in MUST_DECLARE_IDS
        if i not in {e["id"] for e in entries} or marker(i) not in text
    ]
    # 关键语义：文本没在谈 CYP/DDI 时「不适用」= 不违规（applicable=False），
    # 否则纯方法学文档会被整批误报。missing 仍保留供诊断，但不进入 passed。
    all_missing = sorted(set(missing + hard)) if triggered else []
    return OrderedDict(
        [
            ("applicable", bool(triggered)),
            ("triggered_by_ddi_or_cyp_claim", bool(triggered)),
            ("passed", not all_missing),
            ("n_expected", len(entries)),
            ("n_missing", len(all_missing)),
            ("missing", all_missing),
            ("hard_requirements", list(MUST_DECLARE_IDS)),
        ]
    )


def audit_texts(paths, rules=DEFAULT_RULES):
    """对一批文本做声明审计。返回 dict(passed, n_scanned, n_applicable, violations)。"""
    entries = load_not_covered(rules)
    violations, scanned = [], []
    for p in paths:
        if not os.path.isfile(p):
            violations.append(dict(file=p, line=0, why="文件不存在", excerpt=""))
            continue
        text = io.open(p, encoding="utf-8", errors="replace").read()
        scanned.append(p)
        res = verify_declaration(text, entries)
        if not res["passed"]:
            for ln, line in enumerate(text.splitlines(), 1):
                if _triggered(line):
                    violations.append(
                        dict(
                            file=p,
                            line=ln,
                            why="出现 CYP/DDI 类结论但未覆盖端点声明缺失：%s"
                            % ", ".join(res["missing"]),
                            excerpt=line.strip()[:160],
                        )
                    )
                    break
            else:
                violations.append(
                    dict(
                        file=p,
                        line=0,
                        why="声明标记缺失：%s" % ", ".join(res["missing"]),
                        excerpt="",
                    )
                )
    return OrderedDict(
        [
            ("passed", not violations),
            ("n_scanned", len(scanned)),
            (
                "n_applicable",
                sum(
                    1
                    for p in scanned
                    if _triggered(io.open(p, encoding="utf-8", errors="replace").read())
                ),
            ),
            ("n_expected_endpoints", len(entries)),
            ("n_violations", len(violations)),
            ("violations", violations),
        ]
    )


def selftest():
    """正反双向自检（不写盘）：登记表 → 声明 → 校验闭环。"""
    import tempfile

    entries = load_not_covered(DEFAULT_RULES)
    decl = declaration_text(entries)
    cases = []
    cases.append(("完整声明", decl, True))
    cases.append(
        (
            "纯方法学文本（不触发）",
            "本段只描述 Gate 0.5 的结构准入流程，不涉及具体端点结论。",
            "n/a",
        )
    )
    cases.append(
        ("有结论无声明", "CYP3A4 抑制两源一致，未见 DDI 风险，可判定安全。", False)
    )
    cases.append(
        (
            "删掉一个标记",
            decl.replace(marker(entries[0]["id"]), "")
            + "\nCYP3A4 抑制两源一致，无 DDI 风险。",
            False,
        )
    )
    results = []
    for name, text, expect in cases:
        r = verify_declaration(text, entries)
        if expect == "n/a":
            ok = (r["applicable"] is False) and (r["passed"] is True)
        else:
            ok = r["passed"] is expect
        results.append(
            dict(
                case=name,
                applicable=r["applicable"],
                passed=r["passed"],
                expect=expect,
                ok=ok,
                missing=r["missing"],
            )
        )
    return dict(
        passed=all(x["ok"] for x in results),
        n_cases=len(results),
        n_entries=len(entries),
        results=results,
    )
