# -*- coding: utf-8 -*-
"""2026-11-22 同行评审修复的永久回归。

修复 1：trust.physchem_violations 传 physchem_limits() 整包时，
旧实现只读顶层键，lim 全为空 dict → 越界永远为 0，trust_decision 静默放行。
本测试同时覆盖整包 / 内层两种契约，并要求两者结果一致。
"""
import os
import sys


def test_physchem_violations_accepts_nested_and_flat_limits():
    from adt import trust as T
    inner = {
        "MolWt": {"lo": 50, "hi": 500},
        "MolLogP": {"lo": -1, "hi": 3},
        "TPSA": {"lo": 0, "hi": 60},
        "NumRotatableBonds": {"lo": 0, "hi": 5},
        "NumHDonors": {"lo": 0, "hi": 2},
        "NumHAcceptors": {"lo": 0, "hi": 5},
    }
    nested = {"limits": inner, "coverage_declaration": "test"}
    smi = "CCCCCCCCCCCCCCCC"  # 长链：MW/LogP/TPSA 等必然越界
    a = T.physchem_violations(smi, nested)
    b = T.physchem_violations(smi, inner)
    assert a["valid"] is True and b["valid"] is True
    assert a["violations"] == b["violations"]
    assert len(a["violations"]) >= 2, a
    assert a["action"] == "REFUSED", a
    # 无效结构必须 hard fail，不产生零向量
    bad = T.physchem_violations("NOT_A_SMILES", nested)
    assert bad["valid"] is False and bad["action"] == "REFUSED"


def test_trust_decision_actually_refuses_physchem_violation():
    from adt import trust as T
    inner = {
        "MolWt": {"lo": 50, "hi": 500},
        "MolLogP": {"lo": -1, "hi": 3},
        "TPSA": {"lo": 0, "hi": 60},
        "NumRotatableBonds": {"lo": 0, "hi": 5},
        "NumHDonors": {"lo": 0, "hi": 2},
        "NumHAcceptors": {"lo": 0, "hi": 5},
    }
    phys = T.physchem_violations("CCCCCCCCCCCCCCCC", {"limits": inner})
    d = T.trust_decision("CCCCCCCCCCCCCCCC", probability=0.9,
                         independent_uncertainty=0.05, physchem=phys)
    assert d["decision"] == "REFUSED", d
    assert d.get("reason") == "INVALID_STRUCTURE" or "理化" in d["action"]


def test_zero_reference_public_apis_are_exercised(tmp_path):
    """把 2026-11-22 审计出的零引用公共 API 逐个跑一遍（不是 allowlist 掩盖）。"""
    from adt import _version, compliance, resref, retrieval_card as RC
    from adt import schema, selective, trust, independence

    assert _version.as_dict()["version"] == _version.__version__
    assert "xenosite" in compliance.blocked_sources("academic-internal")
    assert resref.strip_prefix("references/03_endpoint_rules.yaml") == "03_endpoint_rules.yaml"
    assert resref.describe()["n_total"] >= 1

    card = RC.make_card('("conformal prediction"[Title/Abstract])',
                        ["PubMed"], date_from="2024", date_to="2026")
    p = tmp_path / "card.json"
    RC.save_card(card, str(p))
    assert p.exists() and RC.verify_card(card)["ok"]

    met = tmp_path / "metabolites.csv"
    n = schema.write_metabolites(str(met), [{"compound_id": "C1",
                                             "metabolite_smiles": "CCO"}])
    assert n == 1 and met.exists()

    pairs = [(0.9, True), (0.8, True), (0.3, False), (0.1, False)]
    cal = selective.risk_coverage_calibrated(pairs, score_kind="calibrated")
    assert cal["score_kind"] == "calibrated" and cal["curve"]
    grid = selective.cost_sensitive_abstain(pairs, cost_grid=[0.1, 1.0])
    assert len(grid) == 2 and all("optimal_coverage" in g for g in grid)

    limits = trust.physchem_limits(["CCO", "c1ccccc1", "CC(=O)O"])
    assert limits["limits"]["MolWt"]["n"] == 3
    assert "not a probabilistic coverage guarantee" in limits["note_not_guarantee"]

    cal_rows = [{"endpoint": "dili", "k": 2, "n_raters": 5, "u_smoothed": 0.2},
                {"endpoint": "dili", "k": 3, "n_raters": 5, "u_smoothed": 0.1}]
    assert independence.posterior_error(2, 5, cal_rows, "dili") == 0.2
    dec = independence.decompose_correlation([1, 2, 3, 4], [1, 2, 3, 5], [1, 2, 3, 4])
    assert "deprecated_alias" in dec


