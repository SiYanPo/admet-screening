# -*- coding: utf-8 -*-
"""轻量变异测试引擎（不依赖 mutmut，也可与 mutmut 并行使用）。

目的：验证 112+ 项断言是否真的能抓住实现里的错误，而不是"伪阳性"。
做法：在**临时副本**里往目标函数注入单个语法合法的变异（比较符反转、
布尔翻转、常量漂移、加减互换），用完整 pytest 跑一遍：
  - 测试失败 / 超时 → killed（断言有效）
  - 测试全绿 → survived（断言无效，需补测）
绝不修改工作区源文件；每个变异体独立目录，避免相互污染。

生产 CI 可把本引擎换成 mutmut/ cosmic-ray，但门禁语义保持一致：
  变异分数不得退化 + 致命变异不得存活 + 断言改动必须带票据。
"""

from __future__ import annotations

import ast
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import tokenize
from collections import defaultdict
from datetime import datetime, timezone

# 只变异"科学判定核心"，不变异渲染模板常量等低价值位置
TARGETS = {
    "textgen.py": [
        "project_slots",
        "render_verdict",
        "semantic_interceptor",
        "safe_render",
    ],
    "budget.py": ["finalize_manifest", "enforce_publish_gate", "guarded_call"],
    "baseline_governance.py": ["decay_weight", "admit_baseline_entry", "washout"],
    "consistency_check.py": ["check_consistency", "guard_fast_output"],
    "shadow_mode.py": ["stats", "can_promote", "promote"],
    "tolerance_assert.py": [
        "assert_no_value_when_undetermined",
        "assert_out_of_domain_no_number",
        "assert_close",
        "assert_direction",
    ],
    "sparsity.py": ["endpoint_support", "egger_test", "publication_bias_probe"],
    "zk_audit.py": ["commitment", "verify_merkle", "verify_evidence", "trace_uplift"],
    "chained_exemption.py": [
        "issue",
        "verify_chain",
        "validate",
        "apply_exemption",
        "publish_gate",
    ],
    "compute_directive.py": [
        "directive_for",
        "matrix_size_gate",
        "request_interactive_override",
        "verify_interactive_grant",
    ],
    "regulatory_seal.py": [
        "source_tree_hash",
        "environment_fingerprint",
        "record_digest",
        "seal",
        "verify",
        "generate_deviation_report",
    ],
    "stratified_monitor.py": [
        "methyl_probe_smiles",
        "stratified_drift",
        "counterfactual_check",
        "add",
        "get",
        "run",
    ],
    "incremental_recert.py": ["reevaluate", "_classify", "run", "checkpoint"],
    "trust_inheritance.py": [
        "record_origin",
        "derive",
        "verify_chain",
        "effective_trust",
    ],
    "uncertainty_quantification.py": [
        "from_samples",
        "from_ensemble",
        "surrogate_uq",
        "resolve_uq",
        "uq_gate",
    ],
    "dependency_guard.py": [
        "assertion_gate",
        "verify_batch",
        "check_assertion_binding",
        "automated_golden_diff",
    ],
    "active_review.py": [
        "select",
        "_cluster_weight",
        "wilson_interval",
        "update",
        "fraction",
    ],
    "split_audit.py": [
        "mcc",
        "split_cluster",
        "evaluate_splits",
        "split_sensitivity_gate",
    ],
    "ood_monotonicity.py": ["build_ood_curve", "ood_monotonicity_gate"],
    "uncertainty_quantification.py": [
        "from_samples",
        "surrogate_uq",
        "coverage_by_shift",
        "coverage_by_class",
        "representation_stability",
        "uq_gate",
    ],
    "stratified_monitor.py": [
        "methyl_probe_smiles",
        "stratified_drift",
        "counterfactual_check",
        "update",
        "scan",
        "coverage",
        "operator_assertions",
    ],
    "regulatory_seal.py": [
        "source_tree_hash",
        "record_digest",
        "seal",
        "verify",
        "append",
        "trust_domain_gate",
    ],
}

