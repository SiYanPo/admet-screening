# -*- coding: utf-8 -*-
"""C11 / C1-a（2026-11-04）：写入端强校验回归锁。

报告要求的四类坏输入必须「全部被拒且不落盘」：
  out_of_domain 带值 / 缺 compound_id / 同键不同 unit / 未登记列名。
另加 metabolites 必需字段、validate 返回码、以及「所有生产入口已切换」的静态锁。
"""
from __future__ import annotations

import io
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adt import schema                       # noqa: E402
from adt import cli as CLI                   # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _good(**kw):
    r = dict(compound_id="C1", endpoint="herg", value="1.2", unit="uM",
             source="s1", source_version="v1", domain_flag="predicted",
             provenance_url="", note="")
    r.update(kw)
    return r


def _assert_rejected(tmp_path, rows, name):
    out = str(tmp_path / name)
    # conftest 的 tmp_path 是复用、不删除的 scratch 目录；必须先清掉上次残留，
    # 否则「文件不存在」断言会因历史产物假失败（2026-11-04 实跑踩过）。
    if os.path.exists(out):
        os.remove(out)
    with pytest.raises(schema.ContractViolation):
        schema.write_measurements_checked(out, rows)
    assert not os.path.exists(out), "坏数据仍落盘了：%s" % out


def test_out_of_domain_with_value_rejected(tmp_path):
    _assert_rejected(tmp_path, [_good(domain_flag="out_of_domain")], "a.csv")


def test_missing_compound_id_rejected(tmp_path):
    _assert_rejected(tmp_path, [_good(compound_id="")], "b.csv")


def test_same_key_different_unit_rejected(tmp_path):
    rows = [_good(), _good(value="2.0", unit="nM")]
    _assert_rejected(tmp_path, rows, "c.csv")


def test_unregistered_column_rejected(tmp_path):
    rows = [_good(gate_as_classifier_auc="0.71")]
    _assert_rejected(tmp_path, rows, "d.csv")


def test_metabolites_required_fields(tmp_path):
    out = str(tmp_path / "m.csv")
    if os.path.exists(out):
        os.remove(out)
    with pytest.raises(schema.ContractViolation):
        schema.write_metabolites_checked(out, [dict(compound_id="C1")])
    assert not os.path.exists(out)
    n = schema.write_metabolites_checked(out, [
        dict(compound_id="C1", metabolite_smiles="CCO", source="bt")])
    assert n == 1 and os.path.exists(out)


def test_good_rows_still_write(tmp_path):
    out = str(tmp_path / "ok.csv")
    n = schema.write_measurements_checked(out, [_good(), _good(compound_id="C2")])
    assert n == 2 and len(schema.read_measurements(out)) == 2


def test_validate_returns_nonzero_on_bad_contract(tmp_path, capsys):
    p = str(tmp_path / "bad.csv")
    # 直接写坏长表（绕过写入端），模拟外部数据进入 validate 子命令
    import csv
    with io.open(p, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=schema.MEASUREMENT_COLS)
        w.writeheader()
        w.writerow(_good(domain_flag="out_of_domain"))

    class A:
        input = p
    with pytest.raises(SystemExit) as e:
        CLI.cmd_validate(A())
    assert e.value.code == 3

    p2 = str(tmp_path / "good.csv")
    schema.write_measurements_checked(p2, [_good()])

    class B:
        input = p2
    assert CLI.cmd_validate(B()) == 0
    assert not os.path.exists(str(tmp_path / "measurements_validated.csv"))


def _write_csv(path, rows):
    import csv
    with io.open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=schema.MEASUREMENT_COLS)
        w.writeheader()
        for r in rows:
            w.writerow(r)


class _MergeArgs:
    def __init__(self, inputs, outdir, allow_invalid=False):
        self.inputs = inputs
        self.outdir = outdir
        self.allow_invalid = allow_invalid
        self.keep_dup = False


def test_merge_missing_source_version_exits_3(tmp_path):
    """C1-b：缺版本即 exit 3，且不落盘（含 run_manifest.yaml）。"""
    p = str(tmp_path / "in.csv")
    _write_csv(p, [_good(source_version="")])
    out = str(tmp_path / "out")
    with pytest.raises(SystemExit) as e:
        CLI.cmd_merge(_MergeArgs([p], out))
    assert e.value.code == 3
    assert not os.path.exists(out) or not os.listdir(out)