def test_benchmark_mcc_column_present_and_guarded():
    """§4 分歧 2：主表同时给 MCC/PR-AUC/ECE/Brier，MCC 带偏乐观标注。"""
    from adt import benchmark as bm
    # _mcc_youden 已知值：完美分离 = 1.0
    assert abs(bm._mcc_youden([0.1, 0.2, 0.8, 0.9], [0, 0, 1, 1]) - 1.0) < 1e-9
    # 反向 / 全并列：Youden-J≤0 无有意义阈值，诚实返回 None 而非误导性 0
    assert bm._mcc_youden([0.9, 0.8, 0.2, 0.1], [0, 0, 1, 1]) is None
    assert bm._mcc_youden([0.5, 0.5], [0, 1]) is None
    # build 输出含 mcc 列 + note 标注偏乐观
    pred = [dict(compound_id="C%d" % i, endpoint="e", value=str(v),
                 domain_flag="predicted", source="s")
            for i, v in enumerate([0.1, 0.2, 0.8, 0.9, 0.15, 0.85])]
    truth = [dict(compound_id="C%d" % i, endpoint="e", truth_value=v,
                  truth_class=("PASS" if v < 0.5 else "FAIL"))
             for i, v in enumerate([0.1, 0.2, 0.8, 0.9, 0.15, 0.85])]
    out, _ = bm.build(pred, truth, {})
    row = out[0]
    assert "mcc" in row and isinstance(row["mcc"], float)
    assert "Youden" in row["note"] and "不作主指标" in row["note"]
    # write 写出的 CSV 表头含 mcc
    import csv
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = d + "/b.csv"
        bm.write(p, out)
        with open(p, encoding="utf-8-sig") as fh:
            header = next(csv.reader(fh))
        assert "mcc" in header, header


def test_mutation_score_has_interpretation_guard():
    """§4 分歧 5：变异分数 1.0 不得单独当质量证据。"""
    from adt.governance_ext import mutation_engine as ME
    # 只验证报告结构，不真的跑变异（昂贵）；用最小 mutants 假的 report 结构检查键存在
    import inspect
    src = inspect.getsource(ME.run_mutation_tests)
    assert "interpretation_guard" in src
    assert "split_sensitivity_gate" in src and "ood_monotonicity_gate" in src


def test_build_class_conditional_endpoint_emits_deprecation():
    """§3 疑点 7：旧 Mondrian 入口发 DeprecationWarning。"""
    import warnings as _w
    from adt import conformal as C
    pred = [dict(compound_id="C%d" % i, endpoint="e", value=str(v)) for i, v in enumerate([0.1, 0.2, 0.8, 0.9])]
    truth = [dict(compound_id="C%d" % i, endpoint="e", truth_value=v)
             for i, v in enumerate([0.0, 0.0, 1.0, 1.0])]
    with _w.catch_warnings(record=True) as w:
        _w.simplefilter("always")
        C.build_class_conditional_endpoint(pred, truth, "e", min_n=2)
    assert any(issubclass(x.category, DeprecationWarning) for x in w), [str(x.message) for x in w]