# 顺序敏感：先长操作符，后短操作符
OPS = [
    ("ge_to_lt", re.compile(r"(?<![=!<>])>=(?!=)"), "<"),
    ("le_to_gt", re.compile(r"(?<![=!<>])<=(?!=)"), ">"),
    ("eq_to_ne", re.compile(r"(?<![!=<>])=="), "!="),
    ("ne_to_eq", re.compile(r"(?<![!=<>])!="), "=="),
    ("gt_to_ge", re.compile(r"(?<![=!<>])>(?!=)"), ">="),
    ("lt_to_le", re.compile(r"(?<![=!<>])<(?!=)"), "<="),
    ("and_to_or", re.compile(r"\band\b"), "or"),
    ("or_to_and", re.compile(r"\bor\b"), "and"),
    ("true_to_false", re.compile(r"\bTrue\b"), "False"),
    ("false_to_true", re.compile(r"\bFalse\b"), "True"),
    ("not_in_to_in", re.compile(r"\bnot\s+in\b"), "in"),
]
NUM_RE = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)(?![\w.])")


def _function_lines(src, names):
    tree = ast.parse(src)
    out = {}
    # 必须 walk 到 class 内部：ShadowChannel.stats/can_promote/promote 都是方法
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in names
            and node.name not in out
        ):
            end = getattr(node, "end_lineno", node.lineno)
            out[node.name] = (node.lineno, end)
    return out


def _string_spans(src):
    """记录每行中 STRING/COMMENT 字符区间：绝不变异文档字符串或注释里的"代码"。"""
    spans = defaultdict(list)
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type not in (tokenize.STRING, tokenize.COMMENT):
                continue
            for ln in range(tok.start[0], tok.end[0] + 1):
                if ln == tok.start[0] == tok.end[0]:
                    spans[ln].append((tok.start[1], tok.end[1]))
                elif ln == tok.start[0]:
                    spans[ln].append((tok.start[1], 10**6))
                elif ln == tok.end[0]:
                    spans[ln].append((0, tok.end[1]))
                else:
                    spans[ln].append((0, 10**6))
    except (tokenize.TokenError, IndentationError):
        pass
    return spans


def _overlaps(a, b, spans):
    return any(not (a >= hi or b <= lo) for lo, hi in spans)


def _mutate_line(line, op_name, pattern, repl, excluded=None):
    excluded = excluded or []
    if pattern is None:
        it = NUM_RE.finditer(line)
        for m in it:
            if _overlaps(m.start(1), m.end(1), excluded):
                continue
            raw = m.group(1)
            try:
                val = float(raw)
            except ValueError:
                continue
            newval = val + 1 if val.is_integer() else round(val * 10, 6)
            newraw = str(int(newval)) if float(newval).is_integer() else str(newval)
            return line[: m.start(1)] + newraw + line[m.end(1) :], "num_%s_to_%s" % (
                raw,
                newraw,
            )
        return None
    for m in pattern.finditer(line):
        if _overlaps(m.start(), m.end(), excluded):
            continue
        return line[: m.start()] + repl + line[m.end() :], op_name
    return None


# 等价变异（改变显示精度/未使用的默认值）：不改变任何可观测行为，
# 不可能被测试杀死。必须显式登记原因，不能靠"分数不够就调低门禁"掩盖。
EQUIVALENT_EXCLUSIONS = {
    "budget.py:118:num_3_to_4": "仅改变 manifest 里耗时的显示小数位",
    "baseline_governance.py:54:num_1.0_to_2": "默认可靠性不参与任何分支比较",
    "sparsity.py:34:num_3_to_4": "仅改变报告展示的小数位",
    "compute_directive.py:34:or_to_and": "complexity 缺失时 small 与 None 在所有分支等价",
    "stratified_monitor.py:81:num_120_to_121": "仅改变错误详情字符串截断长度",
    "incremental_recert.py:53:num_120_to_121": "仅改变错误详情字符串截断长度",
    "trust_inheritance.py:83:num_120_to_121": "仅改变操作名字符串截断长度",
    "regulatory_seal.py:35:ne_to_eq": "__pycache__ 目录内无 .py，是否排除对源哈希无影响",
    "regulatory_seal.py:136:ne_to_eq": "__pycache__ 目录内无 .py，是否排除对源哈希无影响",
}


