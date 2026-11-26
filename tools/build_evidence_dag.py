# -*- coding: utf-8 -*-
"""从命令角色注册表生成证据 DAG（G7），避免手写文档漂移。

为什么用生成而不是手写：
  `adt/command_roles.py` 的 78 条命令已经声明了 layer / evidence_role /
  input_contract / output_contract —— 这就是一张现成的数据流图。手写
  EVIDENCE_DAG.md 一定会和代码脱钩（本项目历史上出现过多次"文档写了代码没有"，
  见 references/07_case_lessons.md）。生成式 DAG 每次可重算，并带源码哈希。

边的定义（可机器复核）：
  若命令 A 的 output_contract 出现在命令 B 的 input_contract 里，
  则连边 A -> B，标签为该 contract 名。这是**契约级**依赖，不是"看起来相关"。

输出：
  references/EVIDENCE_DAG.yaml  （机器读：nodes/edges/meta）
  references/EVIDENCE_DAG.md    （人读：分层摘要 + 关键路径 + 边界声明）

运行：python tools/build_evidence_dag.py [--check]
  --check 只比对不写盘：若现存文件与重算结果不一致则 exit 1（用于 CI 防漂移）。
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from adt import command_roles as cr  # noqa: E402

LAYER_ORDER = ["core", "sources", "decision", "evidence", "experimental"]
LAYER_MEANING = {
    "core": "输入规整与基础度量（不产生结论）",
    "sources": "外部证据源接入（产物受许可证与可达性约束）",
    "decision": "决策层：准入/组合/弃权（结论在此产生）",
    "evidence": "证据治理：门禁、预注册、manifest、审计",
    "experimental": "实验层：不进主结论链（SHADOW）",
}


def _role_granting(role):
    """哪些 evidence_role 允许产物进入结论链。"""
    return role not in ("io_utility", "governance", "experimental", "shadow")


def _tokens(s):
    """契约名 → token 集合（去扩展名、按 + / , 拆分、小写）。

    例：`measurements.csv` → {"measurements"}；`measurements+truth` → {"measurements","truth"}；
    `pred+truth` → {"pred","truth"}。契约是自由文本，token 级匹配比整串相等能抓到真实依赖，
    同时不会把 `scores` 和 `source-scores` 之外的无关项连错（仍要求 token 完全相同）。
    """
    import re

    if not s:
        return set()
    raw = str(s).lower()
    for ext in (".csv", ".json", ".yaml", ".yml", ".md", ".txt"):
        raw = raw.replace(ext, "")
    parts = re.split(r"[+,/\s]+", raw)
    out = set()
    for p in parts:
        p = p.strip("_-")
        if not p:
            continue
        out.add(p)
        if p.endswith("s") and len(p) > 3:  # 轻量复数归一：artifacts -> artifact
            out.add(p[:-1])
    return out


def build():
    roles = cr.ROLES
    nodes = []
    for cmd, m in sorted(roles.items()):
        nodes.append(
            dict(
                id=cmd,
                layer=m.get("layer"),
                evidence_role=m.get("evidence_role"),
                input=m.get("input_contract"),
                output=m.get("output_contract"),
                claimable=_role_granting(m.get("evidence_role")),
            )
        )

    edges = []
    seen = set()
    for a in nodes:
        out_tok = _tokens(a.get("output"))
        if not out_tok:
            continue
        for b in nodes:
            if a["id"] == b["id"]:
                continue
            hit = out_tok & _tokens(b.get("input"))
            if not hit:
                continue
            contract = sorted(hit)[0]
            key = (a["id"], b["id"])
            if key in seen:
                continue
            seen.add(key)
            edges.append(dict(src=a["id"], dst=b["id"], contract=contract))

    src = io.open(
        os.path.join(ROOT, "adt", "command_roles.py"), encoding="utf-8"
    ).read()
    meta = dict(
        schema="adt-evidence-dag/1.0",
        status="active",
        generated_by="tools/build_evidence_dag.py",
        source="adt/command_roles.py",
        source_sha256=hashlib.sha256(src.encode("utf-8")).hexdigest(),
        n_nodes=len(nodes),
        n_edges=len(edges),
        layers={k: sum(1 for n in nodes if n["layer"] == k) for k in LAYER_ORDER},
        rule="edge iff producer.output tokens ∩ consumer.input tokens ≠ ∅（token 级契约匹配）",
        caveat=(
            "契约级依赖不等于统计依赖：本 DAG 说明 A 的产物是 B 的合法输入，"
            "不说明 A 对 B 的结论有贡献；贡献判定见 adt/ablation.py 的同覆盖判据。"
        ),
    )
    return dict(meta=meta, nodes=nodes, edges=edges)


def to_yaml(dag):
    lines = ["# 自动生成，请勿手改（python tools/build_evidence_dag.py）"]
    m = dag["meta"]
    lines.append("meta:")
    for k, v in m.items():
        if isinstance(v, dict):
            lines.append("  %s:" % k)
            for kk, vv in v.items():
                lines.append("    %s: %s" % (kk, json.dumps(vv, ensure_ascii=False)))
        else:
            lines.append("  %s: %s" % (k, json.dumps(v, ensure_ascii=False)))
    lines.append("nodes:")
    for n in dag["nodes"]:
        lines.append("  - id: %s" % n["id"])
        lines.append("    layer: %s" % n["layer"])
        lines.append("    evidence_role: %s" % n["evidence_role"])
        lines.append(
            "    input_contract: %s" % json.dumps(n["input"], ensure_ascii=False)
        )
        lines.append(
            "    output_contract: %s" % json.dumps(n["output"], ensure_ascii=False)
        )
        lines.append("    claimable: %s" % json.dumps(n["claimable"]))
    lines.append("edges:")
    for e in dag["edges"]:
        lines.append(
            "  - {src: %s, dst: %s, contract: %s}" % (e["src"], e["dst"], e["contract"])
        )
    return "\n".join(lines) + "\n"


def to_md(dag):
    m = dag["meta"]
    out = [
        "# 证据 DAG（自动生成）",
        "",
        "> 生成器：`tools/build_evidence_dag.py`；源：`adt/command_roles.py`",
        "> 源码哈希：`%s`" % m["source_sha256"][:16],
        "> 规模：%d 节点 / %d 边；分层 %s" % (m["n_nodes"], m["n_edges"], m["layers"]),
        "> 状态：`%s`（由注册表重算，不依赖人工维护）" % m["status"],
        "",
        "## 层间含义",
        "",
        "| 层 | 含义 | 命令数 |",
        "|---|---|---|",
    ]
    for k in LAYER_ORDER:
        out.append("| `%s` | %s | %d |" % (k, LAYER_MEANING[k], m["layers"].get(k, 0)))
    out += [
        "",
        "## 契约边（按层对聚合，完整清单见 EVIDENCE_DAG.yaml）",
        "",
        "| 源层 → 目标层 | 边数 | 代表契约 |",
        "|---|---|---|",
    ]
    agg = {}
    layer_of = {n["id"]: n["layer"] for n in dag["nodes"]}
    for e in dag["edges"]:
        key = (layer_of.get(e["src"]), layer_of.get(e["dst"]))
        agg.setdefault(key, []).append(e["contract"])
    for (a, b), contracts in sorted(agg.items(), key=lambda kv: -len(kv[1])):
        out.append("| %s → %s | %d | `%s` |" % (a, b, len(contracts), contracts[0]))
    out += [
        "",
        "## 边界声明（必须随图一起引用）",
        "",
        "1. " + m["caveat"],
        "2. `evidence_role` 为 `io_utility` / `governance` / `experimental` 的命令**不**",
        "   授予结论资格；其产物可作输入，但不得被引用为证据。",
        "3. 本图不含数据资产（见 `DATA_MANIFEST.json`）与外部服务可用性（见 `env-audit`）。",
        "4. 分层是**治理标记**，不是调用顺序；实际执行顺序由 CLI 契约与 `ADT_ENFORCE_ROLES` 决定。",
        "",
    ]
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    dag = build()
    y = to_yaml(dag)
    md = to_md(dag)
    ypath = os.path.join(ROOT, "references", "EVIDENCE_DAG.yaml")
    mpath = os.path.join(ROOT, "references", "EVIDENCE_DAG.md")
    if a.check:
        bad = []
        for p, new in ((ypath, y), (mpath, md)):
            old = io.open(p, encoding="utf-8").read() if os.path.isfile(p) else ""
            if old != new:
                bad.append(p)
        if bad:
            print(
                "[evidence-dag] 已漂移：%s（重跑 python tools/build_evidence_dag.py）"
                % bad
            )
            return 1
        print("[evidence-dag] 无漂移")
        return 0
    io.open(ypath, "w", encoding="utf-8", newline="\n").write(y)
    io.open(mpath, "w", encoding="utf-8", newline="\n").write(md)
    print(
        "[evidence-dag] %d 节点 / %d 边 -> references/EVIDENCE_DAG.{yaml,md}"
        % (dag["meta"]["n_nodes"], dag["meta"]["n_edges"])
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