def test_merge_unit_part_of_dedup_key(tmp_path):
    """C1-b：异量纲两行不得被当作重复静默丢掉。

    严格模式下写入端会因 unit 冲突明确拒绝（C1-a 四类坏输入之一）；
    --allow-invalid 下则应保留 2 行，证明去重键确实含 unit。
    """
    p = str(tmp_path / "in.csv")
    _write_csv(p, [_good(), _good(value="2.0", unit="nM")])
    out_strict = str(tmp_path / "strict")
    with pytest.raises(schema.ContractViolation):
        CLI.cmd_merge(_MergeArgs([p], out_strict))
    assert not os.path.exists(os.path.join(out_strict, "measurements_merged.csv"))

    out_loose = str(tmp_path / "loose")
    CLI.cmd_merge(_MergeArgs([p], out_loose, allow_invalid=True))
    merged = schema.read_measurements(
        os.path.join(out_loose, "measurements_merged.csv"))
    assert len(merged) == 2, "unit 未进入去重键，第二条被静默丢弃"
    assert {r["unit"] for r in merged} == {"uM", "nM"}


def test_manifest_four_tuple_and_content_hash(tmp_path):
    """C2-a：真 manifest.json 四元组；内容哈希排除时间戳；prev_hash 成链。"""
    import json as _json
    from adt import manifest as M
    inp = str(tmp_path / "in.csv")
    _write_csv(inp, [_good()])
    out = str(tmp_path / "out")
    argv = ["python", "-m", "adt.cli", "validate"]
    M.write_manifest(out, inputs=[inp], argv=argv)
    m1 = _json.load(io.open(os.path.join(out, "manifest.json"), encoding="utf-8"))
    M.write_manifest(out, inputs=[inp], argv=argv)
    m2 = _json.load(io.open(os.path.join(out, "manifest.json"), encoding="utf-8"))

    for k in ("command", "script_sha256", "data_sha256", "env_digest",
              "estimand_id", "prev_hash", "content_sha256", "generated_at"):
        assert k in m1, k
    assert m1["content_sha256"] == m2["content_sha256"], \
        "同一输入两次运行内容哈希必须相同（时间戳/链字段未排除干净）"
    assert M.content_hash(m1) == m1["content_sha256"]
    assert m2["prev_hash"] == m1["content_sha256"], "prev_hash 必须指向上一条内容哈希"
    assert len(m1["script_sha256"]) == 64 and len(m1["env_digest"]) == 64
    assert m1["data_sha256"][0]["sha256"] == M._sha256_file(inp)
    assert {"generated_at", "prev_hash", "content_sha256"} <= M.CONTENT_HASH_EXCLUDE
    # 人为改时间戳/链字段，内容哈希仍不变（排除表真的生效）
    probe = dict(m1, generated_at="1999-01-01T00:00:00", prev_hash="FORGED")
    assert M.content_hash(probe) == m1["content_sha256"]
    # 改四元组任一分量，内容哈希必须变化（否则哈希没覆盖证据）
    probe2 = dict(m1, env_digest="0" * 64)
    assert M.content_hash(probe2) != m1["content_sha256"]


def test_claims_field_audit_rejects_sentence_only_number(tmp_path):
    """C3 / 外审 C V5：数字只出现在自然语言句子里，字段级比对必须判 FAIL。"""
    import json as _json
    import yaml
    from adt import claims_audit as CA
    art = tmp_path / "art.json"
    art.write_text(_json.dumps({
        "sentence_zh": "本轮 AUC 达到 0.9876，效果显著优于基线，结论明确。",
        "metrics": {"auc": 0.5},
    }, ensure_ascii=False), encoding="utf-8")
    reg = tmp_path / "reg.yaml"
    with io.open(str(reg), "w", encoding="utf-8") as f:
        yaml.safe_dump({"meta": {}, "entries": [{
            "id": "fake_sentence_claim", "claim": "x", "kind": "experiment",
            "artifact": str(art), "expect": ["0.9876"],
            "expect_field_path": "metrics.auc",
        }]}, f, allow_unicode=True)
    fa = CA.verify_registry_fields(str(reg))
    assert fa["n_field_failed"] == 1 and not fa["passed"]
    assert "0.9876" in fa["rows"][0]["missing"]
    strict = CA.verify_registry(str(reg), strict_fields=True)
    assert any("字段级比对失败" in x["why"] for x in strict["failures"])


