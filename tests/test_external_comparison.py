# -*- coding: utf-8 -*-
"""G14 外部对照台账的回归测试（2026-11-19）。

为什么这些用例必须存在：本仓库连续三轮出现"selftest 全绿但实现是错的"。
如果只测"对照能跑通"，那么台账写 0、代码已漂移时仍然会绿——那正是事故的形态。
所以这里刻意测**反面**：人为制造漂移，门禁必须红。

用例分组：
  1) 对照本身全通过，且覆盖面（点数）不为空；
  2) 台账棘轮：required_modules 漏登必须被拦；
  3) 台账完整性：脚本/审查报告/回归测试节点缺失必须被拦；
  4) 实测漂移：参考实现被改动 → 门禁必须报 blocker（而不是采信台账自述数字）；
  5) 容差不可满足：台账把容差写死到 1e-18 → 必须报 blocker；
  6) 分类量语义：OOT 对照组必须同时出现 OOT 与 IN_CONTROL 两种结论（否则
     "全判 IN_CONTROL" 这种最危险的漏报也能通过一致性命中）。

刻意不 mock 统计实现：一旦 mock，测的就是 mock 而非被测物。
"""
import io
import os
import shutil
import sys

import yaml

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from adt import external_comparison as ec      # noqa: E402
from adt import release_gate as rg             # noqa: E402

LEDGER = os.path.join(HERE, "references", "EXTERNAL_COMPARISON_LEDGER.yaml")


def _ledger():
    return yaml.safe_load(io.open(LEDGER, encoding="utf-8"))


def _write_tmp_ledger(tmp_path, data):
    """在临时 root 下复制最小骨架，避免污染真实 references/。"""
    root = str(tmp_path / "root")
    os.makedirs(os.path.join(root, "references"), exist_ok=True)
    for rel in ("adt", "logs/peer_review_20261117", "tests"):
        os.makedirs(os.path.join(root, rel), exist_ok=True)
    with io.open(os.path.join(root, "references",
                              "EXTERNAL_COMPARISON_LEDGER.yaml"), "w",
                 encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, allow_unicode=True, sort_keys=False)
    return root


# ---------------------------------------------------------------- 1) 对照本身

def test_comparisons_all_pass():
    r = ec.run()
    bad = [(e["module"], e["max_abs_deviation"]) for e in r["entries"]
           if not e["passed"]]
    assert not bad, "外部对照未通过：%s" % bad
    assert r["n_points"] >= 20, "对照点太少（%d），覆盖不足" % r["n_points"]
    assert r["all_passed"] is True


def test_comparisons_cover_both_branches_of_categorical_checks():
    """OOT 是分类量：若实现"永远判 IN_CONTROL"，一致性命中仍会全绿。

    因此必须要求对照用例里两种结论都出现——这是漏报类缺陷的唯一防线。
    """
    verdicts = {ec.ref_oot_prefix(s) for s in ec._OOT}
    assert {"OOT", "IN_CONTROL"} <= verdicts, \
        "OOT 对照用例必须同时包含越界与受控两种情形，实际：%s" % verdicts


# ---------------------------------------------------------------- 2) 棘轮

def test_ledger_ratchet_missing_module_blocks(tmp_path):
    d = _ledger()
    # 删掉 required 里的一条，但保留 entries —— 必须报"棘轮未覆盖"
    d["required_modules"] = list(d["required_modules"]) + ["new_stats_module.foo"]
    root = _write_tmp_ledger(tmp_path, d)
    it = rg._check_external_comparison(root)
    assert it["ok"] is False and it["level"] == "blocker"
    assert "棘轮未覆盖" in it["detail"]


# ---------------------------------------------------------------- 3) 完整性

def test_ledger_missing_review_report_blocks(tmp_path):
    d = _ledger()
    d["entries"][0]["review_report"] = "logs/不存在.md"
    root = _write_tmp_ledger(tmp_path, d)
    it = rg._check_external_comparison(root)
    assert it["ok"] is False and "独立审查报告不存在" in it["detail"]


def test_ledger_missing_regression_node_blocks(tmp_path):
    d = _ledger()
    d["entries"][0]["regression_test"] = \
        "tests/test_stats_ci.py::test_this_node_does_not_exist"
    root = _write_tmp_ledger(tmp_path, d)
    # 需要真实测试文件才能走到"节点不存在"分支
    shutil.copy(os.path.join(HERE, "tests", "test_stats_ci.py"),
                os.path.join(root, "tests", "test_stats_ci.py"))
    it = rg._check_external_comparison(root)
    assert it["ok"] is False and "回归测试节点不存在" in it["detail"]


def test_ledger_missing_file_blocks(tmp_path):
    root = _write_tmp_ledger(tmp_path, _ledger())
    os.remove(os.path.join(root, "references",
                           "EXTERNAL_COMPARISON_LEDGER.yaml"))
    it = rg._check_external_comparison(root)
    assert it["ok"] is False and "缺 references/EXTERNAL_COMPARISON_LEDGER.yaml" \
        in it["detail"]


# ---------------------------------------------------------------- 4) 漂移

def test_reference_drift_is_caught(monkeypatch):
    """台账写 0 不算数——门禁必须实跑对照并抓到实现/参考的漂移。"""
    orig = ec.ref_t_p_two_sided

    def shifted(r, n):
        v = orig(r, n)
        return None if v is None else v * 1.5

    monkeypatch.setattr(ec, "ref_t_p_two_sided", shifted)
    it = rg._check_external_comparison(HERE)
    assert it["ok"] is False and it["level"] == "blocker"
    assert "超容差" in it["detail"]


def test_impossible_tolerance_blocks(tmp_path):
    d = _ledger()
    for e in d["entries"]:
        if e["module"].startswith("evidence_streams"):
            e["tolerance"] = 1e-18
    root = _write_tmp_ledger(tmp_path, d)
    # 对照脚本与测试/报告需真实存在，才能走到"超容差"分支
    for rel in ("adt/external_comparison.py",
                "logs/peer_review_20261117/code_review_100papers.md",
                "logs/peer_review_20261117/code_review_market100.md",
                "tests/test_stats_ci.py", "tests/test_estimand.py"):
        src = os.path.join(HERE, rel)
        dst = os.path.join(root, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy(src, dst)
    it = rg._check_external_comparison(root)
    assert it["ok"] is False and "超容差" in it["detail"]


# ---------------------------------------------------------------- 5) 真实仓库

def test_repo_ledger_passes():
    it = rg._check_external_comparison(HERE)
    assert it["ok"] is True, "真实仓库的 G14 不通过：%s / %s" % (
        it["detail"], it.get("fix"))
