# -*- coding: utf-8 -*-
"""2026-11-17 同行评审整改回归：
  - G13 estimand 绑定门（C01 跨量纲撤回的可执行防复发）
  - 修复①：prereg.anchor_status 事后锚定不得放行 claim_allowed
  - 修复②：version --strict 台账登记 dynamic version 分歧（不伪造统一）
这些是"发现一个 bug 就补一个测试"的硬纪律，防止下次重构再悄悄退化。
"""
import io
import os
import subprocess
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _py(*args):
    return subprocess.run([sys.executable] + list(args), cwd=ROOT,
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace")


# ---------- G13 / estimand ----------
def test_estimand_selftest_passes():
    from adt import estimand as ES
    ok, rows = ES.selftest()
    assert ok, [r for r in rows if not r["ok"]]


def test_c01_cross_dimension_blocked():
    """C01 根因：AUC(0.5 基线) 与 always-positive(prevalence) 跨量纲比较必须拦。"""
    from adt import estimand as ES
    r = ES.check_comparison("auc", "always_positive_accuracy")
    assert r["verdict"] == "BLOCK"
    assert "跨量纲" in r["reason"]


def test_same_dimension_allowed():
    from adt import estimand as ES
    assert ES.check_comparison("accuracy", "always_positive_accuracy")["verdict"] == "ALLOW"


def test_herg_inferential_blocked_unbound():
    from adt import estimand as ES
    r = ES.check_claim("hERG", "域外没有排序能力", metric="auc")
    assert r["verdict"] == "BLOCK"
    assert r["estimand_status"] == "NOT_AN_ESTIMAND"


def test_descriptive_claim_not_blocked():
    """纯描述性报告（非推断）不应被 estimand 门误伤。"""
    from adt import estimand as ES
    r = ES.check_claim("hERG", "报告域内 AUC=0.580 及其 95% CI", metric="auc")
    assert r["verdict"] != "BLOCK"


def test_c01_text_detection():
    from adt import estimand as ES
    assert ES.validate_text("AUC 全部低于同批 always-positive accuracy")["verdict"] == "BLOCK"
    assert ES.validate_text("仅报告 AUC 及其 95% CI")["verdict"] == "ALLOW"


def test_g13_release_gate_wired():
    from adt import release_gate as RG
    items = {i["key"]: i for i in RG.check()["items"]}
    assert "G13_estimand_binding" in items
    assert items["G13_estimand_binding"]["ok"]


def test_estimand_card_shipped_in_data():
    """换机复现：estimand 卡必须在包内 _data/，否则 wheel 安装后 G13 直接 blocker。"""
    assert os.path.isfile(os.path.join(ROOT, "references", "ENDPOINT_ESTIMAND_CARDS.yaml"))
    assert os.path.isfile(os.path.join(ROOT, "adt", "_data", "ENDPOINT_ESTIMAND_CARDS.yaml"))


def test_cli_estimand_subcommand():
    r = _py("-m", "adt.cli", "estimand", "--selftest")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


# ---------- 修复①：prereg 事后锚定 ----------
def test_posthoc_anchor_cannot_grant_claim():
    from adt.prereg import Prereg
    p = Prereg(os.path.join(tempfile.mkdtemp(), "p.jsonl"))
    p.register_criteria("c1", {"x": 1})
    assert p.anchor_status()["claim_allowed"] is False
    p.attach_anchor({"registry": "OSF", "url": "https://osf.io/x",
                     "deposited_at": "2026-11-17"})
    s = p.anchor_status()
    assert s["post_hoc_anchor"] is True
    assert s["claim_allowed"] is False, "事后锚定不得授予已预注册资格（C01/C18）"


# ---------- 修复②：version 分歧台账 ----------
def test_version_strict_zero_undeclared():
    r = _py("-m", "adt.version", "--strict")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "未登记 0 条" in r.stdout


# ---------- 修复③：env-audit 退出码语义 ----------
# ---------- 修复④：G10 字段级证据链补全 ----------
def test_claims_field_evidence_coverage():
    """27 条主张：2 条撤回不算，其余 25 条必须全部结构化绑定（JSON 字段或代码 AST 符号）。"""
    from adt import claims_audit as C
    fa = C.verify_registry_fields()
    adm = fa["n_entries"] - fa["n_retracted"]
    assert fa["n_field_failed"] == 0, [r for r in fa["rows"] if r["field_match"] is False]
    assert fa["n_field_unresolved"] == 0, [r for r in fa["rows"] if r["field_match"] == "unresolved"]
    assert fa["n_field_matched"] == adm, (fa["n_field_matched"], adm)


def test_g10_gate_is_info_not_warn():
    from adt import release_gate as RG
    items = {i["key"]: i for i in RG.check()["items"]}
    g10 = items["G10_claims_registry"]
    assert g10["ok"] and g10["level"] == "info", g10


def test_binding_tool_is_deterministic():
    """绑定生成器对已绑定条目应为 ALREADY_BOUND/UNBOUND，不产生新的漂移。"""
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import importlib
    import bind_claim_fields as B
    importlib.reload(B)
    import yaml
    doc = yaml.safe_load(io.open(os.path.join(ROOT, "references", "CLAIMS_REGISTRY.yaml"),
                                 encoding="utf-8"))
    for e in doc["entries"]:
        if e.get("status") == "superseded" or e.get("admissible_for_external_use") is False:
            continue
        if e.get("kind") == "code":
            continue
        fp, why = B.bind_entry(e)
        # 已绑定的条目重新生成应通过 self-check（路径可不同，但必须可绑定）
        assert fp is not None, (e["id"], why)


# ---------- 修复⑤：红线探测嵌套抖动（内容指纹磁盘缓存）----------
def test_redline_probe_disk_cache():
    """真跑一次后应落盘内容指纹缓存；同内容重入不得再起 pytest（消除嵌套抖动）。"""
    from adt import redlines as RL
    root = ROOT
    fresh = RL._probe_freshness_key(root)
    cp = RL._cache_path(root, fresh)
    assert cp is not None
    # 触发一次真跑（若缓存已在则读盘，等价）
    r1 = RL._run_redline_tests(root)
    assert all(v[0] for v in r1.values()), r1
    assert os.path.isfile(cp), "内容指纹缓存未落盘：%s" % cp
    # 再读一次应命中缓存，结果一致
    r2 = RL._run_redline_tests(root)
    assert {k: v[0] for k, v in r1.items()} == {k: v[0] for k, v in r2.items()}


# ---------- 修复⑥：kNN 阈值敏感性欠账 ----------
def test_knn_sensitivity_selftest_and_real_data():
    from adt import knn_sensitivity as KS
    ok, ns = KS.selftest()
    assert ok and ns == sorted(ns, reverse=True), ns
    rep = KS.analyze(ROOT)
    assert set(rep["by_endpoint"]) == {"hERG", "DILI", "BBB_Martins"}
    for ep, per in rep["by_endpoint"].items():
        for gn, g in per.items():
            assert "verdict" in g and len(g["variants"]) == 6, (ep, gn)


def test_knn_sensitivity_cli():
    r = _py("-m", "adt.cli", "knn-sensitivity", "--selftest")
    assert r.returncode == 0, r.stdout + r.stderr


# ---------- 2026-11-19：三个 prior art 的移植模块 ----------
def test_trust_selftest():
    from adt import trust as T
    ok, rows = T.selftest()
    assert ok, [r for r in rows if not r["ok"]]


def test_trust_fixes_three_defects():
    """移植前必须修的 3 个 TRUST-ADMET 缺陷不能回退。"""
    from adt import trust as T
    # 缺陷1：共线信号（1-2|p-0.5|）不得计分
    d = T.trust_decision("CCO", probability=0.8,
                         independent_uncertainty=1 - 2 * abs(0.8 - 0.5))
    assert d["decision"] == "UNDETERMINED"
    # 缺陷2：模型级 ECE 不得充当逐样本校准信号
    d2 = T.trust_decision("CCO", probability=0.9,
                          independent_uncertainty=0.1, similarity=0.95)
    assert d2["calibration_signal"] == "model_level_only_not_counted"
    assert "calibration" not in d2["score_breakdown"]
    # 缺陷3：无效结构硬拒答（不静默零特征）
    d3 = T.trust_decision("NOT_SMILES",
                          physchem=dict(valid=False, violations=["INVALID_STRUCTURE"],
                                        action="REFUSED"))
    assert d3["trust_level"] == "REFUSED"


def test_numeric_coverage_fidelity_gate():
    from adt import trust as T
    assert T.numeric_coverage([10.5], "cost 10.5")["verdict"] == "PASS"
    assert T.numeric_coverage([77.7], "cost 10.5")["verdict"] != "PASS"


def test_prereg_criterion_failure_report():
    from adt import trust as T
    r = T.prereg_criterion_report(dict(id="P1", threshold=-2.0, direction="<="),
                                  dict(value=-1.7), dict(value=2.0))
    assert r["primary"]["met"] is False
    assert r["primary"]["effect_within_noise_floor"] is True
    assert "未达成" in r["citation_ready_text"]


def test_claim_fragility_census():
    from adt import claims_audit as C
    rows = C.fragility_census()
    assert len(rows) == 27
    cats = {r["category"] for r in rows}
    assert "retracted" in cats and "supported" in cats
    assert all(r["human_confirmation_required"] for r in rows), \
        "SciForge 移植纪律：分类须人确认，不做自动判定"


def test_manifest_git_commit_field():
    """TRUST-ADMET 移植：manifest 必须有 git_commit 字段（可为 null，不伪造）。"""
    from adt import manifest as M
    d = tempfile.mkdtemp()
    M.write_manifest(d, argv=["test"])
    txt = io.open(os.path.join(d, "run_manifest.yaml"), encoding="utf-8").read()
    assert "git_commit:" in txt and "git_rev_status:" in txt


# ---------- 2026-11-19：100 篇精读移植 ----------
def test_evidence_streams_selftest():
    from adt import evidence_streams as ES
    ok, rows = ES.selftest()
    assert ok, [r for r in rows if not r["ok"]]


def test_evidence_streams_small_n_escalates():
    from adt import evidence_streams as ES
    r = ES.complementarity([0.1, 0.2], [0.3, 0.4])
    assert r["verdict"] == "INDETERMINATE" and r["human_confirmation_required"]


def test_silent_failure_selftest():
    from adt import silent_failure as SF
    ok, rows = SF.selftest()
    assert ok, [r for r in rows if not r["ok"]]


def test_silent_failure_overconfidence_alarm():
    from adt import silent_failure as SF
    r = SF.silent_failure_rate([0.95] * 20, [True] * 5 + [False] * 15)
    assert r["verdict"] == "ALARM" and r["silent_failure_rate"] == 0.75


def test_perm_contribution_selftest():
    from adt import perm_contribution as PC
    ok, rows = PC.selftest()
    assert ok, [r for r in rows if not r["ok"]]


# ---------- 2026-11-19：技能市场 100 skill 移植 ----------
def test_advisory_warning_separate_from_hard_contract():
    """回归：uncertainty 告警不得混入 validate()（曾导致长表写入被整批拒绝）。"""
    from adt import schema as S
    r = dict(compound_id="C1", endpoint="hERG", domain_flag="predicted",
             value=0.8, provenance_url="x")
    assert S.validate([r]) == [], "软告警不得进硬契约"
    assert len(S.advisory_warnings([r])) == 1


def test_market_modules_selftests():
    for mod in ("deviation", "retrieval_card", "power_analysis"):
        import importlib
        m = importlib.import_module("adt." + mod)
        ok, rows = m.selftest()
        assert ok, (mod, [r for r in rows if not r["ok"]])


def test_power_matches_scipy_independent():
    """外部核验：required_n 必须与独立正态近似公式一致（防止自验证共同盲点）。"""
    import math
    from adt.power_analysis import required_n
    from scipy.stats import norm
    for p1, p2 in ((0.5, 0.7), (0.1, 0.2), (0.5, 0.55)):
        r = required_n(p1, p2)
        pbar, d = (p1 + p2) / 2, abs(p1 - p2)
        ref = ((norm.ppf(0.975) * math.sqrt(2 * pbar * (1 - pbar)) +
                norm.ppf(0.8) * math.sqrt(p1 * (1 - p1) + p2 * (1 - p2))) ** 2) / d ** 2
        assert r["required_n_per_group"] == math.ceil(ref), (p1, p2, r, ref)


def test_deviation_transition_guard():
    from adt import deviation as D
    assert D.transition("pending_investigation", "closed")["ok"] is False
    assert D.transition("attributed", "closed")["ok"] is True
    assert D.detect([1, 2, 3], spec_lo=0, spec_hi=10)["verdict"] == "IN_CONTROL"


def test_retrieval_card_tamper():
    from adt import retrieval_card as RC
    c = RC.make_card("q", ["PubMed"], depth="audit")
    assert RC.verify_card(c)["ok"]
    bad = dict(c, query="q2")
    assert RC.verify_card(bad)["ok"] is False


# ---- 代码审查 Blocker 的永久回归（selftest 曾漏检，必须固化）----
def test_pvalue_matches_scipy_small_n():
    """B1 回归：t 分布双尾 p 的 df 必须是 n-2（曾有 df 错配，小 n 时低估 34%）。"""
    import math
    from adt.evidence_streams import _p_two_sided
    from scipy import stats
    for n in (5, 10, 20):
        for r in (0.2, 0.5, 0.8):
            got = _p_two_sided(r, n)
            t = abs(r) * math.sqrt((n - 2) / (1 - r * r))
            exp = 2 * stats.t.sf(t, n - 2)
            assert got is not None and abs(got - exp) < 1e-10, (n, r, got, exp)


def test_holm_alignment_not_inverted():
    """B2 回归：batch_contribution 必须按 holm 返回的 idx 回填，不得 zip 顺序。"""
    import random
    from adt import perm_contribution as PC
    rng = random.Random(11)
    n = 40
    feats, labs = [], []
    for i in range(n):
        s = 1 if i % 2 == 0 else 0
        feats.append([s, rng.random()])
        labs.append(s)

    def acc(F, y):
        return sum(1 for r, v in zip(F, y) if (1 if r[0] >= 0.5 else 0) == v) / len(y)

    rows = PC.batch_contribution(acc, feats, labs,
                                 {"noise": 1, "signals": 0}, n_perm=60)
    by = {r["component"]: r for r in rows}
    assert by["signals"]["reject_holm"] is True, by["signals"]
    assert by["noise"]["reject_holm"] is False, by["noise"]


def test_significance_gate():
    from adt import claims_audit as C
    # 数值改善但不显著 → FRAGILE（PMID 42734510）
    r = C.significance_gate(effect=0.05, ci=(-0.01, 0.11), p=0.12)
    assert r["verdict"] == "FRAGILE" and "不得写成有效" in r["reason"]
    # 无区间无 p → INDETERMINATE（红线6）
    r2 = C.significance_gate(effect=0.05)
    assert r2["verdict"] == "INDETERMINATE"
    # 显著且区间不跨 0 → SUPPORTED
    r3 = C.significance_gate(effect=0.2, ci=(0.1, 0.3), p=0.001)
    assert r3["verdict"] == "SUPPORTED"


def test_env_audit_exit_code_semantics():
    """默认 0/1/2 语义不变；--required-only 在必需层全绿时把 2 归一为 0。"""
    from adt import env_audit as EA
    rep = EA.build_report()
    req_ok = not rep["summary"]["required_missing"]
    if not req_ok:
        pytest.skip("本机必需层不全绿，跳过进程码归一测试")
    # 直接模块入口，避免 CLI 层干扰
    r = _py("-m", "adt.env_audit", "--quiet")
    r2 = _py("-m", "adt.env_audit", "--quiet", "--required-only")
    assert r.returncode in (0, 2)
    assert r2.returncode == 0, r2.stdout + r2.stderr
    if r.returncode == 2:
        assert "进程码 2→0" in r2.stdout


# ---- 2026-11-19 竞审 Blocker/Warning 的永久回归（selftest 曾漏检）----
def test_deviation_oot_baseline_excludes_tail():
    """B1：不给 history 时基线必须取前段；整段自基线会把尾部算进去而系统性漏报。"""
    from adt import deviation as D
    import random
    rng = random.Random(7)
    base = [round(10 + rng.uniform(-0.05, 0.05), 4) for _ in range(40)]
    series = base + [12.0] * 10
    no_hist = D.detect(series, spec_lo=0, spec_hi=100)
    with_hist = D.detect(series, spec_lo=0, spec_hi=100, history=base)
    assert with_hist["verdict"] == "OOT"
    assert no_hist["verdict"] == "OOT", "同一序列不给 history 时不得因自基线而漏报"
    assert no_hist["baseline"]["source"] == "series_prefix"


def test_deviation_nonfinite_is_invalid_data():
    """W1：NaN/Inf 不得被静默判为 IN_CONTROL。"""
    from adt import deviation as D
    for s in ([10.0, float("nan")] * 5, [10.0] * 20 + [float("inf")]):
        r = D.detect(s, spec_lo=0, spec_hi=100)
        assert r["verdict"] == "INVALID_DATA" and r["human_confirmation_required"]
    r2 = D.detect([11.0] * 5, spec_lo=0, spec_hi=100,
                  history=[10.0] * 20 + [float("nan")])
    assert r2["verdict"] == "INVALID_DATA"


def test_deviation_oot_guard_params():
    """n_consecutive<=0 / oot_k<=0 不得产生假阳性。"""
    from adt import deviation as D
    hist = [10.0 + (i % 3) * 0.01 for i in range(30)]
    series = hist + [11.0, 11.05, 11.02, 11.08, 11.03]
    assert D.detect(series, history=hist, spec_lo=0, spec_hi=100,
                    n_consecutive=0)["oot"] is None
    assert D.detect(series, history=hist, spec_lo=0, spec_hi=100,
                    oot_k=-1.0)["oot"] is None


def test_power_input_validation_regression():
    """W2/W3：alpha 越界、rounding 非法必须显式拒绝，而不是产出貌似合理的数字。"""
    from adt import power_analysis as PA
    for bad in (0, 1, -0.1, 1.5):
        with pytest.raises(ValueError):
            PA.achieved_power(0.5, 0.7, 100, alpha=bad)
    with pytest.raises(ValueError):
        PA.required_n(0.5, 0.7, rounding="floor")
    assert PA.achieved_power(0.5, 0.7, 100, alpha=0.05)["verdict"] == "OK"


def test_retrieval_card_rejects_string_sources():
    """W4：字符串 sources 会被逐字符拆分，必须拒绝。"""
    from adt import retrieval_card as RC
    with pytest.raises(ValueError):
        RC.make_card("q", "PubMed")
    c = RC.make_card("q", ["PubMed"])
    assert RC.verify_card(c)["ok"]
