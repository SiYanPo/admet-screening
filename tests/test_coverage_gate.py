# -*- coding: utf-8 -*-
"""未覆盖端点强制声明闸门（C82 闭环）回归测试。

C82 的教训是「登记表写了但没接线」，因此这里**必须有一条 e2e**：
改 registry → 跑 CLI → 看产物是否变。只测函数不算闭环。
"""
import io
import json
import os
import re
import subprocess
import sys

import pytest
import yaml

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RULES = os.path.join(HERE, "references", "03_endpoint_rules.yaml")


def _cg():
    from adt import coverage_gate
    return coverage_gate


def test_load_not_covered_is_valid_and_cwd_independent(tmp_path, monkeypatch):
    CG = _cg()
    entries = CG.load_not_covered()
    assert len(entries) >= 2
    ids = [e["id"] for e in entries]
    assert len(ids) == len(set(ids))
    assert {"cyp_induction", "cyp_tdi"} <= set(ids)
    for e in entries:
        assert e["status"] in CG.VALID_STATUS
        assert e["label"] and e["reason"] and e["required_evidence"]
    # 换 cwd 仍可读（相对路径会在这里暴露）
    monkeypatch.chdir(str(tmp_path))
    assert [e["id"] for e in CG.load_not_covered()] == ids


def test_declaration_is_complete_and_deterministic():
    CG = _cg()
    entries = CG.load_not_covered()
    text = CG.declaration_text(entries)
    for e in entries:
        assert CG.marker(e["id"]) in text
    assert CG.declaration_text(entries) == text
    # 无动态时间戳（正文里的 2026-11-11 是登记文字，不是运行时生成值）
    assert "generated_at" not in text
    assert not re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", text)


def test_verify_declaration_positive_negative_and_no_false_positive():
    CG = _cg()
    entries = CG.load_not_covered()
    good = CG.verify_declaration(CG.declaration_text(entries), entries)
    assert good["applicable"] is True and good["passed"] is True

    method = "本段只描述 Gate 0.5 的结构准入流程，不涉及具体端点结论。"
    na = CG.verify_declaration(method, entries)
    assert na["applicable"] is False and na["passed"] is True   # 不误伤

    bad = "CYP3A4 抑制两源一致，未见 DDI 风险，可判定安全。"
    fail = CG.verify_declaration(bad, entries)
    assert fail["passed"] is False and "cyp_tdi" in fail["missing"]

    removed = CG.declaration_text(entries).replace(CG.marker("cyp_tdi"), "")
    fail2 = CG.verify_declaration(removed + "\n" + bad, entries)
    assert fail2["passed"] is False and fail2["missing"] == ["cyp_tdi"]


def test_registry_change_changes_product_e2e(tmp_path):
    """C82 要求的形态：改 registry → 跑 CLI → 产物变化 + 校验能检出。"""
    CG = _cg()
    d = yaml.safe_load(io.open(RULES, encoding="utf-8"))
    d["not_covered_endpoints"] = [x for x in d["not_covered_endpoints"]
                                  if x["id"] != "cyp_tdi"]
    p = tmp_path / "rules_missing.yaml"
    p.write_text(yaml.safe_dump(d, allow_unicode=True, sort_keys=False), encoding="utf-8")

    r = subprocess.run([sys.executable, "-m", "adt.cli", "coverage-gate",
                        "--rules", str(p), "--emit"],
                       cwd=HERE, capture_output=True, text=True, encoding="utf-8",
                       timeout=120)
    assert r.returncode == 0, r.stderr
    assert CG.marker("cyp_tdi") not in r.stdout
    res = CG.verify_declaration(r.stdout, CG.load_not_covered())
    assert res["passed"] is False and res["missing"] == ["cyp_tdi"]


def test_audit_texts_does_not_flag_pure_methodology(tmp_path):
    CG = _cg()
    method = tmp_path / "method.md"
    method.write_text("只讲结构准入流程与 Gate 分层，不涉及端点结论。", encoding="utf-8")
    bad = tmp_path / "claim.md"
    bad.write_text("CYP3A4 抑制一致，未见 DDI 风险。", encoding="utf-8")
    res = CG.audit_texts([str(method), str(bad)])
    assert res["n_scanned"] == 2
    assert res["n_applicable"] == 1
    assert res["n_violations"] == 1
    assert os.path.basename(res["violations"][0]["file"]) == "claim.md"


def test_report_wiring_appends_declaration(tmp_path):
    """生产链路接线：report 无条件并入声明，且不被红线拦截。"""
    CG = _cg()
    rel = os.path.join(HERE, "out_wbh", "reliability.csv")
    if not os.path.isfile(rel):
        pytest.skip("out_wbh/reliability.csv 不存在（重跑主链路后本例生效）")
    out = tmp_path / "report_out"
    # conftest 把 tmp_path 覆盖为「不删除的 scratch 目录」，重跑时目录已存在；
    # 且必须先清掉上一次的 conclusions.md，否则 report 失败时旧产物会造成假绿。
    out.mkdir(exist_ok=True)
    stale = out / "conclusions.md"
    if stale.exists():
        stale.unlink()
    r = subprocess.run([sys.executable, "-m", "adt.cli", "report",
                        "--reliability", rel, "--outdir", str(out)],
                       cwd=HERE, capture_output=True, text=True, encoding="utf-8",
                       timeout=180)
    assert r.returncode == 0, "stdout=%s\nstderr=%s" % (r.stdout, r.stderr)
    body = (out / "conclusions.md").read_text(encoding="utf-8")
    for e in CG.load_not_covered():
        assert CG.marker(e["id"]) in body
    assert CG.verify_declaration(body, CG.load_not_covered())["passed"] is True


def test_claims_audit_cli_positive_and_negative(tmp_path):
    CG = _cg()
    decl = tmp_path / "ok.md"
    decl.write_text(CG.declaration_text(CG.load_not_covered())
                    + "\nCYP3A4 抑制一致，未见 DDI 风险。", encoding="utf-8")
    bad = tmp_path / "bad.md"
    bad.write_text("CYP3A4 抑制一致，未见 DDI 风险。", encoding="utf-8")
    base = [sys.executable, "-m", "adt.claims_audit", "--coverage-declaration",
            "--texts"]
    r1 = subprocess.run(base + [str(decl)], cwd=HERE, capture_output=True,
                        text=True, encoding="utf-8", timeout=120)
    r2 = subprocess.run(base + [str(bad)], cwd=HERE, capture_output=True,
                        text=True, encoding="utf-8", timeout=120)
    assert r1.returncode == 0, r1.stdout + r1.stderr
    assert r2.returncode == 1


def test_coverage_gate_selftest():
    assert _cg().selftest()["passed"] is True
