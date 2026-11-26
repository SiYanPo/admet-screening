# -*- coding: utf-8 -*-
"""红线**接线**注册表（评审 C1 修复）——红线不只要"能断言"，还要"在生产路径上开火"。

## 为什么需要这个模块（评审原话）

> "SKILL.md 自己的判定标准是：**能不能用一条命令绕过**。能绕过就不是红线。"
> 实测 grep 全仓：`guards.py` 里 9 个守卫函数中，多数**在生产代码中零调用点**；
> 而 `guards.red_lines_status()` 返回的是硬编码 `ok=True` 字典——它不验证任何接线，
> 只复述自身。发布门禁 G8 读的正是这个字典。**G8 检查的是"红线声称已落地"，
> 而非"红线已落地"。**

本模块把"红线状态"从**自声明**改为**探测**：

1. `REGISTRY` 为每条红线登记其在生产代码中的调用点 `(文件, 函数, 代码记号)`；
2. `probe()` 用 AST 解析该文件、定位该函数、检查记号是否真的出现在函数体内
   ——**静态探测只是必要条件，不是充分条件**（评审 R-A：装饰器/动态 import 会漏报，
   静态分析最多做告警，不能做 G8 的唯一判据）；
3. `status()` 同时检查该红线是否配有 `REDLINE-<id>` 集成测试记号；
4. G8 改为：**静态调用点存在 ∧ 集成测试存在**，二者缺一即 blocker；
   并把 `hardness`（hard / soft / conditional）如实暴露给材料层，
   禁止再把"soft warn"写成"已阻断"。

## hardness 语义（材料层必须照抄，不得合并）

| hardness | 含义 | 允许的对外表述 |
|---|---|---|
| `hard` | 违反即抛异常/非零退出 | "红线已阻断" |
| `conditional` | 仅在特定模式（如 `--publish`）下阻断 | "发布模式下阻断，探索模式放行" |
| `soft` | 默认告警并落盘，不阻断 | "默认告警 + 可 `--strict-*` 升级为阻断" |

## 评审自查修正（2026-11-03，本轮）

初版评审意见称"9 条中 7 条无生产调用点"。逐条复核后**修正为**：
- R1/R2/R4/R5 **已实质接线**（只是不经 `guards.*` 包装，而在 cmd_normalize /
  cmd_reliab / main 的 profile 检查里）；
- R3/R6/R7/R8/R9 确为**零生产调用点**；
- R6 部分接线（`phrasing.allowed_statement` 模板已进报告，但 `interval_line`
  的文本扫描未进）。
本模块的 `probe()` 就是为杜绝这类"整体判断靠印象"而写：状态由探测得出，不由人记。
"""

from __future__ import annotations

import ast
import io
import json
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