def generate_mutants(pkg_dir, *, per_file=8, only=None):
    """生成变异体描述列表（不落盘修改源文件）。"""
    mutants = []
    for fname, funcs in TARGETS.items():
        if only and fname not in only:
            continue
        path = os.path.join(pkg_dir, fname)
        if not os.path.exists(path):
            continue
        src = open(path, "r", encoding="utf-8").read()
        lines = src.splitlines(keepends=True)
        excluded = _string_spans(src)
        ranges = _function_lines(src, funcs)
        candidates = []
        for fn in funcs:
            if fn not in ranges:
                continue
            lo, hi = ranges[fn]
            for idx in range(lo - 1, hi):
                raw = lines[idx]
                stripped = raw.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                # 跳过纯 docstring / def 行 / import 行
                if stripped.startswith(("def ", "import ", "from ", '"""', "'''")):
                    continue
                candidates.append((idx, fn))
        if not candidates:
            continue
        # 顺序扫描，直到凑够 per_file；避免等距取样漏掉可变异行
        picked = candidates
        used = set()
        for idx, fn in picked:
            if len([x for x in mutants if x["file"] == fname]) >= per_file:
                break
            applied = False
            for op_name, pat, repl in OPS:
                res = _mutate_line(
                    lines[idx], op_name, pat, repl, excluded.get(idx + 1, [])
                )
                if res is None:
                    continue
                new_line, op_label = res
                mutated = list(lines)
                mutated[idx] = new_line
                new_src = "".join(mutated)
                try:
                    ast.parse(new_src)
                except SyntaxError:
                    continue
                mid = hashlib.sha256(
                    ("%s|%d|%s" % (fname, idx + 1, op_label)).encode("utf-8")
                ).hexdigest()[:12]
                if mid in used:
                    continue
                used.add(mid)
                mutants.append(
                    {
                        "mid": mid,
                        "file": fname,
                        "line": idx + 1,
                        "function": fn,
                        "op": op_label,
                        "original": lines[idx].strip()[:120],
                        "mutated": new_line.strip()[:120],
                        "_new_src": new_src,
                    }
                )
                applied = True
                break
            if applied:
                continue
            # 全部操作符无效 → 试常量漂移
            res = _mutate_line(lines[idx], "num", None, None, excluded.get(idx + 1, []))
            if res:
                new_line, op_label = res
                mutated = list(lines)
                mutated[idx] = new_line
                new_src = "".join(mutated)
                try:
                    ast.parse(new_src)
                except SyntaxError:
                    continue
                mid = hashlib.sha256(
                    ("%s|%d|%s" % (fname, idx + 1, op_label)).encode("utf-8")
                ).hexdigest()[:12]
                mutants.append(
                    {
                        "mid": mid,
                        "file": fname,
                        "line": idx + 1,
                        "function": fn,
                        "op": op_label,
                        "original": lines[idx].strip()[:120],
                        "mutated": new_line.strip()[:120],
                        "_new_src": new_src,
                    }
                )
    return [
        m
        for m in mutants
        if ("%s:%d:%s" % (m["file"], m["line"], m["op"])) not in EQUIVALENT_EXCLUSIONS
    ]


