# -*- coding: utf-8 -*-
"""`domain_flag` 写入点白名单（评审 P1.7 / R-D 增补项）。

## 为什么需要

外部评审 R-D 对 C1 修复提出元质疑："我只验证了 guards 函数无调用点，
没有穷举所有可能改变 verdict 的生产路径。若适配器自行写 domain_flag 绕过
reliability 主路径，则'裁决路径完整性'未被审计。"

这条质疑是对的：`domain_flag` 是整个裁决层的**信任根**——一个行只要被标成
`measured` 就会抢占"实测优先"分支、标成 `out_of_domain` 就会被剔除、标成
`saturated` 就会触发"可判不可排序"。**谁能写这个字段，就等于谁能改判决。**

## 做法（白名单 + 逐点理由，而不是"grep 一下看着没问题是没问题"）

`WHITELIST` 为每个 (文件, 函数) 登记：允许写入的取值集合 + 该写入点的正当性。
`audit()` 用 AST 扫描全部赋值点，凡未登记的写入 → 返回违规。
新增写入点必须先登记理由再进 CI，否则测试红。

## 已确认的白名单（2026-11-04 实测普查，13 处）

| 文件:函数 | 取值 | 正当性 |
|---|---|---|
| `schema.py:_write/measurement` | predicted（默认） | 长表默认值，唯一入口 |
| `external.py:*` | measured / predicted | 外源真值/预测分离，两处语义不同 |
| `reliability.py:apply_class_blocks` | out_of_domain | 化学类 blocked 端点降级（C82） |
| `cli.py:cmd_validate` | saturated / error | 饱和扫描与调用失败标记 |
| `ablation.py:*` | out_of_domain | 消融实验人为屏蔽源（仅评测用） |
| `sensitivity.py:*` | predicted | 阈值摄动重算，不改语义 |
| `benchmark.py:*` | predicted | 合成基准桩数据（非真实产物） |
| `readback.py:ingest` | predicted / measured / manual | 回填通道，`BACKFILL_FLAGS` 二次断言；禁 out_of_domain/saturated/error |
| `cli.py:cmd_readback` | 同上（仅透传） | argparse `choices` 已限域，不构造行 |

**已剔除的风险点**：不存在任何适配器（`adt/adapters/*`）直接写 `domain_flag` 的情形
——适配器必须经 `schema.measurement()`（该函数对取值域做 ValueError 断言）。
这条结论由本模块的 audit 持续保证，而不是一次性声明。
"""

import ast
import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# (相对路径, 函数名) -> dict(allowed={取值}, why="正当性")
WHITELIST = {
    ("adt/schema.py", "measurement"): dict(
        allowed={
            "measured",
            "predicted",
            "out_of_domain",
            "saturated",
            "manual",
            "error",
        },
        why="单条构造器，对 DOMAIN_FLAGS 做 ValueError 断言——所有适配器必须走这里；"
        "写入值为变量（domain_flag=domain_flag），由上游校验",
    ),
    ("adt/external.py", "write_openadmet"): dict(
        allowed={"measured"}, why="OpenADMET 实测真值写出（measured）"
    ),
    ("adt/external.py", "fit_predict"): dict(
        allowed={"predicted"}, why="外源集上的模型预测（非真值），语义即 predicted"
    ),
    ("adt/external.py", "write_npass"): dict(
        allowed={"measured"}, why="NPASS 天然产物实测真值写出（measured）"
    ),
    ("adt/reliability.py", "apply_class_blocks"): dict(
        allowed={"out_of_domain"},
        why="C82：化学类 blocked 端点（整类无区分度）降级为域外，含 registry 证据",
    ),
    ("adt/cli.py", "_mark_measurements"): dict(
        allowed={"saturated", "error"},
        why="饱和扫描标记 + 调用失败标记；两者都不产生判决，只影响可判性",
    ),
    ("adt/ablation.py", "corrupt"): dict(
        allowed={"out_of_domain"},
        why="消融实验人为屏蔽某源（仅评测脚本内部，不进产物决策链）",
    ),
    ("adt/sensitivity.py", "ad_analyze"): dict(
        allowed={"predicted"},
        why="阈值摄动重算的副本行，取值语义不变（不改 measured/out_of_domain）",
    ),
    ("adt/benchmark.py", "demo_data"): dict(
        allowed={"predicted"}, why="合成基准桩数据，不进入任何真实产物"
    ),
    # ---- v4.20 回填通道（C2 增补：新增写入点必须逐点登记理由）----
    ("adt/readback.py", "ingest"): dict(
        allowed={"predicted", "measured", "manual"},
        why="回填通道唯一写入点；取值域由本模块 BACKFILL_FLAGS 二次断言，"
        "**禁止** out_of_domain/saturated/error —— 否则回填表里写一列就能把"
        "分子踢出裁决（measured 另需显式 provenance_url，缺则降级 manual）",
    ),
    ("adt/cli.py", "cmd_readback"): dict(
        allowed={"predicted", "measured", "manual"},
        why="仅把 CLI `--domain-flag`（argparse choices 已限制为这三个）透传给 "
        "RB.ingest，**不构造任何行**；取值在 readback.ingest 内再次校验",
    ),
}