# ---------------------------------------------------------------------------
# 注册表：每条红线的生产调用点
#   sites: [(相对仓库根的文件, 函数名, 代码记号)]——记号为该函数体内必须出现的字符串
#   test : 承载集成测试的文件（相对路径）
#   marker: 集成测试里必须出现的记号（用于确认是"真集成测试"而非同文件顺手断言）
# ---------------------------------------------------------------------------
REGISTRY = [
    dict(
        id="1_input_anchor",
        name="禁止名称→SMILES 直连；InChIKey 锚定；立体缺失即 fail",
        guard="guards.admission_line",
        hardness="soft",
        sites=[
            ("adt/cli.py", "cmd_normalize", "PB.validate_entry("),
            ("adt/cli.py", "cmd_normalize", "strict_input"),
        ],
        test="tests/test_redline_wiring.py",
        marker="REDLINE-1",
        note="实质接线在 cmd_normalize 逐分子 validate_entry + input_gate.csv 落盘；"
        "默认告警，--strict-input 升级为 exit 3",
    ),
    dict(
        id="2_sample_size",
        name="n<30 打横幅；n<10 只出定性结论",
        guard="guards.sample_size_guard",
        hardness="hard",
        sites=[("adt/cli.py", "cmd_reliab", "sample_size_guard")],
        test="tests/test_redline_wiring.py",
        marker="REDLINE-2",
        note="cmd_reliab 在裁决后按 n 打横幅/降级",
    ),
    dict(
        id="3_replay_only",
        name="论文/决策数字必须来自快照重放模式",
        guard="guards.require_replay",
        hardness="conditional",
        sites=[("adt/cli.py", "cmd_report", "require_replay")],
        test="tests/test_redline_wiring.py",
        marker="REDLINE-3",
        note="report --publish 触发；探索模式（无 --publish）不阻断但会在表头留痕",
    ),
    dict(
        id="4_low_validity",
        name="DILI/Ames 需 --i-accept-low-validity 且留痕",
        guard="guards.low_validity_line",
        hardness="hard",
        sites=[("adt/cli.py", "cmd_reliab", "i_accept_low_validity")],
        test="tests/test_redline_wiring.py",
        marker="REDLINE-4",
        note="实质接线在 endpoints 端点三级政策：not_recommended 默认降 UNDETERMINED",
    ),
    dict(
        id="5_commercial_profile",
        name="商用必须 --profile commercial 且调用日志归档",
        guard="compliance.enforce",
        hardness="hard",
        sites=[("adt/cli.py", "main", "CMP.resolve_profile")],
        test="tests/test_redline_wiring.py",
        marker="REDLINE-5",
        note="main() 入口按档位禁源；适配器基类另有 enforce_profile 兜底",
    ),
    dict(
        id="6_no_ci_no_claim",
        name="禁无区间措辞；护栏不可关闭",
        guard="guards.interval_line",
        hardness="hard",
        sites=[
            ("adt/cli.py", "cmd_report", "enforce_report_text"),
            ("adt/redlines.py", "scan_report_text", "interval_line"),
        ],
        test="tests/test_redline_wiring.py",
        marker="REDLINE-6",
        note="报告落盘前逐段扫描；命中即拒绝写 conclusions.md",
    ),
    dict(
        id="7_gate_eval_distribution",
        name="gate 判别力数字必须带评测分布标注",
        guard="guards.gate_distribution_line",
        hardness="hard",
        sites=[("adt/redlines.py", "scan_report_text", "gate_distribution_line")],
        test="tests/test_redline_wiring.py",
        marker="REDLINE-7",
        note="报告文本含 gate 主张而无评测分布标注即拦截",
    ),
    dict(
        id="8_external_not_preregistered",
        name="post-cutoff 数字必须同句标「非预注册前瞻」",
        guard="guards.provenance_line",
        hardness="hard",
        sites=[("adt/redlines.py", "scan_report_text", "provenance_line")],
        test="tests/test_redline_wiring.py",
        marker="REDLINE-8",
        note="报告文本含 post-cutoff 数字而无「非预注册」标记即拦截",
    ),
    dict(
        id="9_endpoint_plurality",
        name="端点依赖类结论必须三端点并列",
        guard="guards.endpoint_plurality_line",
        hardness="hard",
        sites=[("adt/redlines.py", "scan_report_text", "endpoint_plurality_line")],
        test="tests/test_redline_wiring.py",
        marker="REDLINE-9",
        note="报告文本含端点依赖结论而端点<3 且未限定即拦截",
    ),
]

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 2026-11-04 / C02：把「测试文件里含 marker 字符串」升级为「真实 pytest 节点」。
# 精确节点名（不是 -k 模糊匹配）；且刻意不包含 test_REDLINE_wiring_probe_all_nine
# 与 test_REDLINE_status_matches_guards_entry —— 它们会调用 all_wired()，
# 若纳入本表会造成 subprocess 递归。
TEST_NODES = {
    "1_input_anchor": "test_REDLINE_1_publish_blocks_ungated_input",
    "2_sample_size": "test_REDLINE_2_small_sample_banner",
    "3_replay_only": "test_REDLINE_3_publish_requires_replay",
    "4_low_validity": "test_REDLINE_4_low_validity_endpoint_downgraded",
    "5_commercial_profile": "test_REDLINE_5_unknown_profile_rejected",
    "6_no_ci_no_claim": "test_REDLINE_6_unqualified_superiority_blocked",
    "7_gate_eval_distribution": "test_REDLINE_7_gate_claim_without_distribution_blocked",
    "8_external_not_preregistered": "test_REDLINE_8_post_cutoff_without_disclaimer_blocked",
    "9_endpoint_plurality": "test_REDLINE_9_single_endpoint_extrapolation_blocked",
}


