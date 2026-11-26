# -*- coding: utf-8 -*-
"""来源依赖审计回归测试：防"共享训练生态的源被当成独立票"（PACT/data-incest 评审点）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import source_dependence_audit as sda  # noqa: E402


def test_all_active_sources_have_group():
    rows, issues = sda.audit()
    bad = [i for i in issues if i["kind"] == "missing_independence_group"]
    assert not bad, bad


def test_no_group_conflict_between_registry_and_card():
    rows, issues = sda.audit()
    bad = [i for i in issues if i["kind"] == "group_conflict"]
    assert not bad, bad


def test_independent_votes_collapse_by_group():
    rows, _ = sda.audit()
    groups = {r["reg_group"] for r in rows if r["reg_group"] != "—"}
    n_active = sum(1 for r in rows if r["status"] == "ok")
    assert 0 < len(groups) < n_active, (len(groups), n_active)


def test_generated_doc_exists_and_has_no_unclosed_issues():
    p = os.path.join(sda.ROOT, "references", "SOURCE_DEPENDENCE.md")
    assert os.path.isfile(p)
    txt = open(p, encoding="utf-8").read()
    assert "## 待闭合问题（0）" in txt


if __name__ == "__main__":
    for fn in (test_all_active_sources_have_group,
               test_no_group_conflict_between_registry_and_card,
               test_independent_votes_collapse_by_group,
               test_generated_doc_exists_and_has_no_unclosed_issues):
        fn()
        print("PASS", fn.__name__)
    print("ALL OK (4 tests)")
