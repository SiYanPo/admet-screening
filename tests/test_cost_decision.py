# -*- coding: utf-8 -*-
"""B6 / C18 / 外审 A 回归锁（2026-11-04）。

锁死四件事：
1. 代价记号方向与 run_keystone.utility() 严格一致（压缩前版本曾把 c_fp_pass /
   c_fp_fail 对调，导致贝叶斯阈值反向，此处为纠错回归）；
2. 代价真正进入 decided_mask（各档 sha256 不全同）；
3. Δu(c)=a−q·c 会计恒等式能被机械判定为 accounting_only；
4. phrasing / redlines 的 R18 闸门会拦截 c* / 无差异点 / 条件性优势区，
   且只能由带证据的 ctx 解除。
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adt import cost_decision as CD          # noqa: E402
from adt import phrasing as PH               # noqa: E402
from adt import redlines as RL               # noqa: E402


def test_cost_sign_convention_matches_utility():
    """(5,1,·)：判 FAIL 阈值必须是 c_fp_fail/(c_fp_pass+c_fp_fail)=1/6，
    而不是反过来的 5/6。用两个概率点跨阈值验证动作。"""
    t = CD  # 触发导入
    assert t is CD
    # 直接引用 run_keystone 的阈值函数，避免两处实现漂移
    import run_keystone as K
    thr = K.bayes_threshold_from_costs((5.0, 1.0, 0.5))
    assert abs(thr - 1.0 / 6.0) < 1e-9
    # 弃权代价须高于 min(cost_fail, cost_pass) 才能观察到 FAIL/PASS 方向；
    # 否则理性策略恒弃权，测试会假绿。
    costs = (5.0, 1.0, 2.0)
    lo = CD.pi_cost_sensitive([thr - 0.05], costs)
    hi = CD.pi_cost_sensitive([thr + 0.05], costs)
    assert lo["actions"] == ["PASS"], lo
    assert hi["actions"] == ["FAIL"], hi
    # 与 utility() 的记号交叉验证：真 FAIL 被判 PASS 应计 c_fp_pass=5
    import run_keystone as K2
    u = K2.utility(np.array([1]), np.array([0]), np.array([True]),
                   (5.0, 1.0, 0.01))
    assert u == pytest.approx(-5.0)


def test_decided_mask_varies_with_cost():
    probs = [0.05, 0.20, 0.40, 0.60, 0.80, 0.95]
    grid = [(5.0, 1.0, c) for c in (0.05, 0.10, 0.20, 0.50, 1.00)]
    sw = CD.sweep_decision_masks(probs, grid)
    assert sw["n_cost_points"] == 5
    assert sw["distinct_decided_masks"] > 1, sw
    assert sw["accounting_only"] is False
    # 弃权代价越高，弃权样本越少（单调方向），证明 cost 进入了掩码
    abst = [o["n_abstained"] for o in sw["points"]]
    assert abst == sorted(abst, reverse=True), abst


def test_linearity_audit_flags_accounting_identity():
    # 外审 A 复算的 Δu(c)=a−q·c，q=0.8189
    pts = [(c, 0.2128 - 0.8189 * c) for c in (0.05, 0.10, 0.20, 0.50, 1.00)]
    r = CD.linearity_audit(pts)
    assert r["status"] == "ok"
    assert r["r2"] >= 0.999
    assert r["accounting_only"] is True
    assert "c_star" in r["forbidden_claims"]
    # 非线性（代价进决策后的真实曲线）不得被误判为会计恒等式
    curved = [(0.05, 0.10), (0.10, 0.42), (0.20, 0.18), (0.50, 0.55), (1.00, 0.05)]
    assert CD.linearity_audit(curved)["accounting_only"] is False


def test_phrasing_and_redlines_block_accounting_claims():
    bad = "准入层存在条件性优势区，无差异点 c* 约为 0.26。"
    hits = PH.flag_accounting_claims(bad)["hits"]
    assert "条件性优势区" in hits and "无差异点" in hits
    v = RL.scan_report_text(bad)
    assert any(x["red_line"] == "R18_accounting_identity" for x in v), v
    # 举证责任在作者：只声明 verified 但 accounting_only 未给 False，仍拦截
    v2 = RL.scan_report_text(bad, ctx={"cost_decision_verified": True})
    assert any(x["red_line"] == "R18_accounting_identity" for x in v2), v2
    # 带齐证据才解除
    v3 = RL.scan_report_text(bad, ctx={"cost_decision_verified": True,
                                       "accounting_only": False})
    assert not any(x["red_line"] == "R18_accounting_identity" for x in v3), v3


def test_audit_pipeline_separates_legacy_from_new():
    pi_rows = []
    for seed in (0, 1):
        for i, c in enumerate((0.05, 0.20, 1.00)):
            pi_rows.append(dict(endpoint="hERG", seed=seed,
                                cost_point="abstain=%.2f" % c,
                                decided_mask_sha256="h%d_%d" % (seed, i)))
    legacy = {"hERG": [(c, 0.2128 - 0.8189 * c)
                       for c in (0.05, 0.10, 0.20, 0.50, 1.00)]}
    r = CD.audit_pipeline(pi_rows, legacy)
    assert r["legacy_accounting_only"] is True
    assert r["cost_sensitive_decision_verified"] is True
    assert r["accounting_only"] is True, "新流水线修好不得洗白旧主张"
    assert r["legacy_claim_status"] == "revoked_pending_estimand"
    assert r["n_groups"] == 2 and r["groups_with_decision_varying"] == 2
    # 若新流水线各档 hash 全同，必须判未验证
    same = [dict(x, decided_mask_sha256="same") for x in pi_rows]
    assert CD.audit_pipeline(same, legacy)["cost_sensitive_decision_verified"] is False


def test_strategies_costs_produce_S6():
    """外审 A 的原始指控：costs 在 strategies 函数体内零引用。此处锁死正面修复。"""
    import run_keystone as K
    p = np.array([0.05, 0.20, 0.40, 0.60, 0.80, 0.95])
    probs = {"a": p, "b": np.clip(p + 0.02, 0, 1)}
    calib = {"a": lambda x: x, "b": lambda x: x}
    ad = np.ones(len(p)) * 0.9
    s = K.strategies(probs, ad, 0.1, calib, thr_raw=0.1,
                     costs=(5.0, 1.0, 0.05))
    assert "S6_cost_sensitive" in s
    s2 = K.strategies(probs, ad, 0.1, calib, thr_raw=0.1,
                      costs=(5.0, 1.0, 1.00))
    assert not np.array_equal(s["S6_cost_sensitive"][1],
                              s2["S6_cost_sensitive"][1])
    # 不带 costs 时不得出现 S6（S1–S5 口径保持兼容）
    assert "S6_cost_sensitive" not in K.strategies(probs, ad, 0.1, calib,
                                                   thr_raw=0.1)