class RedLineViolation(RuntimeError):
    """聚合多条红线违规。**不可降级为 warning**（与 guards.RedLineError 同一立场）。"""


def _read(p):
    with io.open(p, encoding="utf-8") as f:
        return f.read()


def _func_segment(path, func_name):
    """返回 path 中 func_name 函数体的源码片段（含装饰器），找不到返回 None。

    用 AST 定位而非文本 grep：避免"函数名在注释里出现"造成的假阳性。
    """
    try:
        src = _read(path)
        tree = ast.parse(src)
    except (OSError, SyntaxError):
        return None
    lines = src.splitlines()
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == func_name
        ):
            end = getattr(node, "end_lineno", None)
            if end is None:
                return None
            start = node.lineno - 1
            deco = [d.lineno for d in node.decorator_list]
            if deco:
                start = min(start, min(deco) - 1)
            return "\n".join(lines[start:end])
    return None


def _func_ast(path, func_name):
    """返回 (源码, 目标函数 AST 节点)；找不到/语法错返回 None。"""
    try:
        src = _read(path)
        tree = ast.parse(src)
    except (OSError, SyntaxError):
        return None
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == func_name
        ):
            return src, node
    return None


def _call_names(call):
    """ast.Call.func 的限定名：G.interval_line -> {G.interval_line, interval_line}。"""
    f = call.func
    out = set()
    if isinstance(f, ast.Name):
        out.add(f.id)
    elif isinstance(f, ast.Attribute):
        parts, cur = [], f
        while isinstance(cur, ast.Attribute):
            parts.append(cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            parts.append(cur.id)
        out.add(".".join(reversed(parts)))
        out.add(f.attr)
    return out


def _code_evidence(path, func_name):
    """返回 (names, calls)：函数体内**真实 AST 代码节点**的名字与调用限定名。

    C02 根因：旧 probe() 用 `token in seg` 子串匹配，docstring / 注释里出现同名
    记号即判「已接线」。AST 节点天然不包含字符串字面量内容与注释，故此类
    假阳性被根除。静态探测仍是**必要条件**；充分条件由下方真跑集成测试承担。
    """
    got = _func_ast(path, func_name)
    if got is None:
        return None
    _, fn = got
    names, calls = set(), set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Name):
            names.add(n.id)
        elif isinstance(n, ast.Attribute):
            names.add(n.attr)
        elif isinstance(n, ast.keyword) and n.arg:
            names.add(n.arg)
        elif isinstance(n, ast.arg):
            # ast.arg 的字段名就是 .arg（字符串），不是 .arg.arg —— 2026-11-04 实跑修正
            names.add(n.arg)
        elif isinstance(n, ast.Call):
            names |= _call_names(n)
            calls |= _call_names(n)
            # getattr(a, "strict_input", False) 是真实的动态属性访问（生产代码里
            # 红线 1/4 的接线形式）：**仅**接受其第 2 个字符串常量参数作为代码证据。
            # 其它字符串字面量与注释一律不算 —— 这是 C02 的防线，不得放宽。
            f = n.func
            if isinstance(f, ast.Name) and f.id == "getattr" and len(n.args) >= 2:
                v = n.args[1]
                if isinstance(v, ast.Constant) and isinstance(v.value, str):
                    names.add(v.value)
    return names, calls


def _token_hit(token, names, calls):
    """含 `(` 或含 `.` 的记号必须在真实 ast.Call 中命中；其余必须在代码节点中命中。"""
    t = token.strip()
    wants_call = t.endswith("(") or t.endswith("()")
    base = t.rstrip("() ").strip()
    last = base.split(".")[-1]
    if wants_call or "." in base:
        return any(c == base or c == last or c.endswith("." + last) for c in calls)
    return last in names or last in calls


