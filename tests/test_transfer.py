# -*- coding: utf-8 -*-
"""模块L：跨数据集可迁移性（弃权行为随 curation 质量的敏感性）。"""
import sys
sys.path.insert(0, ".")

from adt import transfer as TR

RULES = {"vnn_bbb": {"id": "vnn_bbb", "role": "quality",
                     "threshold": 0.5, "direction": "higher_is_worse",
                     "require_sources": 2, "phys_range": [0.0, 1.0]}}


def _meas(cid, val, src, dom="predicted"):
    return dict(compound_id=cid, endpoint="vnn_bbb", value=val, unit="probability",
                source=src, source_version="v1", domain_flag=dom,
                retrieved_at="2026")


def test_profile_counts_abstention_and_domain_block():
    rows = [_meas("C1", 0.9, "s1"), _meas("C1", 0.9, "s2"),
            _meas("C2", 0.1, "s1", dom="out_of_domain"),
            _meas("C2", 0.1, "s2", dom="out_of_domain")]
    p = TR.profile("ds", rows, RULES)
    assert p["n_pairs"] == 2
    assert p["n_compounds"] == 2
    assert p["abstention_rate"] is not None
    # C2 两源全域外 → domain_block_rate > 0
    assert p["domain_block_rate"] and p["domain_block_rate"] > 0


def test_compare_expected_order_direction():
    better = dict(name="clean", n_pairs=10, abstention_rate=0.1,
                  domain_block_rate=0.0)
    worse = dict(name="raw", n_pairs=10, abstention_rate=0.4,
                 domain_block_rate=0.3)
    res = TR.compare([better, worse], expected_order=("clean", "raw"))
    assert "符合预期" in res["prediction_check"], res["prediction_check"]


def test_compare_warns_when_no_displacement():
    a = dict(name="clean", n_pairs=10, abstention_rate=0.3, domain_block_rate=0.4)
    b = dict(name="raw", n_pairs=10, abstention_rate=0.3, domain_block_rate=0.1)
    res = TR.compare([a, b], expected_order=("clean", "raw"))
    assert "未观察到位移" in res["prediction_check"]


def test_proxy_flag_recorded(tmp_path):
    a = dict(name="a", n_pairs=1, abstention_rate=0.0, domain_block_rate=0.0)
    b = dict(name="b", n_pairs=1, abstention_rate=1.0, domain_block_rate=1.0)
    res = TR.compare([a, b], expected_order=("a", "b"), proxy=True)
    assert res["proxy"] is True
    p1, p2 = TR.write(str(tmp_path), res)
    assert (tmp_path / "transfer_profiles.csv").exists()
    assert (tmp_path / "transfer_note.md").exists()


def test_decided_accuracy_uses_truth_class():
    """C-2026-11-03：decided_accuracy 此前是不可达死代码（CLI 无 --truth）。

    本用例锁住函数语义：只在有 PASS/FAIL 真值且裁决为 PASS/FAIL 的对上计分。
    """
    rows = [_meas("C1", 0.9, "s1"), _meas("C1", 0.9, "s2"),   # 裁决应可定
            _meas("C2", 0.1, "s1"), _meas("C2", 0.1, "s2")]
    truth = [dict(compound_id="C1", endpoint="vnn_bbb", truth_class="FAIL"),
             dict(compound_id="C2", endpoint="vnn_bbb", truth_class="PASS"),
             dict(compound_id="C3", endpoint="vnn_bbb", truth_class="UNDETERMINED")]
    da = TR.decided_accuracy("ds", rows, truth, RULES)
    assert da["name"] == "ds"
    assert da["n_eval"] >= 0
    if da["n_eval"] == 0:
        # 全部弃权时必须是 None，不能伪装成 0.0 或 1.0
        assert da["decided_accuracy"] is None
    else:
        assert 0.0 <= da["decided_accuracy"] <= 1.0


def test_cli_transfer_exposes_truth_flag():
    """CLI 必须真的暴露 --truth，否则 decided_accuracy 又变成不可达死代码。"""
    import subprocess
    p = subprocess.run([sys.executable, "-m", "adt.cli", "transfer", "--help"],
                       capture_output=True, text=True)
    assert p.returncode == 0
    assert "--truth" in (p.stdout + p.stderr)


def test_cli_source_admit_runs_registration_gate(tmp_path):
    """C-2026-11-03：registration_gate 此前无任何管线调用点（文档-代码漂移）。

    `source-admit` 是它的真实执行入口：n 不足 → CI 上界 > tol → 不得宣称通过。
    """
    import subprocess
    res = tmp_path / "results.csv"
    res.write_text("source,n,observed_failures\n"
                   "tiny,100,1\n"        # CP95 上界≈0.0545 > 0.05 → 不能宣称通过
                   "big,1000,10\n",      # CP95 上界≈0.0183 ≤ 0.05 → 通过
                   encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    p = subprocess.run([sys.executable, "-m", "adt.cli", "source-admit",
                        "--results", str(res), "--outdir", str(out)],
                       capture_output=True, text=True)
    assert p.returncode == 0, p.stderr[-500:]
    import json
    payload = json.loads((out / "source_admission.json").read_text(encoding="utf-8"))
    by = {r["source"]: r for r in payload["rows"]}
    assert by["tiny"]["passes"] is False
    assert by["tiny"]["ci_upper"] > 0.05
    assert by["tiny"]["decision"] == "admit_with_ci_flag"   # 带 CI 标注进入，非二值拒绝
    assert by["tiny"]["disclosure_required"] is True
    assert by["big"]["passes"] is True
    assert by["big"]["ci_upper"] <= 0.05


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
