# -*- coding: utf-8 -*-
"""主张台账审计（G10 门）：**标 ✅ 必须附产物路径 + 至少一个数字**。

## 这条规则怎么来的
第三轮评审 §B 把它列为"四轮评审中第一次把 ✅ 通胀当制度问题修复"：
v4.2 自查发现 R14/R19/R20 三项标了 ✅，但 `out_gate/`、`out_p8/` **从未生成**。
修订后的规则是：只有代码没有产物的条目一律降级 🟡。

问题是——**规则写在文档里就会被绕过**。所以本模块把它做成可执行审计：
解析台账/计分卡的 Markdown 表格，对每个含 ✅ 的行检查
① 是否出现产物路径（`out_*/xxx.json|csv|npz|md|log`、`assets/…`、`replication/…`）；
② 是否出现至少一个**数字**（且该数字不在路径里，避免 `_v4.2.md` 里的 4.2 充数）。
任一不满足即记违规。发布门禁 G10 读它，有违规就 BLOCK。

## 数字的判定（防作弊）
路径里的版本号不是证据。因此先把所有路径 token 从文本中剔除，再找数字。
**只看产物路径 + 数字还不够**：必须二者同时出现在同一行——这正是 R14/R19/R20 缺的。

## 按类型分档（必须，否则会误伤代码项）
台账有"类型"列。代码项的证据是**源码/测试路径**，不是数字产物；
实验项的证据才是 `out_*/xxx.json` + 数字。所以：
| 类型 | 要求 |
|---|---|
| 实验 / 数字 / 基准 | 产物路径（`out_*/…json,csv,npz,log,md` 或 `assets/`）+ 至少一个数字 |
| 代码 / 测试 | 任一源码/测试路径（`.py`） |
| 文档 | 任一 `.md` 路径 |
| 未标注 | 任一路径（兜底，不放过"什么都没有"） |

## 用法
```bash
python -m adt.claims_audit                      # 审计默认台账集合
python -m adt.claims_audit --json out/claims_audit.json
```
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

DEFAULT_TARGETS = [
    "references/REVIEW_v4.1_LEDGER.md",
    "references/TASK_SCORECARD_v4.2.md",
    "references/UNRESOLVED_CLOSEOUT_v4.3.md",
]

# 产物路径 token：任何带已知扩展名的路径
_PATH_PAT = re.compile(
    r"(?:[A-Za-z0-9_.\-]+/)*[A-Za-z0-9_.\-]+\.(?:json|csv|tsv|npz|log|md|yaml|yml|py|png|pdf)"
    r"|(?:out|assets|replication|tests|adt|references)/[A-Za-z0-9_./\-]+"
)
# 实验类要求的"数字产物"：必须是数据产物，不是源码
_DATA_PATH_PAT = re.compile(
    r"(?:(?:[A-Za-z0-9_.\-]+/)*[A-Za-z0-9_.\-]+\.(?:json|csv|tsv|npz|log)"
    r"|(?:out|assets|replication)/[A-Za-z0-9_./\-]+)"
)
_NUM_PAT = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?(?![\w.])")

TYPE_TOKENS = ("实验", "代码", "文档", "测试", "产物", "基准", "数字")


def _row_cells(line):
    if not line.strip().startswith("|"):
        return None
    parts = [c.strip() for c in line.strip().strip("|").split("|")]
    if len(parts) < 2:
        return None
    if all(set(c) <= set("-: ") for c in parts if c):
        return None  # 分隔行
    return parts


def _classify(cells):
    """从"类型"单元格判档；找不到就返回 None（兜底）。"""
    for c in cells:
        clean = re.sub(r"[✅🟡⛔⬜\s]", "", c)
        if clean and any(t in clean for t in TYPE_TOKENS) and len(clean) <= 12:
            if "实验" in clean or "基准" in clean or "数字" in clean:
                return "experiment"
            if "代码" in clean or "测试" in clean:
                return "code"
            if "文档" in clean:
                return "doc"
    return None


def audit_file(path, require_number=True):
    p = os.path.join(ROOT, path) if not os.path.isabs(path) else path
    if not os.path.exists(p):
        return {"file": path, "exists": False, "n_checked": 0, "violations": []}
    viol, checked, by_type = [], 0, {}
    with io.open(p, encoding="utf-8", errors="replace") as fh:
        for i, line in enumerate(fh, 1):
            cells = _row_cells(line)
            if not cells:
                continue
            if not any("✅" in c for c in cells):
                continue
            checked += 1
            text = " ".join(cells)
            kind = _classify(cells) or "unspecified"
            by_type[kind] = by_type.get(kind, 0) + 1
            all_paths = [m.group(0) for m in _PATH_PAT.finditer(text)]
            data_paths = [m.group(0) for m in _DATA_PATH_PAT.finditer(text)]
            # 数字必须在剔掉路径之后仍然存在（防 `_v4.2.md` 的 4.2 充数）
            stripped = text
            for token in set(all_paths):
                stripped = stripped.replace(token, " ")
            nums = _NUM_PAT.findall(stripped)

            reasons = []
            if kind == "experiment":
                if not data_paths:
                    reasons.append("实验类缺数据产物路径（out_*/…json|csv|npz|log）")
                if require_number and not nums:
                    reasons.append("实验类缺数字")
            elif kind == "code":
                if not all_paths:
                    reasons.append("代码类缺源码/测试路径（.py）")
            elif kind == "doc":
                if not [q for q in all_paths if q.endswith(".md")]:
                    reasons.append("文档类缺 .md 路径")
            else:
                if not all_paths and not nums:
                    reasons.append("未标注类型且既无路径也无数字")
            if reasons:
                viol.append(
                    {
                        "line": i,
                        "id": cells[0][:80],
                        "kind": kind,
                        "why": "；".join(reasons),
                        "has_path": bool(all_paths),
                        "has_data_path": bool(data_paths),
                        "has_number": bool(nums),
                        "excerpt": text[:160],
                    }
                )
    return {
        "file": path,
        "exists": True,
        "n_checked": checked,
        "by_type": by_type,
        "violations": viol,
    }


def audit(targets=None, require_number=True):
    targets = targets or DEFAULT_TARGETS
    reports = [audit_file(t, require_number=require_number) for t in targets]
    n_checked = sum(r["n_checked"] for r in reports)
    viol = [dict(v, file=r["file"]) for r in reports for v in r["violations"]]
    by_type = {}
    for r in reports:
        for k, v in (r.get("by_type") or {}).items():
            by_type[k] = by_type.get(k, 0) + v
    return {
        "rule": (
            "标 ✅ 必须附产物路径；其中**实验类**还必须附数据产物 + 至少一个数字"
            "（数字不得来自路径中的版本号）"
        ),
        "origin": "第三轮评审 §B：R14/R19/R20 曾标 ✅ 但产物从未生成（空心 ✅）",
        "targets": targets,
        "n_rows_checked": n_checked,
        "by_type": by_type,
        "n_violations": len(viol),
        "passed": len(viol) == 0,
        "violations": viol,
        "per_file": [
            {k: r[k] for k in ("file", "exists", "n_checked")}
            | {"n_violations": len(r["violations"])}
            for r in reports
        ],
    }


def _resolve_field_path(obj, path):
    """按 `cuts[].auc_vs_chance.auc_ci95` 这类点分路径取结构化值。"""
    cur = [obj]
    for part in [x for x in str(path).split(".") if x]:
        is_list = part.endswith("[]")
        key = part[:-2] if is_list else part
        nxt = []
        for c in cur:
            if not isinstance(c, dict) or key not in c:
                continue
            v = c[key]
            if is_list and isinstance(v, list):
                nxt.extend(v)
            else:
                nxt.append(v)
        cur = nxt
    return cur


def _is_natural_language(v):
    """长字符串视为自然语言句子，不得作为「数字在产物里」的证据（C3 / C16）。"""
    return isinstance(v, str) and (len(v) > 80 or (" " in v and len(v) > 30))


def verify_registry_fields(path="references/CLAIMS_REGISTRY.yaml", entries=None):
    """C3 / C16（2026-11-04）：逐条做**字段级**比对，替代 `token in txt`。

    外审 C V5 的判决：「补 command 字段」若只是字符串 + 非空检查，就是把人工断言
    自动化。因此本函数只采信由 `expect_field_path` 指向的结构化字段值；
    数字只出现在 `sentence_zh` 之类自然语言段落里 → 判 FAIL。
    字段路径未绑定的历史条目如实标 unresolved + non_evidence，不伪造 field_match。
    """
    import yaml

    p = os.path.join(ROOT, path) if not os.path.isabs(path) else path
    if entries is None:
        doc = yaml.safe_load(io.open(p, encoding="utf-8")) or {}
        entries = doc.get("entries") or []
    rows = []
    for e in entries:
        eid = e.get("id") or "<no-id>"
        # 已撤回主张（C01）禁止进入任何证据聚合：既不算 matched 也不算 failed，
        # 否则「撤回」会被统计成一个字段失配，掩盖它本应被移出证据链的事实。
        if (
            e.get("status") == "superseded"
            or e.get("admissible_for_external_use") is False
        ):
            rows.append(
                dict(
                    id=eid,
                    field_match="retracted",
                    evidence_grade="retracted_no_evidence",
                    why="已撤回主张（C01），禁止参与字段级证据聚合",
                )
            )
            continue
        fp = e.get("expect_field_path")
        # 2026-11-18：code 类主张（kind=code，产物是 .py）用 AST 符号绑定，
        # 不套 JSON 字段路径（对 .py 做 json.loads 必失败，属错误判据）。
        # 这是结构化证据的一种，而非字面量命中：expect_code_symbol 必须在
        # 源码里真的有一个同名 def/class/赋值，才算字段级等价物。
        if e.get("kind") == "code" and (e.get("expect_code_symbol") or e.get("expect")):
            syms = [
                str(x) for x in (e.get("expect_code_symbol") or e.get("expect") or [])
            ]
            art = e.get("artifact") or ""
            ap_ = os.path.join(ROOT, art) if not os.path.isabs(art) else art
            if not os.path.isfile(ap_):
                rows.append(
                    dict(id=eid, field_match=False, why="源码产物不存在：%s" % art)
                )
                continue
            try:
                import ast as _ast

                tree = _ast.parse(io.open(ap_, encoding="utf-8").read())
                defined = set()
                for node in _ast.walk(tree):
                    if isinstance(
                        node, (_ast.FunctionDef, _ast.AsyncFunctionDef, _ast.ClassDef)
                    ):
                        defined.add(node.name)
                    elif isinstance(node, _ast.Assign):
                        for tgt in node.targets:
                            if isinstance(tgt, _ast.Name):
                                defined.add(tgt.id)
                missing = [s for s in syms if s not in defined]
                rows.append(
                    dict(
                        id=eid,
                        field_match=not missing,
                        missing=missing,
                        n_field_values=len(syms),
                        evidence_grade=(
                            "structured_code_symbol_evidence"
                            if not missing
                            else "field_mismatch"
                        ),
                        why=(
                            ("AST 符号 %s 未在 %s 定义" % (missing, art))
                            if missing
                            else ""
                        ),
                    )
                )
            except Exception as exc:
                rows.append(
                    dict(id=eid, field_match=False, why="源码 AST 解析失败：%s" % exc)
                )
            continue
        if not fp or e.get("field_path_status") == "unresolved":
            rows.append(
                dict(
                    id=eid,
                    field_match="unresolved",
                    evidence_grade="literal_token_only_non_evidence",
                    why="未绑定 expect_field_path；字面量命中不构成字段级证据",
                )
            )
            continue
        art = e.get("artifact") or ""
        ap_ = os.path.join(ROOT, art) if not os.path.isabs(art) else art
        if not os.path.isfile(ap_):
            rows.append(dict(id=eid, field_match=False, why="产物不存在"))
            continue
        try:
            obj = json.loads(io.open(ap_, encoding="utf-8").read())
        except (ValueError, OSError) as exc:
            rows.append(
                dict(
                    id=eid,
                    field_match=False,
                    why="产物非 JSON，字段级比对不适用：%s" % exc,
                )
            )
            continue
        vals = []
        for sub in str(fp).split(" / "):
            vals.extend(_resolve_field_path(obj, sub.strip()))
        vals = [v for v in vals if not _is_natural_language(v)]
        corpus = json.dumps(vals, ensure_ascii=False, sort_keys=True) if vals else ""
        missing = [str(t) for t in (e.get("expect") or []) if str(t) not in corpus]
        rows.append(
            dict(
                id=eid,
                field_match=not missing,
                missing=missing,
                n_field_values=len(vals),
                evidence_grade=(
                    "structured_field_evidence" if not missing else "field_mismatch"
                ),
                why=("字段级缺失 %s" % missing) if missing else "",
            )
        )
    n_true = sum(r["field_match"] is True for r in rows)
    n_false = sum(r["field_match"] is False for r in rows)
    n_unres = sum(r["field_match"] == "unresolved" for r in rows)
    n_retr = sum(r["field_match"] == "retracted" for r in rows)
    return dict(
        rows=rows,
        n_field_matched=n_true,
        n_field_failed=n_false,
        n_field_unresolved=n_unres,
        n_retracted=n_retr,
        n_entries=len(rows),
        passed=n_false == 0,
        policy=(
            "field_match=unresolved 的历史条目一律标 non_evidence；"
            "只有结构化字段命中才算证据（外审 C V5）"
        ),
    )


def significance_gate(effect, ci=None, p=None, alpha=0.05, min_effect=0.0, context=""):
    """主张的"效应量 + 显著性"双准入（2026-11-19；100 篇精读移植）。

    文献依据：PMID 42734510 / DOI 10.1021/acs.jcim.6c01878 —— 多模态模型
    "numerical improvements ... generally not statistically significant"，
    但 UQ 对齐显著改善。这是"数字好看但不显著"的真实负结果，
    直接命中 claim 五类脆弱性中的 fragile 类。

    判据：
      · effect 绝对值 < min_effect → NO_EFFECT（即使显著也不主张）
      · ci 给出且跨 0 → FRAGILE（不得写"有效"）
      · p 给出且 >= alpha → FRAGILE
      · 三者齐备且通过 → SUPPORTED
      · 缺区间与 p → INDETERMINATE（不凭点估计下结论，与 skill 红线6一致）
    """
    try:
        e = float(effect) if effect is not None else None
    except (TypeError, ValueError):
        return dict(
            verdict="INDETERMINATE",
            reason="效应量不可解析：%r" % (effect,),
            context=context,
            human_confirmation_required=True,
        )
    if e is None:
        return dict(
            verdict="INDETERMINATE",
            reason="效应量缺失",
            context=context,
            human_confirmation_required=True,
        )
    crosses = None
    if ci is not None:
        try:
            lo, hi = float(ci[0]), float(ci[1])
            crosses = not (lo > 0 or hi < 0)
        except (TypeError, ValueError, IndexError):
            crosses = None
    if abs(e) < min_effect:
        v, why = "NO_EFFECT", "效应量 |%.4g| < %.4g（实务阈值），不主张差异" % (
            e,
            min_effect,
        )
    elif crosses is True:
        v, why = "FRAGILE", "95%%CI [%s, %s] 跨 0；点估计 %.4g 不得写成有效" % (
            ci[0],
            ci[1],
            e,
        )
    elif p is not None:
        try:
            v, why = (
                ("SUPPORTED", "效应 %.4g 显著 (p=%.4g)" % (e, float(p)))
                if float(p) < alpha
                else (
                    "FRAGILE",
                    "p=%.4g >= alpha=%.2f，数值改善未达显著" % (float(p), alpha),
                )
            )
        except (TypeError, ValueError):
            v, why = "INDETERMINATE", "p 值不可解析"
    elif crosses is False:
        # CI 有效且不跨 0（无 p 也可据此支持，但仍须人确认）
        v, why = "SUPPORTED", "效应 %.4g，CI 不跨 0；仍须人确认上下文" % e
    else:
        # crosses is None：无区间或区间不可解析，且无 p —— 不得凭点估计放行。
        # 旧实现把此分支当 SUPPORTED，导致形如 ci=['bad','bad'] 的无效区间被
        # 写成"CI 不跨 0"的支持证据。
        v, why = "INDETERMINATE", "无有效区间且无 p：按红线6不得下显著性结论"
    return dict(
        verdict=v,
        reason=why,
        effect=e,
        ci=list(ci) if ci is not None else None,
        p=p,
        alpha=alpha,
        context=context,
        evidence="PMID 42734510 (numerical gains not statistically significant)",
        human_confirmation_required=True,
        remediation=(
            "不得写'有效/提升'，改为'数值方向但统计不确定'"
            if v in ("FRAGILE", "INDETERMINATE")
            else ""
        ),
    )


def classify_fragility(entry, field_result=None):
    """主张脆弱性五分类 + 可执行处置（2026-11-19 移植自 SciForge §4.3）。

    五类：supported / fragile / unsupported / needs_narrowing / needs_experiment。
    **刻意不做自动判定**：SciForge 原论文也写 scientific judgment remains with the researcher。
    本函数只按结构化证据状态给出**候选分类 + 处置建议**，最终分类必须由人确认。
    红旗词（robust / biologically grounded / overgeneralization / single-dataset）来自 SciForge。
    """
    import re as _re

    # 非捕获组：否则 findall 对中文红旗词只返回空串，处置建议丢失实际命中词
    REDFLAGS = _re.compile(
        r"\b(?:robust|biologically grounded|universal|proven)\b|"
        r"稳健|普适|已证实|广泛适用",
        _re.IGNORECASE,
    )
    st = (field_result or {}).get("field_match")
    grade = (field_result or {}).get("evidence_grade", "")
    why = (field_result or {}).get("why", "")
    text = str(entry.get("claim") or "")
    red = REDFLAGS.findall(text)
    if (
        entry.get("status") == "superseded"
        or entry.get("admissible_for_external_use") is False
    ):
        return dict(
            category="retracted",
            remediation="已撤回：不得进入对外材料",
            human_confirmation_required=True,
            redflags=red,
        )
    if st is False or grade == "field_mismatch":
        return dict(
            category="unsupported",
            remediation="字段级失配：改主张或改产物",
            detail=why,
            human_confirmation_required=True,
            redflags=red,
        )
    if st == "unresolved" or grade == "literal_token_only_non_evidence":
        return dict(
            category="needs_narrowing",
            remediation="绑定 expect_field_path / expect_code_symbol 后收窄表述",
            human_confirmation_required=True,
            redflags=red,
        )
    if red:
        return dict(
            category="needs_narrowing",
            remediation="含红旗词 %s：收窄到本产物支持的端点/分布/口径" % red,
            human_confirmation_required=True,
            redflags=red,
        )
    if entry.get("gold_standard_bound") is False or (
        entry.get("endpoint") in ("hERG", "DILI", "BBB_Martins")
        and "PARTIAL" in str(entry.get("estimand_status", ""))
    ):
        return dict(
            category="needs_experiment",
            remediation="estimand 未完全绑定：补实验金标准（见 ENDPOINT_ESTIMAND_CARDS）",
            human_confirmation_required=True,
            redflags=red,
        )
    if st is True:
        return dict(
            category="supported",
            remediation="字段级证据命中；按 G10 引用纪律写产物身份",
            human_confirmation_required=True,
            redflags=red,
        )
    return dict(
        category="fragile",
        remediation="证据依赖窄条件：在材料中显式声明边界",
        human_confirmation_required=True,
        redflags=red,
    )


def fragility_census(path="references/CLAIMS_REGISTRY.yaml"):
    """对全部主张做脆弱性普查（只读、不改注册表）。"""
    import yaml

    p = os.path.join(ROOT, path) if not os.path.isabs(path) else path
    doc = yaml.safe_load(io.open(p, encoding="utf-8")) or {}
    entries = doc.get("entries") or []
    fr = verify_registry_fields(path)["rows"]
    by_id = {r["id"]: r for r in fr}
    out = []
    for e in entries:
        eid = e.get("id") or "<no-id>"
        c = classify_fragility(e, by_id.get(eid))
        out.append(dict(id=eid, **c))
    return out


def check_commands(path="references/CLAIMS_REGISTRY.yaml", entries=None):
    """C3：校验 command 字符串能否解析到真实脚本/模块（UNRESOLVED 不算通过）。"""
    import yaml

    p = os.path.join(ROOT, path) if not os.path.isabs(path) else path
    if entries is None:
        doc = yaml.safe_load(io.open(p, encoding="utf-8")) or {}
        entries = doc.get("entries") or []
    out = []
    for e in entries:
        cmd = str(e.get("command") or "")
        if not cmd or cmd == "UNRESOLVED":
            out.append(dict(id=e.get("id"), status="unresolved", why="无生成命令"))
            continue
        parts = cmd.split()
        if len(parts) >= 3 and parts[1] == "-m":
            out.append(dict(id=e.get("id"), status="module", why="-m %s" % parts[2]))
            continue
        target = parts[1] if len(parts) > 1 else ""
        ok = os.path.isfile(os.path.join(ROOT, target))
        out.append(dict(id=e.get("id"), status="bound" if ok else "broken", why=target))
    return dict(
        rows=out,
        n_bound=sum(x["status"] == "bound" for x in out),
        n_module=sum(x["status"] == "module" for x in out),
        n_unresolved=sum(x["status"] == "unresolved" for x in out),
        n_broken=sum(x["status"] == "broken" for x in out),
    )


def verify_registry(path="references/CLAIMS_REGISTRY.yaml", strict_fields=False):
    """校验主张登记表：每条都要「文件存在 + 每个 expect token 真的出现在文件里」。

    这一层比 Markdown 文本审计强，因为它核对的是**产物内容**而不是**文档措辞**：
    `out_gate/` 那种"路径写了但目录不存在"、以及"数字是四舍五入后凑出来的"两类
    空洞主张都会在这里被抓出来。
    """
    import yaml

    p = os.path.join(ROOT, path) if not os.path.isabs(path) else path
    if not os.path.exists(p):
        return {
            "registry": path,
            "exists": False,
            "passed": False,
            "n_entries": 0,
            "n_failed": 1,
            "failures": [{"id": "<registry>", "artifact": path, "why": "登记表不存在"}],
        }
    doc = yaml.safe_load(io.open(p, encoding="utf-8")) or {}
    entries = doc.get("entries") or []
    failures, checked = [], []
    for e in entries:
        eid = e.get("id") or "<no-id>"
        art = e.get("artifact") or ""
        expect = e.get("expect") or []
        ap_ = os.path.join(ROOT, art) if not os.path.isabs(art) else art
        if not art:
            failures.append({"id": eid, "artifact": "", "why": "未指定 artifact"})
            continue
        if not os.path.exists(ap_):
            failures.append({"id": eid, "artifact": art, "why": "产物文件不存在"})
            continue
        if not expect:
            failures.append(
                {"id": eid, "artifact": art, "why": "expect 为空（无数字可核）"}
            )
            continue
        try:
            txt = io.open(ap_, encoding="utf-8", errors="replace").read()
        except OSError as exc:
            failures.append({"id": eid, "artifact": art, "why": "读取失败：%s" % exc})
            continue
        missing = [t for t in expect if str(t) not in txt]
        kind = e.get("kind", "experiment")
        if kind == "experiment" and not re.search(r"\.(json|csv|tsv|npz|log)$", art):
            failures.append(
                {
                    "id": eid,
                    "artifact": art,
                    "why": "kind=experiment 但产物不是数据文件（红线：只认数据产物）",
                }
            )
            continue
        if missing:
            failures.append(
                {"id": eid, "artifact": art, "why": "产物内找不到字面量 %s" % missing}
            )
            continue
        checked.append({"id": eid, "artifact": art, "tokens": len(expect)})

    # ---- 头号数字（第三轮评审 §D：post-cutoff 0.581 是"全包最重要的单一数字"）----
    #  为什么这条要机器校验：**排序即立场**。把平均情形的好数字放首页、把 0.581 放附录，
    #  完全符合"每条都附了产物"，但读者拿到的印象被颠倒了。故要求登记表里
    #  **恰好一条** tier=headline，且它必须带区间（R1）——没有区间的"最重要结论"不合格。
    headline = [e for e in entries if (e.get("tier") or "") == "headline"]
    if len(headline) != 1:
        failures.append(
            {
                "id": "<headline>",
                "artifact": path,
                "why": "tier=headline 的条目应恰好 1 条，实际 %d 条"
                "（对外材料的第一号数字必须唯一且明确）" % len(headline),
            }
        )
    else:
        h = headline[0]
        if not h.get("interval"):
            failures.append(
                {
                    "id": h.get("id"),
                    "artifact": h.get("artifact", ""),
                    "why": "headline 条目缺 interval（最重要的数字必须带 CI，评审 R1）",
                }
            )
        if h.get("rank") != 1:
            failures.append(
                {
                    "id": h.get("id"),
                    "artifact": h.get("artifact", ""),
                    "why": "headline 条目应标 rank: 1",
                }
            )

    # C3 / C16：字段级证据与命令可解析性作为**附加维度**输出；
    # strict_fields=True 时字段不一致直接计入 failures（供 CI 的严格档使用）。
    fa = verify_registry_fields(p, entries)
    cmds = check_commands(p, entries)
    if strict_fields:
        for r in fa["rows"]:
            if r["field_match"] is False:
                failures.append(
                    {
                        "id": r["id"],
                        "artifact": path,
                        "why": "字段级比对失败：%s" % r.get("why", ""),
                    }
                )

    return {
        "registry": path,
        "exists": True,
        "strict_fields": bool(strict_fields),
        "field_audit": fa,
        "command_audit": cmds,
        "evidence_grade_summary": dict(
            structured=fa["n_field_matched"],
            literal_only_non_evidence=fa["n_field_unresolved"],
            retracted_no_evidence=fa.get("n_retracted", 0),
            field_mismatch=fa["n_field_failed"],
            commands_bound=cmds["n_bound"],
            commands_unresolved=cmds["n_unresolved"],
        ),
        "rule": doc.get("meta", {}).get("rule", ""),
        "headline_rule": doc.get("meta", {}).get("headline_rule", ""),
        "headline": (headline[0].get("id") if len(headline) == 1 else None),
        "n_entries": len(entries),
        "n_verified": len(checked),
        "n_failed": len(failures),
        "passed": len(failures) == 0,
        "failures": failures,
        "verified": checked,
    }


# ---------------------------------------------------------------------------
# F1 / S1a（2026-11-06）：撤回标记贯通检查
#
# 单一真源：references/RETRACTION_NOTE.md 的 R1/R2/R4 + CLAIMS_REGISTRY.yaml 里
# status: superseded 的条目。不新建第二套撤回清单（外部评审 V1：复用既有实现）。
# 只扫「活跃对外文本」；历史评审档案 / CHANGELOG / 撤回笔记本身不追溯改写，
# 作为 audit_only 保留 —— 这与 C' 的「留痕」要求一致，不是把它们洗白。
# ---------------------------------------------------------------------------

_RETRACTION_PATTERNS = {
    "R1": re.compile(r"全部低于同批\s*always-positive|域外没有排序能力"),
    "R2": re.compile(r"域外处处不可用|保守的正确"),
    "R4": re.compile(
        r"c\*\s*(?:≤|≈|=)?\s*0\.21|条件性优势|S4 才赢"
        r"|无差异点存在且可估计|无差异点\s*c\*"
    ),
}
_RETRACTION_MARKERS = (
    "撤回",
    "RETRACTED",
    "superseded",
    "已撤回",
    "作废",
    "~~",
    "会计恒等式",
    "保留以供审计",
    "仅审计保留",
)
_ACTIVE_TEXTS = (
    "SKILL.md",
    "references/NEGATIVE_RESULT_DEFAULTS.yaml",
    "references/POSITIONING.md",
)


def verify_no_retracted_claims(root="."):
    """扫描活跃对外文本，找出「已撤回结论被无标记地继续使用」的行。

    判定：命中禁用表述，且该行及其前 2 行内没有任何撤回标记 → 违规。
    上下文窗口是必要的：撤回声明常写在段首、旧句在续行（SKILL.md 的既有写法）。
    返回 dict(passed, scanned, violations, policy, excluded)；空列表即通过。
    """
    import yaml

    r = os.path.abspath(root)
    scanned, violations = [], []

    for rel in _ACTIVE_TEXTS:
        p = os.path.join(r, rel)
        if not os.path.isfile(p):
            continue
        lines = io.open(p, encoding="utf-8", errors="replace").read().splitlines()
        scanned.append(rel)
        for i, line in enumerate(lines):
            for rid, pat in _RETRACTION_PATTERNS.items():
                if not pat.search(line):
                    continue
                ctx = "\n".join(lines[max(0, i - 2) : i + 1])
                if any(m in ctx for m in _RETRACTION_MARKERS):
                    continue
                violations.append(
                    dict(
                        file=rel,
                        line=i + 1,
                        rule=rid,
                        id=None,
                        excerpt=line.strip()[:160],
                    )
                )

    reg = os.path.join(r, "references", "CLAIMS_REGISTRY.yaml")
    if os.path.isfile(reg):
        doc = yaml.safe_load(io.open(reg, encoding="utf-8")) or {}
        scanned.append("references/CLAIMS_REGISTRY.yaml:active_claims")
        for e in doc.get("entries") or []:
            if (
                e.get("status") == "superseded"
                or e.get("admissible_for_external_use") is False
            ):
                continue  # 已登记撤回的条目整体排除，其 claim 文本是审计记录
            claim = str(e.get("claim") or "")
            for rid, pat in _RETRACTION_PATTERNS.items():
                if pat.search(claim):
                    violations.append(
                        dict(
                            file="references/CLAIMS_REGISTRY.yaml",
                            line=None,
                            rule=rid,
                            id=e.get("id"),
                            excerpt=claim[:160],
                        )
                    )

    return dict(
        passed=not violations,
        n_scanned=len(scanned),
        scanned=scanned,
        n_violations=len(violations),
        violations=violations,
        policy=(
            "命中 R1/R2/R4 禁用表述且无撤回标记即违规；"
            "撤回清单不另建，复用 RETRACTION_NOTE + CLAIMS_REGISTRY.status"
        ),
        excluded=(
            "历史评审档案 / CHANGELOG / RETRACTION_NOTE / 历史产物不追溯改写，"
            "audit_only；POSITIONING 的条件命题骨架不在短语覆盖内，仍需人工复核"
        ),
    )


# ---- 2026-11-11：结构干扰红旗的措辞封顶断言（F2）----------------------------
# 与 verify_no_retracted_claims 同一范式：把「文档里写了规则」变成「可执行审计」。
# 判定对象是**强 PAINS 红旗化合物**（flag=suspect_interference）；weak_only 不在范围内
# （GRAS 不饱和酸子类本就不折减结论，见 adt/interference.py docstring）。
_INTERFERENCE_STRONG_CLAIMS = re.compile(
    r"未见毒性|已排除风险|未见风险信号|确认无干扰|无毒|可判定安全|"
    r"排除[^，。；]{0,8}风险|证明[^，。；]{0,6}安全"
)
_INTERFERENCE_CONTEXT_MARKERS = (
    "interference",
    "PAINS",
    "需实验确认",
    "去污剂",
    "正交",
    "suspect_interference",
    "降级",
    "红旗",
    "撤回",
    "保留意见",
)


def verify_interference_phrasing(flags_csv, texts=None, root="."):
    """强结构干扰红旗化合物的对外文本，不得出现无保留的「未见毒性/已排除风险」结论。

    命中条件（三者同时）：
      ① 该化合物在 flags_csv 里 flag=suspect_interference；
      ② 同一行出现该 compound_id（词边界匹配，长度>=3 以防短 id 误伤）；
      ③ 同一行出现强结论词，且该行及前 2 行没有任何干扰/保留标记。

    空 flags 或缺文件一律返回 passed=False（**不静默跳过**）——审计器假装通过
    比不审计更危险。没有强红旗分子时返回 passed=True 但 applicable=False，
    明确标注「断言本轮不适用」，不得冒充已验证。
    """
    import csv

    r = os.path.abspath(root)
    fp = flags_csv if os.path.isabs(flags_csv) else os.path.join(r, flags_csv)
    result = dict(
        passed=False,
        applicable=False,
        flags=flags_csv,
        n_flagged_compounds=0,
        scanned=[],
        n_violations=0,
        violations=[],
        policy=(
            "强 PAINS 红旗化合物的文本出现无保留强结论即违规；"
            "weak_only 不适用；上下文带干扰/保留标记可豁免"
        ),
        excluded=("历史评审档案不追溯改写；不含 compound_id 的泛泛表述不在判定范围"),
    )
    if not flags_csv or not os.path.isfile(fp):
        result["error"] = "flags 文件不存在或未指定：%r" % flags_csv
        return result

    flagged = set()
    with io.open(fp, encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            cid = (row.get("compound_id") or "").strip()
            if row.get("flag") == "suspect_interference" and cid:
                flagged.add(cid)
    result["n_flagged_compounds"] = len(flagged)
    result["passed"] = True
    if not flagged:
        result["note"] = "flags 里没有 suspect_interference 分子，断言本轮不适用"
        return result
    result["applicable"] = True

    pats = {
        cid: re.compile(r"(?<![A-Za-z0-9_-])%s(?![A-Za-z0-9_-])" % re.escape(cid), re.I)
        for cid in flagged
        if len(cid) >= 3
    }
    result["n_flagged_compounds"] = len(flagged)
    for rel in (texts if texts is not None else _ACTIVE_TEXTS):
        p = rel if os.path.isabs(rel) else os.path.join(r, rel)
        if not os.path.isfile(p):
            continue
        result["scanned"].append(rel)
        lines = io.open(p, encoding="utf-8", errors="replace").read().splitlines()
        for i, line in enumerate(lines):
            if not _INTERFERENCE_STRONG_CLAIMS.search(line):
                continue
            ctx = "\n".join(lines[max(0, i - 2) : i + 1])
            if any(m in ctx for m in _INTERFERENCE_CONTEXT_MARKERS):
                continue
            for cid, pat in pats.items():
                if pat.search(line):
                    result["violations"].append(
                        dict(
                            file=rel,
                            line=i + 1,
                            compound_id=cid,
                            excerpt=line.strip()[:160],
                        )
                    )
                    break
    result["n_violations"] = len(result["violations"])
    result["passed"] = not result["violations"]
    return result


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--targets", nargs="*", default=None)
    ap.add_argument(
        "--registry",
        default=None,
        help="校验主张登记表（推荐；G10 门用的就是这个模式）",
    )
    ap.add_argument(
        "--no-require-number",
        action="store_true",
        help="只查产物路径（宽松模式，仅供排查，不用于门禁）",
    )
    ap.add_argument("--json", dest="json_out", default=None)
    ap.add_argument(
        "--strict-fields",
        action="store_true",
        dest="strict_fields",
        help="C3：字段级比对失败也计入失败（CI 严格档）",
    )
    ap.add_argument(
        "--retractions",
        action="store_true",
        help="F1/S1a：检查已撤回结论是否仍在活跃对外文本中被无标记引用",
    )
    ap.add_argument(
        "--interference-phrasing",
        action="store_true",
        dest="interference_phrasing",
        help="F2：强结构干扰红旗化合物不得被写成无保留的「未见毒性/已排除风险」",
    )
    ap.add_argument(
        "--coverage-declaration",
        action="store_true",
        dest="coverage_declaration",
        help="C82 闭环：出现 CYP/DDI 类结论的文本必须带完整未覆盖端点声明",
    )
    ap.add_argument(
        "--rules", default="", help="端点规则表（缺省用随包 03_endpoint_rules.yaml）"
    )
    ap.add_argument(
        "--flags", default="", help="adt.cli interference 产出的 interference_flags.csv"
    )
    ap.add_argument(
        "--texts",
        nargs="*",
        default=None,
        help="待审文本（缺省扫活跃对外文本集合 + out*/conclusions.md 产物）",
    )
    a = ap.parse_args(argv)

    if a.coverage_declaration:
        import glob as _glob
        from . import coverage_gate as CG

        if a.texts is not None:
            paths = list(a.texts)
        else:
            paths = list(_ACTIVE_TEXTS) + sorted(_glob.glob("out*/conclusions.md"))
        res = CG.audit_texts(paths, a.rules or None)
        print(
            "[claims] 未覆盖端点声明：扫描 %d 份文本，适用 %d 份，"
            "登记端点 %d 条，违规 %d 条"
            % (
                res["n_scanned"],
                res["n_applicable"],
                res["n_expected_endpoints"],
                res["n_violations"],
            )
        )
        for v in res["violations"][:40]:
            print("  ✗ %s:%d [%s] %s" % (v["file"], v["line"], v["why"], v["excerpt"]))
        if a.json_out:
            os.makedirs(os.path.dirname(os.path.abspath(a.json_out)), exist_ok=True)
            with io.open(a.json_out, "w", encoding="utf-8") as f:
                f.write(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res["passed"] else 1

    if a.interference_phrasing:
        res = verify_interference_phrasing(a.flags, texts=a.texts)
        print(
            "[claims] 干扰措辞封顶：红旗分子 %d 个，扫描 %d 份文本，违规 %d 条，"
            "适用=%s"
            % (
                res["n_flagged_compounds"],
                len(res["scanned"]),
                res["n_violations"],
                res["applicable"],
            )
        )
        if res.get("error"):
            print("  ✗ %s" % res["error"])
        for v in res["violations"][:40]:
            print(
                "  ✗ %s:%d [%s] %s"
                % (v["file"], v["line"], v["compound_id"], v["excerpt"])
            )
        if a.json_out:
            os.makedirs(os.path.dirname(os.path.abspath(a.json_out)), exist_ok=True)
            with io.open(a.json_out, "w", encoding="utf-8") as f:
                f.write(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res["passed"] else 1

    if a.retractions:
        res = verify_no_retracted_claims()
        print(
            "[claims] 撤回标记贯通：扫描 %d 个活跃文本，违规 %d 条"
            % (res["n_scanned"], res["n_violations"])
        )
        for v in res["violations"][:40]:
            print("  ✗ %s:%s [%s] %s" % (v["file"], v["line"], v["rule"], v["excerpt"]))
        if a.json_out:
            os.makedirs(os.path.dirname(os.path.abspath(a.json_out)), exist_ok=True)
            with io.open(a.json_out, "w", encoding="utf-8") as f:
                f.write(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res["passed"] else 1

    if a.registry:
        res = verify_registry(a.registry, strict_fields=a.strict_fields)
        g = res.get("evidence_grade_summary") or {}
        print(
            "[claims] 字段级证据：structured=%s / literal_only_non_evidence=%s / "
            "field_mismatch=%s；command 已绑定=%s / unresolved=%s"
            % (
                g.get("structured"),
                g.get("literal_only_non_evidence"),
                g.get("field_mismatch"),
                g.get("commands_bound"),
                g.get("commands_unresolved"),
            )
        )
        if a.json_out:
            os.makedirs(os.path.dirname(os.path.abspath(a.json_out)), exist_ok=True)
            with io.open(a.json_out, "w", encoding="utf-8") as f:
                f.write(json.dumps(res, ensure_ascii=False, indent=2))
        print(
            "[claims] registry=%s  条目 %d，失败 %d"
            % (res["registry"], res["n_entries"], res["n_failed"])
        )
        for e in res["failures"]:
            print("  ✗ %-32s %s — %s" % (e["id"], e["artifact"], e["why"]))
        return 0 if res["passed"] else 1

    res = audit(a.targets, require_number=not a.no_require_number)
    if a.json_out:
        os.makedirs(os.path.dirname(os.path.abspath(a.json_out)), exist_ok=True)
        with io.open(a.json_out, "w", encoding="utf-8") as f:
            f.write(json.dumps(res, ensure_ascii=False, indent=2))
    print(
        "[claims] 检查 %d 行 ✅，违规 %d 条"
        % (res["n_rows_checked"], res["n_violations"])
    )
    for v in res["violations"][:40]:
        print("  %s:%d  [%s] %s" % (v["file"], v["line"], v["why"], v["excerpt"]))
    if res["n_violations"] > 40:
        print("  … 其余 %d 条见 JSON" % (res["n_violations"] - 40))
    return 0 if res["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