def probe(root=None):
    """逐条探测生产调用点是否存在（AST 代码节点级）。返回 [(id, ok, found, missing)]。"""
    root = root or ROOT
    out = []
    for spec in REGISTRY:
        found, missing = [], []
        for rel, fn, token in spec["sites"]:
            ev = _code_evidence(os.path.join(root, rel), fn)
            if ev is not None and _token_hit(token, ev[0], ev[1]):
                found.append("%s::%s[AST]" % (rel, fn))
            else:
                missing.append("%s::%s(缺 AST 代码节点 %r)" % (rel, fn, token))
        out.append((spec["id"], not missing, found, missing))
    return out


_TEST_RESULT_CACHE = {}


def _probe_freshness_key(root):
    """决定探测结果的内容指纹：源码 + 9 个集成测试文件的内容哈希。

    2026-11-18（全量测试抖动根因修复）：
      报错现象——全量 pytest 时 4 个红线测试文件经 `test_smoke_pytest.py`
      再套一层 subprocess 调用 `red_lines_status()`，后者又各起一个 3 层
      pytest 子进程（junitxml）。9 节点 × 多次重入在最坏情况下并发争抢
      ORCA/RDKit C 扩展与 temp 根，偶发 access violation → 假阴性。
      单独跑全过，证明不是断言问题而是重入放大。
      修复：把"真跑一次"的结果按**内容指纹**落盘缓存；同内容的所有重入
      （含跨子进程）直接复用，不再重复起 pytest。内容一变指纹即变，
      下次必真跑——不牺牲"executed"证据的诚实性（每条缓存都来自一次真实执行）。
    """
    import hashlib

    h = hashlib.sha256()
    watch = [
        os.path.join(root, "adt", "redlines.py"),
        os.path.join(root, "adt", "guards.py"),
        os.path.join(root, "adt", "release_gate.py"),
    ]
    watch += [os.path.join(root, s["test"]) for s in REGISTRY]
    for p in watch:
        if os.path.isfile(p):
            h.update(p.encode("utf-8"))
            h.update(io.open(p, "rb").read())
    return h.hexdigest()[:16]


def _cache_path(root, fresh):
    d = os.path.join(root, ".pytest_cache", "adt_redline_probe")
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        return None
    return os.path.join(d, "probe_%s.json" % fresh)


def _run_redline_tests(root):
    """一次 subprocess 真跑 9 个 REDLINE 集成测试节点，junitxml 逐条解析。

    fail-closed：pytest 缺失 / 超时 / 节点缺失 / FAILED / SKIPPED 一律判 False。
    结果按 root 缓存；2026-11-18 起额外按内容指纹落盘缓存，杜绝嵌套重入抖动。
    """
    key = os.path.abspath(root)
    fresh = _probe_freshness_key(root)
    if key in _TEST_RESULT_CACHE:
        cached = _TEST_RESULT_CACHE[key]
        if cached.get("_fresh") == fresh:
            return cached["results"]
    cp = _cache_path(root, fresh)
    if cp and os.path.isfile(cp):
        try:
            obj = json.load(io.open(cp, encoding="utf-8"))
            if obj.get("_fresh") == fresh and obj.get("results"):
                results_disk = {k: tuple(v) for k, v in obj["results"].items()}
                _TEST_RESULT_CACHE[key] = {"_fresh": fresh, "results": results_disk}
                return results_disk
        except Exception:
            pass  # 缓存损坏 → 真跑一次重建
    nodes = ["%s::%s" % (spec["test"], TEST_NODES[spec["id"]]) for spec in REGISTRY]
    results = {spec["id"]: (False, "未执行") for spec in REGISTRY}
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(prefix="adt_redline_", suffix=".xml")
        os.close(fd)
        cmd = [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-o",
            "python_files=test_*.py",
            "--junitxml",
            tmp,
        ] + nodes
        proc = subprocess.run(
            cmd, cwd=root, capture_output=True, text=True, timeout=300
        )
        tree = ET.parse(tmp)
        by_name = {}
        for tc in tree.iter("testcase"):
            by_name[tc.get("name", "")] = not any(
                c.tag in ("failure", "error", "skipped") for c in tc
            )
        for spec in REGISTRY:
            node = TEST_NODES[spec["id"]]
            hit = by_name.get(node)
            if hit is True:
                results[spec["id"]] = (True, "executed: %s" % node)
            elif hit is False:
                results[spec["id"]] = (False, "集成测试失败/跳过: %s" % node)
            else:
                results[spec["id"]] = (False, "junitxml 无此节点: %s" % node)
        if proc.returncode not in (0, 1) and all(v[0] for v in results.values()):
            results = {k: (False, "pytest rc=%s" % proc.returncode) for k in results}
        _TEST_RESULT_CACHE[key] = {"_fresh": fresh, "results": results}
        # 只把"全部通过"的结果落盘：失败不缓存，下次仍真跑，
        # 避免把一次偶发失败固化成长期假阴性（fail-closed 的精神）。
        if cp and all(v[0] for v in results.values()):
            try:
                with io.open(cp, "w", encoding="utf-8") as fh:
                    json.dump(
                        {
                            "_fresh": fresh,
                            "results": {k: list(v) for k, v in results.items()},
                        },
                        fh,
                        ensure_ascii=False,
                        sort_keys=True,
                    )
            except OSError:
                pass
    except Exception as exc:
        results = {
            spec["id"]: (False, "集成测试无法执行: %r" % (exc,)) for spec in REGISTRY
        }
        _TEST_RESULT_CACHE[key] = {"_fresh": fresh, "results": results}
    finally:
        if tmp and os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass
    return results