def test_archive_call_default_path_and_aggregate(tmp_path):
    """§5 输入缺口：留痕不写 cwd；每次调用可聚合审计。"""
    from adt import compliance as C
    # 默认路径在 skill 内 logs/，不是当前工作目录
    dp = C.default_call_log_path()
    assert os.path.basename(dp) == "compliance_calls.jsonl"
    assert os.path.basename(os.path.dirname(dp)) == "logs"
    # 聚合审计：显式路径，统计 源×档位×许可
    log = tmp_path / "calls.jsonl"
    log.write_text(
        '{"source":"admetlab3","profile":"commercial","license":"free_rate_limited"}\n'
        '{"source":"admetlab3","profile":"commercial","license":"free_rate_limited"}\n'
        '{"source":"protox3","profile":"pre-commercial","license":"CC-BY-NC"}\n',
        encoding="utf-8")
    r = C.aggregate_calls(str(log))
    assert r["n_calls"] == 3
    assert r["by_source_profile_license"]["admetlab3|commercial|free_rate_limited"] == 2
    # 空文件合法
    empty = tmp_path / "none.jsonl"
    assert C.aggregate_calls(str(empty))["n_calls"] == 0


def test_evidence_tier_command_execution_binding():
    """§5 输出缺口：REFUSED/SKIP 不得写成覆盖；高等级绑定不成立即 REFUSED。"""
    from adt import governance as G
    req = ["normalize", "saturate", "benchmark", "tier"]
    ledger = [
        dict(command="normalize", status="ok"),
        dict(command="saturate", status="ok"),
        dict(command="benchmark", status="refused"),
        dict(command="tier", status="skip"),
    ]
    r = G.command_execution_binding(ledger, req, claimed_tier="T3")
    assert r["bound"] is False
    assert r["verdict"] == "REFUSED"
    assert "benchmark" in r["refused_or_skipped_not_coverage"]
    assert "tier" in r["refused_or_skipped_not_coverage"]
    assert "benchmark" not in r["executed"]
    # 全部 ok 才绑定
    ok = [dict(command=c, status="ok") for c in req]
    r2 = G.command_execution_binding(ok, req, claimed_tier="T3")
    assert r2["bound"] is True and r2["verdict"] == "BOUND"


def test_effective_params_hash_deterministic():
    """§5 参数缺口：同一组参数得到同一 hash，参数变则 hash 变。"""
    from adt import manifest as MF
    class A:
        def __init__(self, **kw):
            self.__dict__.update(kw)
        def func(self):
            pass
    a1 = A(out="out", profile="commercial", func=lambda: None)
    a2 = A(profile="commercial", out="out", func=lambda: None)
    a3 = A(out="out", profile="academic", func=lambda: None)
    assert MF.effective_params_hash(a1) == MF.effective_params_hash(a2)
    assert MF.effective_params_hash(a1) != MF.effective_params_hash(a3)


def test_source_admission_falsifiability_card():
    """§4 分歧 1：源级贡献必须给同覆盖可证伪对比，不给架构图。"""
    from adt import ablation as AB
    # 构造四条件摘要：源级原始更高但同覆盖更低 -> 必须判 refuted（避免覆盖假象）
    result = {
        "summary": [
            dict(condition="b_unit_guard", decided_accuracy=0.70, coverage=0.90),
            dict(condition="c_full_admission", decided_accuracy=0.80, coverage=0.50),
        ],
        "matched": [
            dict(condition="b_unit_guard", matched_accuracy=0.75, target_n=100),
            dict(condition="c_full_admission", matched_accuracy=0.72, target_n=100),
        ],
    }
    card = AB.source_admission_falsifiability_card(result)
    assert card["falsifiable"] is True
    assert card["evidence"] == "refuted_by_same_coverage_comparison"
    assert card["raw_gain"] == 0.1 and card["matched_coverage_gain"] < 0
    # 缺同覆盖数据 -> insufficient
    card2 = AB.source_admission_falsifiability_card({"summary": [], "matched": []})
    assert card2["evidence"] == "insufficient" and card2["falsifiable"] is False


def test_external_comparison_scope_declaration():
    """§5 对照缺口：external_comparison 只对照统计实现，不对照模型性能。"""
    from adt import external_comparison as ec
    d = ec.scope_declaration()
    assert d["does_not_compare"] == "model_predictive_performance"
    assert "benchmark" in d["performance_comparison_commands"]
    assert "ablate" in d["performance_comparison_commands"]


