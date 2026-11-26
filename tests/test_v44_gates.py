# -*- coding: utf-8 -*-
"""v4.4 新增门禁的回归断言：G10 主张登记表 / G11 负结果默认配置 / G12 阈值冻结。

为什么要给门禁写测试：门禁代码本身也会坏。
门禁坏掉的表现是"静默通过"——它不报错，只是不再拦，这比没有门禁更危险
（因为大家以为它在看着）。所以三个门各配两类断言：
- **正常时通过**（防止门禁把自己做成永久红灯，那样会被整体关掉）；
- **构造坏数据时必须 red**（防止门禁被写成永远绿）。
"""
import io
import os
import shutil
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adt import claims_audit, defaults, release_gate, threshold_audit  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------- G10
class TestClaimsRegistry:
    def test_real_registry_passes(self):
        res = claims_audit.verify_registry(
            os.path.join(ROOT, "references", "CLAIMS_REGISTRY.yaml"))
        assert res["exists"]
        assert res["passed"], "登记表应全部通过；失败项：%s" % res["failures"]
        assert res["n_verified"] >= 15, "登记条目过少（%d），不足以覆盖数字主张" % res["n_verified"]

    def test_detects_missing_artifact(self, tmp_path):
        y = tmp_path / "reg.yaml"
        y.write_text(
            "meta: {rule: test}\n"
            "entries:\n"
            "  - id: ghost\n"
            "    kind: experiment\n"
            "    artifact: out_ext/__nope__.json\n"
            "    expect: ['0.5']\n", encoding="utf-8")
        res = claims_audit.verify_registry(str(y))
        assert not res["passed"]
        assert res["failures"][0]["why"] == "产物文件不存在"

    def test_detects_fabricated_number(self, tmp_path):
        art = tmp_path / "art.json"
        art.write_text('{"auc": 0.581}', encoding="utf-8")
        y = tmp_path / "reg.yaml"
        y.write_text(
            "meta: {rule: test}\n"
            "entries:\n"
            "  - id: fabricated\n"
            "    kind: experiment\n"
            "    artifact: %s\n"
            "    expect: ['0.999']\n" % str(art).replace("\\", "/"), encoding="utf-8")
        res = claims_audit.verify_registry(str(y))
        assert not res["passed"]
        assert "0.999" in res["failures"][0]["why"], "必须报出找不到的字面量"

    def test_rejects_code_artifact_for_experiment(self, tmp_path):
        py = tmp_path / "m.py"
        py.write_text("X = 0.5\n", encoding="utf-8")
        y = tmp_path / "reg.yaml"
        y.write_text(
            "meta: {rule: test}\n"
            "entries:\n"
            "  - id: code_as_experiment\n"
            "    kind: experiment\n"
            "    artifact: %s\n"
            "    expect: ['0.5']\n" % str(py).replace("\\", "/"), encoding="utf-8")
        res = claims_audit.verify_registry(str(y))
        assert not res["passed"]
        assert "不是数据文件" in res["failures"][0]["why"]


# ---------------------------------------------------------------- G11
class TestNegativeResultDefaults:
    def test_real_yaml_consistent(self):
        res = defaults.assert_consistent()
        assert res["ok"], "yaml 与代码默认值不一致：%s / %s" % (
            res["mismatches"], res["evidence_failures"])
        assert res["n_entries"] == len(defaults.DEFAULTS)

    def test_detects_code_drift(self, tmp_path, monkeypatch):
        # 构造：yaml 说 true，代码说 false → 必须被抓
        y = tmp_path / "d.yaml"
        y.write_text(
            "meta: {rule: test}\n"
            "defaults:\n"
            "  - key: ranking_enabled\n"
            "    default: true\n"
            "    evidence: {artifact: references/03_endpoint_rules.yaml, expect: ['desirability']}\n",
            encoding="utf-8")
        res = defaults.assert_consistent(str(y))
        assert not res["ok"]
        assert res["mismatches"][0]["key"] == "ranking_enabled"

    def test_detects_missing_evidence(self, tmp_path):
        y = tmp_path / "d.yaml"
        y.write_text(
            "meta: {rule: test}\n"
            "defaults:\n"
            "  - key: ranking_enabled\n"
            "    default: false\n"
            "    evidence: {artifact: out_ext/__nope__.json, expect: ['1']}\n",
            encoding="utf-8")
        res = defaults.assert_consistent(str(y))
        assert not res["ok"]
        assert res["evidence_failures"][0]["why"] == "产物不存在"


# ---------------------------------------------------------------- G12
class TestThresholdFreeze:
    def test_real_registry_no_drift(self):
        res = threshold_audit.audit()
        assert res["exists"]
        assert res["drift"] == [], "阈值漂移：%s" % res["drift"]
        assert res["n_thresholds"] >= 10
        # 分类普查必须齐全（U9 的 22 阈值普查靠这个填）
        assert set(res["census"]) >= {"literature", "calibrated", "ad_hoc"}

    def test_detects_drift(self, tmp_path):
        # 登记一个根本不存在的字面量 → 必须报漂移
        y = tmp_path / "t.yaml"
        y.write_text(
            "meta: {rule: test}\n"
            "thresholds:\n"
            "  - id: fake\n"
            "    value: 0.123456\n"
            "    value_token: '0.123456'\n"
            "    where: ['adt/guards.py']\n"
            "    provenance: ad_hoc\n"
            "    frozen: true\n"
            "    sensitivity: 'x'\n", encoding="utf-8")
        res = threshold_audit.audit(str(y))
        assert not res["passed"]
        assert res["drift"][0]["id"] == "fake"

    def test_flags_unfrozen_threshold(self):
        res = threshold_audit.audit()
        unfrozen = [g["id"] for g in res["gaps"] if g["kind"] == "not_frozen"]
        # ad_anchor 是**有意**不冻结的（数据里 0.35 附近无断点），必须被记录而非隐藏
        assert "ad_anchor" in unfrozen, (
            "ad_anchor 应保持 frozen=false 并出现在 gap 里；"
            "若被静默冻结，等于掩盖了『阈值无数据边界』这一事实")


# ---------------------------------------------------------------- 发布门禁整体
class TestReleaseGateWiring:
    def test_all_gates_present_and_pass(self):
        res = release_gate.check(ROOT)
        keys = [i["key"] for i in res["items"]]
        for k in ("G8_red_lines", "G10_claims_registry",
                  "G11_negative_result_defaults", "G12_threshold_freeze"):
            assert k in keys, "门禁 %s 未接线" % k
        assert res["passed"], "阻断项：%s" % res["blockers"]

    def test_red_line_count_is_nine(self):
        from adt import guards
        assert len(guards.red_lines_status()) == 9