def _test_ok(spec, root, run_tests=True):
    p = os.path.join(root, spec["test"])
    if not os.path.isfile(p):
        return False, "缺测试文件 %s" % spec["test"]
    if spec["id"] not in TEST_NODES:
        return False, "未登记 pytest 节点 %s" % spec["id"]
    if not run_tests:
        # 仅供本模块内部避免递归；标记 static_only，G8 不得据此放行。
        txt = _read(p)
        ok = spec["marker"] in txt and TEST_NODES[spec["id"]] in txt
        return ok, "static_only_non_authoritative"
    return _run_redline_tests(root)[spec["id"]]


def status(root=None, run_tests=True):
    """返回 {id: dict(ok, hardness, sites, missing, test_ok, test_evidence, note)}。

    G8 读这个。test_evidence=executed 才是可被发布门禁采信的证据。
    """
    root = root or ROOT
    probes = {pid: (ok, found, missing) for pid, ok, found, missing in probe(root)}
    res = {}
    for spec in REGISTRY:
        ok_p, found, missing = probes[spec["id"]]
        ok_t, why_t = _test_ok(spec, root, run_tests=run_tests)
        evidence = (
            "static_only" if not run_tests else ("executed" if ok_t else "failed")
        )
        res[spec["id"]] = dict(
            ok=bool(ok_p and ok_t),
            hardness=spec["hardness"],
            name=spec["name"],
            guard=spec["guard"],
            sites=found,
            missing=missing,
            test=spec["test"],
            test_ok=ok_t,
            test_why=why_t,
            test_evidence=evidence,
            note=spec["note"],
        )
    return res


def all_wired(root=None, run_tests=True):
    st = status(root, run_tests=run_tests)
    bad = [k for k, v in st.items() if not v["ok"]]
    return (not bad), st, bad


def hardness_census(root=None):
    """材料层引用红线时的**必抄**一句：不要写"九条全部阻断"。"""
    st = status(root)
    c = {}
    for v in st.values():
        c[v["hardness"]] = c.get(v["hardness"], 0) + 1
    return dict(
        total=len(st),
        by_hardness=c,
        sentence="九条红线均已接线（%d 条 hard 阻断 / %d 条 soft 告警可升级 / "
        "%d 条 conditional 发布模式阻断）"
        % (c.get("hard", 0), c.get("soft", 0), c.get("conditional", 0)),
    )


