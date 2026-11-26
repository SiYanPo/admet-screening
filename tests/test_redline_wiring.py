# -*- coding: utf-8 -*-
"""红线**接线**集成测试（评审 C1 修复）。

本文件存在的唯一目的：证明九条红线不是"测试里能通过的函数"，而是
**在生产命令的调用路径上真的会开火**。因此绝大多数用例走 subprocess，
断言的是**命令的返回码与产物是否存在**，而不是内部函数的返回值。

判定口径（与评审原文一致）："能不能用一条命令绕过，能绕过就不是红线。"
所以每条用例都是一次"绕过尝试"：构造一份违规输入，看命令是否拒绝产出。

记号：`REDLINE-<id>` 供 `adt.redlines` 的接线普查识别本文件为真集成测试。
"""
import csv
import io
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable


@pytest.fixture(autouse=True)
def _clean_tmp(tmp_path):
    """清空 tmp_path：pytest 按测试名复用目录，上一轮的 conclusions.md 会伪造"没拦住"。"""
    if tmp_path.exists():
        for f in list(tmp_path.iterdir()):
            if f.is_file():
                f.unlink()
    yield


def _run(args, cwd=None, env=None, replay=False):
    e = dict(os.environ)
    e.pop("ADT_REPLAY", None)
    e.pop("ADT_ALLOW_ONLINE", None)
    if replay:
        e["ADT_REPLAY"] = "1"
    if env:
        e.update(env)
    return subprocess.run([PY, "-m", "adt.cli"] + args, cwd=cwd or ROOT,
                          env=e, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def _write_reliability(path, statement="实测结果为 0.42 probability——结论：PASS",
                       endpoint="hERG", verdict="PASS", n=1):
    cols = ["compound_id", "endpoint", "n_total", "n_in_domain", "n_measured",
            "sources", "n_indep_groups", "indep_groups", "value_used", "unit",
            "spread", "verdict", "confidence", "reason", "action", "bbb_mechanism",
            "allowed_statement", "certainty_modifier", "certainty_rationale",
            "grade_indirectness", "grade_inconsistency", "grade_imprecision",
            "grade_rob", "expert_rule_layer", "alert_hit"]
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with io.open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for i in range(n):
            w.writerow(dict(compound_id="C%d" % (i + 1), endpoint=endpoint,
                            n_total=2, n_in_domain=2, n_measured=0,
                            sources="s1;s2", n_indep_groups=2, indep_groups="a;b",
                            value_used=0.42, unit="probability", spread=0.05,
                            verdict=verdict, confidence="medium",
                            reason="2 个域内源一致", action="",
                            allowed_statement=statement))
    return path


def _write_gate(path, status="fail"):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with io.open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["compound_id", "status", "reasons",
                                           "inchikey_input", "inchikey_calc"])
        w.writeheader()
        w.writerow(dict(compound_id="C1", status=status,
                        reasons="立体未声明", inchikey_input="", inchikey_calc=""))


# ---------------------------------------------------------------- 接线普查
def test_REDLINE_wiring_probe_all_nine():
    """REDLINE-1..REDLINE-9：九条红线必须都探测到生产调用点 + 集成测试。"""
    from adt import redlines as RL
    ok, st, bad = RL.all_wired(ROOT)
    assert ok, "未接线：%s" % {k: (st[k]["missing"], st[k]["test_why"]) for k in bad}
    assert len(st) == 9
    # 硬度必须如实暴露，禁止"九条全部阻断"这种合并表述
    census = RL.hardness_census(ROOT)
    assert census["total"] == 9
    assert census["sentence"].startswith("九条红线均已接线")


def test_REDLINE_status_matches_guards_entry():
    """G8 的输入源必须是探测结果，不得是硬编码 ok=True。"""
    from adt import guards as G
    st = G.red_lines_status()
    assert all("where" in v for v in st.values())
    # 至少一条必须给出真实调用点（"adt/cli.py::cmd_..." 形态），
    # 证明确实读到了生产代码而不是自声明
    assert any("::" in v["where"] for v in st.values()), st


# ---------------------------------------------------------------- 红线 3
def test_REDLINE_3_publish_requires_replay(tmp_path):
    """REDLINE-3：--publish 无 ADT_REPLAY → exit 4 且不产出 conclusions.md。"""
    relp = _write_reliability(str(tmp_path / "reliability.csv"))
    r = _run(["report", "--reliability", relp, "--outdir", str(tmp_path),
              "--publish"])
    assert r.returncode == 4, r.stderr
    assert not (tmp_path / "conclusions.md").exists()
    assert "红线 3" in r.stderr


# ---------------------------------------------------------------- 红线 1
def test_REDLINE_1_publish_blocks_ungated_input(tmp_path):
    """REDLINE-1：input_gate.csv 有拦截 → 发布模式拒绝出结论段。"""
    relp = _write_reliability(str(tmp_path / "reliability.csv"))
    _write_gate(str(tmp_path / "input_gate.csv"), status="fail")
    r = _run(["report", "--reliability", relp, "--outdir", str(tmp_path),
              "--publish"], replay=True)
    assert r.returncode == 4, r.stderr
    assert "红线 1" in r.stderr
    assert not (tmp_path / "conclusions.md").exists()


# ---------------------------------------------------------------- 红线 8
def test_REDLINE_8_post_cutoff_without_disclaimer_blocked(tmp_path):
    """REDLINE-8：post-cutoff 数字 + "前瞻验证通过" → 拒绝落盘。"""
    relp = _write_reliability(
        str(tmp_path / "reliability.csv"),
        statement="post-cutoff 外源留出 AUC 0.581，前瞻验证通过")
    r = _run(["report", "--reliability", relp, "--outdir", str(tmp_path)])
    assert r.returncode == 4, r.stderr
    assert not (tmp_path / "conclusions.md").exists()
    v = io.open(str(tmp_path / "REDLINE_VIOLATIONS.md"), encoding="utf-8").read()
    assert "红线 8" in v