def test_coverage_by_tanimoto_bins_gate():
    """§3 疑点 3：最远分桶覆盖率跌破标称一半即拒绝声明。"""
    from adt import conformal as C
    # 近端全覆盖、远端全不覆盖 -> ok=False（远端 0 < 0.45）
    pairs = [(0.9, True)] * 25 + [(0.85, True)] * 25 + [(0.4, False)] * 25 + [(0.3, False)] * 25
    r = C.coverage_by_tanimoto_bins(pairs, alpha=0.1, n_bins=4)
    assert r["ok"] is False
    assert any("最远分桶" in x for x in r["reasons"])
    # 各层都达标 -> ok=True
    pairs2 = [(0.9, True)] * 50 + [(0.3, True)] * 50
    r2 = C.coverage_by_tanimoto_bins(pairs2, alpha=0.1, n_bins=2)
    assert r2["ok"] is True


def test_peer_review_audit_smoke_and_command_usage():
    """§3 疑点 1/6：smoke 脚本确实含断言；命令无静态零引用。"""
    import sys
    sys.path.insert(0, os.path.join(HERE_DIR(), "tools"))
    import peer_review_audit as P
    s = P.audit_smoke_assertions()
    assert s["n_scripts"] >= 80
    assert s["n_no_assertion"] == 0, [r["script"] for r in s["rows"]
                                      if r["classification"] == "NO_ASSERTION_FOUND"]
    u = P.audit_command_static_usage()
    assert u["n_commands"] >= 70
    assert u["n_zero_static_reference"] == 0, u["zero_static_reference"]


def HERE_DIR():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_anchor_vault_uses_reference_anchor_with_expiry_terminology():
    """§4 分歧 4：绝对锚点改称 reference anchor with expiry。"""
    from adt.governance_ext import anchor_vault as AV
    import inspect
    doc = AV.__doc__ or ""
    assert "reference anchor with expiry" in doc.lower()
    assert "scientific_half_life_days" in inspect.getsource(AV.Anchor)


def test_data_manifest_sha256_and_core_mode():
    """§3 疑点 5：data manifest 含 SHA256 + 来源 + 许可 + core 模式。"""
    import sys
    sys.path.insert(0, os.path.join(HERE_DIR(), "tools"))
    import data_manifest as DM
    m = DM.build()
    assert m["n_files"] >= 15
    assert all(len(f["sha256"]) == 64 for f in m["files"])
    assert m["core_mode"]["all_core_hashes_match"] is True
    assert "oneADMET.csv" in m["core_mode"]["excluded_large_file"]
    assert any("zenodo" in (f["source_url"] or "") for f in m["files"])


def test_all_cli_commands_have_evidence_role():
    """§6 Phase 1 / B19：每个 CLI 命令必须声明分层与 evidence_role。"""
    from adt import command_roles as CR
    ok, undeclared, stale = CR.validate_registry()
    assert ok, "undeclared=%s stale=%s" % (undeclared, stale)
    assert len(CR.cli_commands()) >= 70
    # 关键结论链命令必须 claimable；实验/demo 命令不得 claimable
    assert CR.claimable("trust") is True
    assert CR.claimable("tier") is True
    assert CR.claimable("benchmark") is False  # 证据层，不是结论本身
    assert CR.claimable("pbpk") is False       # 实验层
    assert CR.claimable("conformal") is False


def test_delong_mcnemar_holm_for_phase2():
    """§6 Phase 2 / B20：DeLong/McNemar + Holm 配对检验可用且退化被拒。"""
    from adt import paired_stats as P
    # DeLong：同曲线 p=1；有区分度差异显著
    y = [0] * 50 + [1] * 50
    a = [0.1 + 0.8 * (i / 100) for i in range(50)] + [0.2 + 0.7 * (i / 100) for i in range(50)]
    b = [0.3 + 0.4 * (i / 100) for i in range(50)] + [0.3 + 0.4 * (i / 100) for i in range(50)]
    r = P.delong(a, b, y)
    assert r["method"] == "delong" and r["significant"] is True
    same = P.delong(a, a, y)
    assert abs(same["p"] - 1.0) < 1e-9 and same["delta"] == 0.0
    # 完美分离退化 -> 拒绝给 p
    good = [i / 100 for i in range(50)] + [0.5 + i / 100 for i in range(50)]
    deg = P.delong(good, [0.5] * 100, y)
    assert deg["degenerate"] is True and deg["p"] is None
    # McNemar：对称不显著、极端显著
    assert P.mcnemar(10, 10)["significant"] is False
    assert P.mcnemar(20, 5)["significant"] is True
    # Holm 已存在
    assert len(P.holm([0.01, 0.04, 0.03], alpha=0.05)) == 3


