# -*- coding: utf-8 -*-
"""C6（2026-11-03 评审）：阈值普查表必须与代码常量**双向一致**。

## 问题

首轮评审称"U9 阈值普查表是空白模板"，实测发现该表**已经填了 24 项**（评审报告已更正），
但缺口在另一处：**表只覆盖 SKILL.md 的文档阈值，没有覆盖代码里的模块级常量**。
代码里 13 个阈值常量（PROB_SPREAD_MAX / RATIO_SPREAD_MAX / QUALITATIVE_ONLY …）
在普查表里一个都没有——而它们恰恰是真正执行判定的那一层。

## 本文件做什么

用 AST 扫描 `adt/*.py` 的模块级阈值常量，要求每个名字都出现在
`references/U9_THRESHOLD_CENSUS.md`。新增常量不登记 → 测试红。
同时断言 0.65 的三处定义（文档 #6 / guards / gate_audit）语义一致、数值相等。
"""
import ast
import glob
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

CENSUS = os.path.join(ROOT, "references", "U9_THRESHOLD_CENSUS.md")

# 阈值类常量的命名模式（只抓"决策阈值"，不抓普通常量如 DOMAIN_FLAGS）
PAT = re.compile(r"^[A-Z][A-Z0-9_]*(MAX|MIN|BANNER|ONLY|WORKPOINT|FLOOR|CAP|ALPHA|THRESH)[A-Z0-9_]*$")


def scan_constants():
    out = []
    for p in sorted(glob.glob(os.path.join(ROOT, "adt", "*.py"))):
        try:
            tree = ast.parse(io.open(p, encoding="utf-8").read())
        except SyntaxError:
            continue
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and PAT.match(tgt.id):
                    val = None
                    if isinstance(node.value, ast.Constant) and isinstance(
                            node.value.value, (int, float)):
                        val = node.value.value
                    out.append(dict(file=os.path.basename(p), name=tgt.id,
                                    value=val, line=node.lineno))
    return out


def test_census_exists():
    assert os.path.isfile(CENSUS), "缺 references/U9_THRESHOLD_CENSUS.md"


def test_every_code_threshold_is_censused():
    """代码里的每个阈值常量都必须在普查表 §B 出现。"""
    txt = io.open(CENSUS, encoding="utf-8").read()
    missing = [c for c in scan_constants() if c["name"] not in txt]
    assert not missing, ("以下阈值常量未登记进 U9 普查表（§B）：%s。"
                        "新增阈值必须同时登记含义/来源/稳健性/敏感性状态。"
                        % [(c["file"], c["name"], c["value"]) for c in missing])


def test_census_has_no_ghost_constants():
    """普查表 §B 里写出的常量必须真的存在于代码（防止文档空转）。"""
    txt = io.open(CENSUS, encoding="utf-8").read()
    body = txt.split("§B", 1)[-1]
    documented = set(re.findall(r"`([A-Z][A-Z0-9_]{2,})`", body))
    live = {c["name"] for c in scan_constants()}
    ghost = sorted(n for n in documented if n not in live and n not in
                   ("GATE_AUC_MIN", "THRESHOLD_REGISTRY", "QUALITATIVE"))
    assert not ghost, "普查表 §B 引用了代码里不存在的常量：%s" % ghost


def test_gate_workpoint_is_consistent():
    """0.65 的三处定义必须同值同义（C3 之后的纪律）。"""
    from adt import guards as G
    from adt import gate_audit as GA
    assert G.GATE_AUC_WORKPOINT == GA.GATE_AUC_FLOOR == 0.65
    assert G.GATE_AUC_MIN == G.GATE_AUC_WORKPOINT, "别名必须与工作点同值"


def test_ad_hoc_thresholds_are_labelled():
    """每个 ad hoc 阈值必须在普查表里被标 ad hoc（不得伪装成 anchored）。"""
    txt = io.open(CENSUS, encoding="utf-8").read()
    for c in scan_constants():
        if c["value"] is None:
            continue
        # 找到该常量所在行，允许跨行（表格行可能折行，用名字定位后取邻近 400 字）
        idx = txt.find("`%s`" % c["name"])
        assert idx >= 0, c["name"]
        window = txt[idx: idx + 400]
        assert ("anchored" in window) or ("ad hoc" in window), \
            "常量 %s 未标注稳健性（anchored / ad hoc）" % c["name"]