# ---------------------------------------------------------------- 红线 6
def test_REDLINE_6_unqualified_superiority_blocked(tmp_path):
    """REDLINE-6：无 CI 的"略优" → 拒绝落盘。"""
    relp = _write_reliability(str(tmp_path / "reliability.csv"),
                              statement="仅单位守卫 7.83% 略优")
    r = _run(["report", "--reliability", relp, "--outdir", str(tmp_path)])
    assert r.returncode == 4, r.stderr
    assert not (tmp_path / "conclusions.md").exists()


# ---------------------------------------------------------------- 红线 7
def test_REDLINE_7_gate_claim_without_distribution_blocked(tmp_path):
    """REDLINE-7：报告写 gate AUC 但未给评测分布 → 拒绝落盘。"""
    relp = _write_reliability(str(tmp_path / "reliability.csv"),
                              statement="gate AUC 0.580，本框架域外弃权诚实")
    r = _run(["report", "--reliability", relp, "--outdir", str(tmp_path)])
    assert r.returncode == 4, r.stderr
    assert "红线 7" in io.open(str(tmp_path / "REDLINE_VIOLATIONS.md"),
                              encoding="utf-8").read()


# ---------------------------------------------------------------- 红线 9
def test_REDLINE_9_single_endpoint_extrapolation_blocked(tmp_path):
    """REDLINE-9：单端点外推"gate 判别力"结论，且未限定范围 → 拒绝落盘。"""
    relp = _write_reliability(str(tmp_path / "reliability.csv"),
                              statement="本框架的 gate 判别力普遍不足")
    r = _run(["report", "--reliability", relp, "--outdir", str(tmp_path)])
    assert r.returncode == 4, r.stderr


# ---------------------------------------------------------------- 干净文本必须放行
def test_report_clean_text_still_passes(tmp_path):
    """反向守卫：不得因接线过严而误杀合规报告（这条保证修复不破坏可用性）。"""
    relp = _write_reliability(str(tmp_path / "reliability.csv"))
    r = _run(["report", "--reliability", relp, "--outdir", str(tmp_path)])
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "conclusions.md").exists()


# ---------------------------------------------------------------- 红线 5
def test_REDLINE_5_unknown_profile_rejected():
    """REDLINE-5：非法合规档位 → 非零退出（不得静默按默认档跑）。"""
    r = _run(["release-check", "--profile", "bogus-profile"])
    assert r.returncode != 0


# ---------------------------------------------------------------- 红线 2 / 4
def _write_measurements(path, endpoints, n_comp=3, sources=("admet_ai", "vnn")):
    """sources 默认取**跨独立方法组**（descriptor_ml + dl_atomwise）：
    若取同组两源，独立票只有 1，裁决会因"单组"直接 UNDETERMINED，
    从而掩盖红线 4（tier 降级）是否真的生效——测试必须能区分这两条路径。"""
    cols = ["compound_id", "endpoint", "value", "unit", "source", "source_version",
            "retrieved_at", "domain_flag", "uncertainty", "provenance_url", "note"]
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with io.open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for i in range(n_comp):
            for ep, val in endpoints:
                for src in sources:
                    w.writerow(dict(compound_id="C%d" % i, endpoint=ep,
                                    value=val, unit="probability", source=src,
                                    domain_flag="predicted", retrieved_at="2026-01-01T00:00:00"))
    return path


def test_REDLINE_2_small_sample_banner(tmp_path):
    """REDLINE-2：n<10 时 verdict 命令必须打定性横幅。"""
    mp = _write_measurements(str(tmp_path / "measurements.csv"),
                             [("herg", 0.1)], n_comp=3)
    r = _run(["reliab", "--in", mp, "--outdir", str(tmp_path)])
    assert r.returncode == 0, r.stderr
    assert "红线2" in (r.stdout + r.stderr)


def _write_compounds(path, n_comp=3, smiles="CCO"):
    cols = ["compound_id", "input_smiles", "calc_smiles", "state_flag",
            "formula", "inchikey", "mw", "clogp",
            "hard_gate_problems", "state_sensitive", "note"]
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with io.open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for i in range(n_comp):
            w.writerow(dict(compound_id="C%d" % i, input_smiles=smiles,
                            calc_smiles=smiles, state_flag="neutral",
                            formula="C2H6O", inchikey="LFQSCWFLJHTTHZ-UHFFFAOYSA-N",
                            mw=46.07, clogp=-0.31))
    return path


def test_REDLINE_4_low_validity_endpoint_downgraded(tmp_path):
    """REDLINE-4：DILI 无 --i-accept-low-validity 时默认降为 UNDETERMINED 且留痕。

    需要 compounds.csv 让专家规则层（ich M7 双方法）介入，否则 DILI 在
    双方法缺失时本就 UNDETERMINED，tier 降级不会留下 tier_log（会掩盖红线）。
    """
    mp = _write_measurements(str(tmp_path / "measurements.csv"),
                             [("dili", 0.9)], n_comp=40)
    cp = _write_compounds(str(tmp_path / "compounds.csv"), n_comp=40)
    r = _run(["reliab", "--in", mp, "--outdir", str(tmp_path), "--compounds", cp])
    assert r.returncode == 0, r.stderr
    blocks = tmp_path / "endpoint_tier_blocks.csv"
    assert blocks.exists(), r.stdout + r.stderr
    txt = io.open(str(blocks), encoding="utf-8-sig").read()
    assert "UNDETERMINED" in txt