def run_mutation_tests(
    project_root,
    *,
    per_file=8,
    timeout_s=120,
    only=None,
    pytest_args=None,
    out_path=None,
):
    """在临时副本上跑全部变异体，产出 JSON 报告。"""
    pkg_dir = os.path.join(project_root, "adt_proto")
    mutants = generate_mutants(pkg_dir, per_file=per_file, only=only)
    # 固定快速核心子集：覆盖 112 项既有断言 + 生产级快测；
    # 显式排除 slow 标记的并发/多进程压测，避免每个变异体重复跑数十秒。
    pytest_args = pytest_args or [
        "tests/test_adversarial.py",
        "tests/test_landing.py",
        "tests/test_production.py",
        "tests/test_mutation_killers.py",
        "tests/test_commercial.py",
        "tests/test_regulatory.py",
        "tests/test_trust_boundary.py",
        "-q",
        "-m",
        "not slow",
        "--disable-warnings",
    ]
    started_all = time.monotonic()
    results = []
    for m in mutants:
        tmp = tempfile.mkdtemp(prefix="admet_mut_")
        try:
            shutil.copytree(pkg_dir, os.path.join(tmp, "adt_proto"))
            shutil.copytree(
                os.path.join(project_root, "tests"), os.path.join(tmp, "tests")
            )
            with open(
                os.path.join(tmp, "adt_proto", m["file"]), "w", encoding="utf-8"
            ) as fh:
                fh.write(m["_new_src"])
            env = os.environ.copy()
            env["PYTHONPATH"] = tmp + os.pathsep + env.get("PYTHONPATH", "")
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            t0 = time.monotonic()
            try:
                proc = subprocess.run(
                    [sys.executable, "-m", "pytest"] + pytest_args,
                    cwd=tmp,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=timeout_s,
                )
                status = "killed" if proc.returncode != 0 else "survived"
                tail = (proc.stdout + proc.stderr)[-400:]
            except subprocess.TimeoutExpired:
                status = "timeout"  # 超时按 killed 计（挂死也是缺陷被暴露）
                tail = "TIMEOUT after %ss" % timeout_s
            elapsed = round(time.monotonic() - t0, 3)
            rec = {k: v for k, v in m.items() if k != "_new_src"}
            rec.update({"status": status, "seconds": elapsed, "tail": tail})
            results.append(rec)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    n_valid = len(results)
    n_killed = sum(1 for r in results if r["status"] in ("killed", "timeout"))
    n_surv = sum(1 for r in results if r["status"] == "survived")
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "per_file": per_file,
        "n_total": n_valid,
        "n_killed": n_killed,
        "n_survived": n_surv,
        "n_timeout": sum(1 for r in results if r["status"] == "timeout"),
        "score": round(n_killed / n_valid, 4) if n_valid else 0.0,
        "seconds": round(time.monotonic() - started_all, 2),
        "mutants": results,
    }
    # 同行评审 §4 分歧 5：变异分数 1.0 只证明"断言对代码变异敏感"，
    # 不证明分布偏移下有意义。禁止把它单独当质量证据——必须与 split_audit /
    # ood_monotonicity 的元断言并列读。这里把该边界固化进产物本身。
    report["interpretation_guard"] = {
        "score_meaning": "assertion_sensitivity_only",
        "not_evidence_of": "distribution_shift_robustness",
        "must_pair_with": [
            "split_audit.split_sensitivity_gate",
            "ood_monotonicity.ood_monotonicity_gate",
        ],
        "statement": (
            "变异分数=%.4f 仅表明测试对代码变异敏感；不代表模型在 scaffold/cluster/time "
            "分割或分布偏移下的稳健性。禁止单独引用为质量证据，须与 split_audit/"
            "ood_monotonicity 元断言并列。" % report["score"]
        ),
    }
    if out_path:
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)
    return report


if __name__ == "__main__":
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    rep = run_mutation_tests(
        root,
        per_file=6,
        out_path=os.path.join(root, "evidence", "mutation_report.json"),
    )
    print(
        json.dumps(
            {k: v for k, v in rep.items() if k != "mutants"},
            ensure_ascii=False,
            indent=2,
        )
    )
    for m in rep["mutants"]:
        if m["status"] == "survived":
            print("SURVIVED %s:%s %s" % (m["file"], m["line"], m["op"]))