# ---------------------------------------------------------------------------
# 文本红线扫描：报告/材料落盘前的统一闸门
# ---------------------------------------------------------------------------
def scan_report_text(text, ctx=None):
    """对**面向人**的文本跑全部文本类红线（6/7/8/9）+ 真值一致性措辞（R12）。

    返回 violations: [{red_line, message}]；空列表 = 通过。
    设计原则：**不猜意图，只拦模式**——宁可让作者改写一句话，也不放过一个
    "前瞻验证通过"（红线 8 的反例正是这么写出去的）。
    """
    from . import guards as G
    from . import phrasing as PH

    ctx = ctx or {}
    out = []

    def _try(red_line, fn, *args, **kw):
        try:
            fn(*args, **kw)
        except Exception as exc:
            out.append(dict(red_line=red_line, message=str(exc)))

    _try(6, G.interval_line, text, has_ci_or_test=bool(ctx.get("has_ci_or_test")))
    _try(
        7,
        G.gate_distribution_line,
        text,
        eval_distribution=ctx.get("eval_distribution"),
        auc=ctx.get("gate_auc"),
    )
    _try(8, G.provenance_line, text)
    _try(9, G.endpoint_plurality_line, text, endpoints=ctx.get("endpoints"))

    # R12：真值一致性措辞（按 n 分级），与红线同一闸门出口
    tr = PH.flag_truth_consistency_claim(text, n=ctx.get("n_compounds"))
    if tr["hits"]:
        out.append(
            dict(
                red_line="R12_truth_claim",
                message="出现真值一致性主张 %s；%s" % (tr["hits"], tr["advice"]),
            )
        )

    # R18 / C18（外审 A，2026-11-04）：Δu(c)=a−q·c 会计恒等式主张。
    # 默认 accounting_only=True —— 当前产物尚未证明代价进入决策，举证责任在作者侧。
    # 只有同时给出 cost_decision_verified=True 且 accounting_only=False 的 ctx
    # 才允许解除；单凭文本自称「已重构」不予放行。
    acct_only = bool(ctx.get("accounting_only", True))
    verified = bool(ctx.get("cost_decision_verified", False))
    if verified and not acct_only:
        acct_only = False
    acct = PH.flag_accounting_claims(text, accounting_only=acct_only)
    if acct["hits"] and not ctx.get("accounting_claims_permitted"):
        out.append(
            dict(
                red_line="R18_accounting_identity",
                message="出现会计恒等式主张 %s；%s 解除条件：产物须给出 "
                "cost_decision.sweep_decision_masks 且 distinct_decided_masks>1，"
                "并在 ctx 中带 cost_decision_verified=True / accounting_only=False。"
                % (acct["hits"], acct["advice"]),
            )
        )
    return out


def enforce_report_text(text, outdir=None, ctx=None, stage="report"):
    """报告落盘前调用。有违规 → 落盘违规清单并抛 RedLineViolation（非零退出）。"""
    v = scan_report_text(text, ctx=ctx)
    if not v:
        return dict(ok=True, violations=[])
    lines = [
        "# 红线拦截清单（%s）" % stage,
        "",
        "> 本文件由 `adt.redlines.enforce_report_text` 生成。报告**未被写出**。",
        "> 每一条都必须改写原文或补足证据后才可重跑。",
        "",
    ]
    for i, item in enumerate(v, 1):
        lines.append("## %d. 红线 %s" % (i, item["red_line"]))
        lines.append("")
        lines.append("```")
        lines.append(item["message"])
        lines.append("```")
        lines.append("")
    body = "\n".join(lines)
    if outdir:
        try:
            os.makedirs(outdir, exist_ok=True)
            with io.open(
                os.path.join(outdir, "REDLINE_VIOLATIONS.md"), "w", encoding="utf-8"
            ) as f:
                f.write(body + "\n")
        except OSError:
            pass
    raise RedLineViolation(body)


def require_replay(action="publish"):
    """薄包装：统一从 guards 取，避免两处实现漂移。"""
    from . import guards as G

    return G.require_replay(action)


def main(argv=None):
    """`python -m adt.redlines` 自检：接线普查 + 硬度普查。"""
    argv = argv if argv is not None else sys.argv[1:]
    root = argv[0] if argv else ROOT
    ok, st, bad = all_wired(root)
    print("[redlines] %s" % ("PASS" if ok else "FAIL"))
    for k in sorted(st):
        v = st[k]
        flag = "OK  " if v["ok"] else "FAIL"
        print(
            "  %s %-28s hardness=%-11s sites=%s%s"
            % (
                flag,
                k,
                v["hardness"],
                ",".join(v["sites"]) or "-",
                "" if v["ok"] else "  << %s" % (v["missing"] or v["test_why"]),
            )
        )
    print("  " + hardness_census(root)["sentence"])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