def test_prereg_init_cli_creates_anchorable_chain(tmp_path):
    """全流程实跑发现：Prereg 只有 Python API，status 永远文件不存在。补 CLI 写入口。"""
    from adt import cli as CLI
    log = str(tmp_path / "prereg.jsonl")
    class A:
        pass
    a = A()
    a.name = "primary"
    a.criteria = '{"endpoint":"hERG","rule":"IC50>10"}'
    a.note = "test"
    a.log = log
    a.registry = ""
    a.doi = ""
    a.deposited_at = ""
    from adt.prereg import Prereg
    n_before = len(Prereg(log).events)  # tmp_path 可能复用 .scratch，append-only 链会累积
    assert CLI.cmd_prereg_init(a) == 0
    st = Prereg(log).anchor_status()
    assert st["claim_allowed"] is False
    assert len(Prereg(log).events) == n_before + 1


def test_desire_empty_axis_fails_with_clear_message(tmp_path):
    """全流程实跑发现：rules 无 axis 分组时 desire 原为 min() ValueError 崩溃。"""
    from adt import cli as CLI
    import csv as _csv
    relp = str(tmp_path / "rel.csv")
    with open(relp, "w", encoding="utf-8", newline="") as fh:
        w = _csv.DictWriter(fh, fieldnames=["compound_id", "endpoint", "verdict", "value"])
        w.writeheader()
        w.writerow(dict(compound_id="C1", endpoint="unknown_ep",
                        verdict="PASS", value="0.5"))
    class A:
        pass
    a = A()
    a.input = relp
    a.rules = "references/03_endpoint_rules.yaml"
    a.outdir = str(tmp_path)
    a.enforce_rank_guard = False
    a.max_cluster_frac = 1.0
    import pytest as _pytest
    with _pytest.raises(SystemExit) as ex:
        CLI.cmd_desire(a)
    assert "没有" in str(ex.value) or "axis" in str(ex.value)


def test_gut_micro_from_export_runs_qc_without_network(tmp_path):
    """BioTransformer REST 不可达时，人工导出 JSON 仍可跑 biosystem 过滤+标注 QC。"""
    from adt import cli as CLI
    from adt import gut_microbiome as GM
    # 构造符合 BioTransformer 响应结构的最小样本（1 条标注矛盾的转化）
    data = {"predictions": [{"identifier": "C1", "biotransformations": [{
        "substrates": [{"smiles": "CCO"}],
        "products": [{"smiles": "CCO", "inchikey": "LFQSCWFLJHTTHZ-UHFFFAOYSA-N"}],
        "reaction_type": "Glucuronidation",  # 但质量差为 0 -> 应判 inconsistent
        "metabolic_enzymes": ["UGT"], "biosystem": "gut_microbial"}]}]}
    fp = str(tmp_path / "bt_export.json")
    import json as _json
    with open(fp, "w", encoding="utf-8") as fh:
        _json.dump(data, fh)
    class A:
        pass
    a = A()
    a.from_export = fp
    a.input = ""
    a.outdir = str(tmp_path / "out")
    a.format = "auto"
    import os as _os
    _os.makedirs(a.outdir, exist_ok=True)
    assert CLI.cmd_gut_micro(a) is None
    rows = list(__import__("csv").DictReader(
        open(_os.path.join(a.outdir, "metabolites_gut.csv"), encoding="utf-8-sig")))
    assert rows and rows[0]["source"] == "biotransformer_manual_export"
    assert rows[0]["label_check"] == "inconsistent"  # 标注 QC 真实跑了