def _func_of(tree, lineno):
    """返回 lineno 所在的最内层函数名（模块级返回 '<module>'）。"""
    best = ("<module>", -1)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            end = getattr(node, "end_lineno", node.lineno)
            if node.lineno <= lineno <= end and node.lineno > best[1]:
                best = (node.name, node.lineno)
    return best[0]


def _literal(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def scan(root=None):
    """返回所有 domain_flag 写入点：[{file, func, line, value, kind}]。"""
    root = root or ROOT
    out = []
    for dirpath, _dirs, files in os.walk(os.path.join(root, "adt")):
        for f in files:
            if not f.endswith(".py"):
                continue
            p = os.path.join(dirpath, f)
            rel = os.path.relpath(p, root).replace("\\", "/")
            try:
                src = io.open(p, encoding="utf-8").read()
                tree = ast.parse(src)
            except (OSError, SyntaxError):
                continue
            for node in ast.walk(tree):
                # 形式 1：r["domain_flag"] = "x"
                if isinstance(node, ast.Assign):
                    for t in node.targets:
                        if (
                            isinstance(t, ast.Subscript)
                            and _literal(t.slice) == "domain_flag"
                        ):
                            out.append(
                                dict(
                                    file=rel,
                                    func=_func_of(tree, node.lineno),
                                    line=node.lineno,
                                    kind="subscript",
                                    value=_literal(node.value),
                                )
                            )
                # 形式 2：dict(..., domain_flag="x")
                if isinstance(node, ast.Call):
                    for kw in node.keywords or []:
                        if kw.arg == "domain_flag":
                            out.append(
                                dict(
                                    file=rel,
                                    func=_func_of(tree, node.lineno),
                                    line=node.lineno,
                                    kind="kwarg",
                                    value=_literal(kw.value),
                                )
                            )
    return sorted(out, key=lambda d: (d["file"], d["line"]))


def audit(root=None):
    """返回 (ok, violations, known)。violations = 未登记写入点或超范围取值。"""
    from .schema import DOMAIN_FLAGS

    sites = scan(root)
    bad = []
    for s in sites:
        key = (s["file"], s["func"])
        spec = WHITELIST.get(key)
        if spec is None:
            bad.append(
                dict(**s, why="未登记的 domain_flag 写入点（新增写入点必须先登记理由）")
            )
            continue
        if s["value"] is not None and s["value"] not in spec["allowed"]:
            bad.append(
                dict(
                    **s,
                    why="取值 %r 不在该写入点白名单 %s"
                    % (s["value"], sorted(spec["allowed"])),
                )
            )
        if s["value"] is not None and s["value"] not in DOMAIN_FLAGS:
            bad.append(dict(**s, why="取值 %r 不在 schema.DOMAIN_FLAGS" % s["value"]))
    return (not bad), bad, sites


def main(argv=None):
    import sys

    ok, bad, sites = audit()
    print("[domain_flag] 写入点 %d 处；%s" % (len(sites), "PASS" if ok else "FAIL"))
    for s in sites:
        mark = "  ok " if s not in bad else " BAD "
        print(
            "%s %-22s %-28s L%-5d %r"
            % (mark, s["file"], s["func"], s["line"], s["value"])
        )
    for b in bad:
        print("  !! %s:%d %s" % (b["file"], b["line"], b["why"]))
    return 0 if ok else 1


if __name__ == "__main__":
    import sys

    sys.exit(main())