def test_claims_registry_all_fields_present_and_honest():
    """27 条全部补齐四元组字段，但 unresolved 不得被伪装成已绑定证据。"""
    import yaml
    from adt import claims_audit as CA
    d = yaml.safe_load(io.open(os.path.join(ROOT, "references",
                                            "CLAIMS_REGISTRY.yaml"), encoding="utf-8"))
    assert len(d["entries"]) == 27
    for k in ("command", "command_status", "script_sha256", "input_sha256",
              "env_digest", "expect_field_path", "evidence_grade"):
        assert all(k in e for e in d["entries"]), k
    fa = CA.verify_registry_fields()
    assert fa["n_entries"] == 27
    # 2026-11-06 F1/S1a：indifference_curve（R4·C18 会计恒等式）补登记
    # status: superseded，与 external_cuts_headline（C01）并列。撤回条目必须
    # 从 field_unresolved 移到 retracted —— 这是更严格的分类，不是放宽验收。
    assert fa["n_retracted"] == 2
    # 2026-11-22：字段绑定已补齐（25/27 structured），旧断言 25 unresolved 已过期。
    # 保留"unresolved 不得伪装成证据"的原意，但按当前真实状态断言。
    assert fa["n_field_unresolved"] == 0
    assert fa["n_field_matched"] == 25
    assert fa["n_field_failed"] == 0
    cmds = CA.check_commands()
    assert cmds["n_bound"] == 25 and cmds["n_unresolved"] == 2
    assert cmds["n_broken"] == 0
    r = CA.verify_registry("references/CLAIMS_REGISTRY.yaml",
                           strict_fields=True)
    assert r["passed"] and r["n_entries"] == 27


def test_version_divergences_all_declared():
    """C2-c：四轨分歧必须全部登记，不许靠改数字假统一。"""
    from adt import version as V
    r = V.audit_version_sources()
    assert r["n_sources"] == 4
    assert r["n_divergences"] == 6, r["divergences"]
    assert r["undeclared"] == [], r["undeclared"]
    assert r["status"] == "known_divergence_pending_external_anchor"
    assert "4.0-dev" in r["observed"]["SKILL.md::version"]
    assert V.main(["--strict"]) == 0


def test_ci_executes_release_check_and_covers_windows_py313():
    """外审 C V4：CI 必须真正执行 release-check，且覆盖交付平台。"""
    import yaml
    p = os.path.join(ROOT, ".github", "workflows", "ci.yml")
    d = yaml.safe_load(io.open(p, encoding="utf-8"))
    jobs = d.get("jobs") or {}
    assert "release-gate" in jobs
    body = yaml.safe_dump(jobs["release-gate"], allow_unicode=True)
    assert "release-check" in body and "continue-on-error" not in body
    m = (jobs["unit"].get("strategy") or {}).get("matrix") or {}
    assert "windows-latest" in m.get("os", []), m
    assert "3.13" in [str(x) for x in m.get("python-version", [])], m


def test_endpoint_no_substring_fallback():
    """C1-c：未登记端点不得静默借用同前缀规则。"""
    from adt import endpoints as E
    rules = {"herg": {"shape": "down"}}
    assert E.match_rule("herg_blocking_ic50_v2", rules)[1] == "unmapped_endpoint"
    assert E.match_rule("bbb_martins", {"bbb": {"shape": "up"}})[1] == \
        "unmapped_endpoint"
    # 显式降级通道仍可用（历史迁移），但必须留痕
    assert E.match_rule("herg_blocking_ic50_v2", rules,
                        allow_substring=True)[1] == "substring"
    # 真实别名表命中（33 条，hERG -> herg）
    assert E.match_rule("hERG", rules)[1] == "alias"
    assert E.match_rule("herg", rules)[1] == "exact"


def test_rule_direction_audit_and_ledger():
    """静态校验器抓出 4 个真实冲突，且全部已登记；不允许有漏登记的新冲突。"""
    from adt import endpoints as E
    probs = E.validate_rule_direction()
    assert len(probs) == 4, probs
    assert all(x.startswith("[LEDGER:") for x in probs), probs
    assert E.unacknowledged_rule_problems() == []
    assert {x.split("]")[0].split(":")[1] for x in probs} == \
        {"herg", "dili", "ames", "mmp"}

    # 合成坏规则表：方向反、window 不包、重复 id —— 校验器必须逐条抓出
    import yaml
    p = str(tmp_path_fixture() / "bad_rules.yaml")
    with io.open(p, "w", encoding="utf-8") as f:
        yaml.safe_dump({"endpoints": [
            {"id": "fake_up", "shape": "up", "pass": 1, "fail": 9},
            {"id": "fake_down", "shape": "down", "pass": 9, "fail": 1},
            {"id": "fake_win", "shape": "window", "window": [3, -1],
             "soft": [-2, 4]},
            {"id": "fake_up", "shape": "up", "pass": 5, "fail": 2},
        ]}, f, allow_unicode=True)
    bad = E.validate_rule_direction(p)
    assert any("shape=up 但 pass" in x for x in bad), bad
    assert any("shape=down 但 fail" in x for x in bad), bad
    assert any("window" in x for x in bad), bad
    assert any("重复端点 id" in x for x in bad), bad
    assert all(not x.startswith("[LEDGER:") for x in bad), bad


def tmp_path_fixture():
    """scratch 目录（与 conftest 的 tmp_path 同口径），供模块级 helper 使用。"""
    from pathlib import Path
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     ".scratch", "endpoint_contract")
    os.makedirs(d, exist_ok=True)
    return Path(d)


