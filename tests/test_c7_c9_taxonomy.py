# -*- coding: utf-8 -*-
"""C7（归因分类唯一真源）与 C9（单位投射置信度分档）的回归测试。

两条都源于同一个病根：**同一个概念在仓库里有多处数字/多处口径，靠人记**。
  C7 —— SKILL.md 写"六类归因"，代码里 ORDER 有 8 类 + other，independence.py
        又把 source_conflict 称作"第七类归因"：三个数字互不相容。
  C9 —— 单位异构时的 class_map 投射路径与"同构中位数"路径共享同一置信度档，
        产物里区分不开，报告模板会把投射结果写成"中位 X"。
"""
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from adt import abstain_attrib as AA      # noqa: E402
from adt import phrasing as PH           # noqa: E402
from adt import reliability as R         # noqa: E402


# ---------------------------------------------------------------- C7
def test_taxonomy_single_source_of_truth():
    t = AA.TAXONOMY
    assert len(t["abstain"]) == 8, "弃权归因 8 类（含 other）"
    assert t["source_reliability"] == ["source_conflict"]
    assert t["total"] == 9
    assert "九类归因" in t["sentence"]


def test_skill_md_uses_taxonomy_constant():
    """SKILL.md 不得再出现自相矛盾的归因计数。"""
    s = io.open(os.path.join(ROOT, "SKILL.md"), encoding="utf-8").read()
    assert "六类归因" not in s, "旧计数残留（C7 未修完）"
    assert "TAXONOMY" in s, "SKILL.md 必须指向唯一真源，而不是自己数一遍"


def test_abstain_order_matches_docstring():
    """ORDER 与模块文档里列出的类别必须一致（防止加了一类忘了写文档）。"""
    doc = AA.__doc__ or ""
    for k in AA.ORDER:
        if k == "other":
            continue
        assert k in doc, "归因类别 %s 未写进模块文档" % k


# ---------------------------------------------------------------- C9
def _row(cid, unit, value, src):
    return dict(compound_id=cid, endpoint="herg", value=value, unit=unit,
                source=src, domain_flag="predicted")


RULES = {"herg": {"shape": "down", "pass": 0.1, "fail": 0.5,
                  "require_sources": 2, "class_map": {"0": "PASS", "1": "FAIL"}}}


def test_projection_path_is_flagged():
    rows = [_row("C1", "class", 0, "s1"), _row("C1", "probability", 0.05, "s2")]
    recs = R.evaluate(rows, rules=RULES, source_groups={"s1": "g1", "s2": "g2"})
    r = [x for x in recs if x["compound_id"] == "C1"][0]
    assert r["verdict"] == "PASS"
    assert r.get("projection_used") is True
    assert "非原始数值共识" in r["reason"]


def test_projection_statement_has_own_tier():
    st = PH.allowed_statement("PASS", "medium", n_indep=2, projection=True)
    assert st["tier"] == "projected"
    assert "中位" not in st["template"], "投射结果不得写成中位数（C9）"
    assert any("投射" in f for f in st["forbidden"])


def test_homogeneous_statement_unchanged():
    st = PH.allowed_statement("PASS", "medium", n_indep=2, projection=False)
    assert st["tier"] == "consistent_pred"
    assert "中位" in st["template"]