def test_audit_unmapped_and_merge_report(tmp_path):
    from adt import endpoints as E
    u = E.audit_unmapped([{"compound_id": "C1",
                           "endpoint": "herg_blocking_ic50_v2"}])
    assert len(u) == 1 and u[0]["how"] == "unmapped_endpoint"
    assert "action" in u[0]

    p = str(tmp_path / "in.csv")
    _write_csv(p, [_good(endpoint="hERG"),
                   _good(compound_id="C2", endpoint="totally_unregistered_ep")])
    out = str(tmp_path / "out")
    CLI.cmd_merge(_MergeArgs([p], out))
    rep = os.path.join(out, "unmapped_endpoint_report.csv")
    assert os.path.isfile(rep)
    import csv as _csv
    rows = list(_csv.DictReader(io.open(rep, encoding="utf-8-sig")))
    assert len(rows) == 1, rows
    assert rows[0]["endpoint"] == "totally_unregistered_ep"
    assert rows[0]["how"] == "unmapped_endpoint"


def test_all_production_write_sites_are_checked():
    """静态锁：生产代码不得再出现裸 write_measurements/write_metabolites 调用。"""
    import ast
    bad = []
    for rel in ("adt/cli.py", "adt/external.py",
                "examples/admetlab_until_success.py", "examples/build_demo_long.py"):
        p = os.path.join(ROOT, rel)
        tree = ast.parse(io.open(p, encoding="utf-8").read(), filename=rel)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            if (isinstance(f, ast.Attribute)
                    and f.attr in ("write_measurements", "write_metabolites")
                    and isinstance(f.value, ast.Name) and f.value.id == "schema"):
                bad.append("%s:%d %s" % (rel, node.lineno, f.attr))
    assert bad == [], "仍有未切换的裸写入点：%s" % bad


# ---------------------------------------------------------------- 第 17/18 项
# C3：主张登记表必须有「命令 / 脚本哈希 / 输入哈希 / 环境摘要 / 期望字段路径」
# 五件套；字段级审计不得把 literal_only 冒充 structured。
def test_claims_registry_has_quadruple_fields():
    import yaml
    d = yaml.safe_load(io.open(os.path.join(
        ROOT, "references", "CLAIMS_REGISTRY.yaml"), encoding="utf-8"))
    ents = d["entries"]
    assert len(ents) == 27
    for k in ("command", "command_status", "script_sha256", "input_sha256",
              "env_digest", "expect_field_path", "evidence_grade"):
        missing = [e["id"] for e in ents if k not in e]
        assert missing == [], "字段 %s 缺失：%s" % (k, missing)
    # command 要么由代码证据绑定，要么显式 UNRESOLVED —— 不允许空串/编造
    for e in ents:
        if e["command_status"] == "bound_from_code":
            assert e["command"].startswith("python "), e
            assert e["script_sha256"], e
        else:
            assert e["command"] == "UNRESOLVED", e


def test_claims_field_audit_never_fakes_structured():
    """structured 只能来自真实 JSON 字段比对；unresolved 必须如实计数。"""
    from adt import claims_audit as CA
    r = CA.verify_registry_fields()
    assert r["n_entries"] == 27
    assert r["n_field_failed"] == 0, "存在字段级 mismatch"
    # 每条结果必须是四态之一，禁止出现 True 而实际未比对。
    # retracted = 已撤回主张（如 C01），必须排除出任何聚合 —— 撤回不是"通过"。
    for row in r["rows"]:
        assert row["field_match"] in (True, False, "unresolved", "retracted"), row
    if row["field_match"] == "retracted":
        assert row["evidence_grade"] == "retracted_no_evidence", row
    # 2026-11-22：字段绑定已补齐。当前真实状态是 25 matched / 0 unresolved /
    # 0 failed / 2 retracted；旧断言 0 matched 是当时的历史状态，已过期。
    # 仍禁止"True 但实际未比对"：上面的四态检查保留。
    assert r["n_field_matched"] == 25
    assert r["n_field_unresolved"] == 0
    assert r["n_field_failed"] == 0
    n_retr = sum(x["field_match"] == "retracted" for x in r["rows"])
    assert (r["n_field_unresolved"] + r["n_field_matched"]
            + r["n_field_failed"] + n_retr) == 27, (r["n_field_unresolved"], n_retr)


def test_release_gate_g10_level_matches_structured_evidence():
    """G10 级别必须与真实字段证据一致：literal_only>0 → warn；全 structured → info。"""
    from adt import release_gate as RG
    items = {i["key"]: i for i in RG.check(ROOT, include_dag=False)["items"]}
    g10 = items["G10_claims_registry"]
    assert g10["ok"] is True
    detail = g10["detail"]
    if "literal_only=0" in detail:
        assert g10["level"] == "info", g10
    else:
        assert g10["level"] == "warn", g10
    assert "structured=" in detail
