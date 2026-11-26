# -*- coding: utf-8 -*-
"""R03/R04/R05/R06/R07 回归测试：n_eff 公式修正、权重 CI、功效门、贝叶斯收缩。

对应评审 C3/C4/C5 + R1-1 + B1。
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adt.independence import (                    # noqa: E402
    rho_contraction_weight, n_eff_equicorrelated, n_eff_from_corr_matrix,
    n_eff_kish_eigen, weight_ci, assess_pair, correlation_power,
    min_detectable_rho, bayes_contraction, rho_posterior_weights,
    MIN_PAIRS_FOR_INDEPENDENCE)
from adt.stats_ci import correlation_power_report  # noqa: E402


def equicorr(k, rho):
    R = np.full((k, k), float(rho))
    np.fill_diagonal(R, 1.0)
    return R


def test_k2_backward_compatible():
    """k=2 必须与历史 1/(1+ρ) 逐位一致（不得静默改变既有结论）。"""
    w, st, note = rho_contraction_weight(0.594, ci_lo=0.41, ci_hi=0.72, k=2)
    assert st == "contracted"
    assert abs(w - 1.0 / (1.0 + 0.594)) < 1e-3, w


def test_k_enters_formula():
    """C3 核心：组内源数 k 必须进入公式；k=5, ρ=0.5 → w=1/3, n_eff=5/3。"""
    w5, _, _ = rho_contraction_weight(0.5, ci_lo=0.3, ci_hi=0.7, k=5)
    w2, _, _ = rho_contraction_weight(0.5, ci_lo=0.3, ci_hi=0.7, k=2)
    assert abs(w5 - 1.0 / 3.0) < 1e-3, w5
    assert w5 < w2, "源越多、同等相关越强，单源权重应更低"
    assert abs(n_eff_equicorrelated(5, 0.5) - 5.0 / 3.0) < 1e-9
    assert abs(n_eff_equicorrelated(2, 0.5) - 2.0 / 1.5) < 1e-9
    # k=1：单源无冗余
    w1, _, _ = rho_contraction_weight(0.9, ci_lo=0.8, ci_hi=0.95, k=1)
    assert abs(w1 - 1.0) < 1e-9


def test_matrix_form_is_consistent_with_equicorrelation():
    """R03 的数学结论：正确推广是 k²/(1ᵀR1)，不是 (Σλ)²/Σλ²。"""
    for k, rho in ((3, 0.4), (4, 0.5), (6, 0.2), (5, 0.0)):
        R = equicorr(k, rho)
        neff_mat = n_eff_from_corr_matrix(R)
        neff_eq = n_eff_equicorrelated(k, rho)
        assert abs(neff_mat - neff_eq) < 1e-6, (k, rho, neff_mat, neff_eq)
        # 评审建议的 (Σλ)²/Σλ² 实际给出 k/(1+(k−1)ρ²)，仅 ρ∈{0,1} 重合
        kish = n_eff_kish_eigen(R)
        expected_kish = k / (1 + (k - 1) * rho ** 2)
        assert abs(kish - expected_kish) < 1e-6, (kish, expected_kish)
    # 非等相关：矩阵式仍可算，且介于 [1, k]
    R = np.array([[1.0, 0.9, 0.1], [0.9, 1.0, 0.2], [0.1, 0.2, 1.0]])
    v = n_eff_from_corr_matrix(R)
    assert 1.0 <= v <= 3.0


def test_weight_ci_ordering_and_width():
    """C4：权重必须有区间，且 w_lo ≤ w_med ≤ w_hi。"""
    med, lo, hi = weight_ci(4, 0.6, 0.35, 0.79)
    assert lo <= med <= hi, (lo, med, hi)
    assert hi - lo > 0.05, "ρ 的 CI 很宽时权重区间不应塌成一点"
    # 无 CI 时退化为点
    m2, l2, h2 = weight_ci(4, 0.6, None, None)
    assert l2 == h2 == m2


def test_power_gate_blocks_small_n():
    """C5 / R1-1：n=14 必须被功效门拦住，不得静默出收缩权重。"""
    r = assess_pair(14, 0.5, 0.1, 0.78)
    assert r["status"] == "insufficient_power", r
    assert r["weight"] == 1.0
    assert "sample_size" in r["reason"]
    assert r["power_at_rho_0.5"] < 0.5, "评审断言 n=14 对 ρ=0.5 功效不足 50%"
    # n=100 放行
    r2 = assess_pair(100, 0.5, 0.35, 0.62)
    assert r2["status"] == "contracted"
    assert r2["weight_ci95"][0] <= r2["weight"] <= r2["weight_ci95"][1]
    assert r2["robustness"] in ("robust", "marginal", "unstable")


def test_power_report_numbers():
    rep = correlation_power_report(14)
    assert rep["verdict"] == "insufficient"
    assert rep["power_by_rho"]["0.5"] < 0.5
    assert rep["min_detectable_rho"] > 0.5
    rep2 = correlation_power_report(200)
    assert rep2["verdict"] == "adequate"
    assert rep2["power_by_rho"]["0.5"] > 0.99
    assert correlation_power(50, 0.5) > correlation_power(20, 0.5)
    assert min_detectable_rho(200, power=0.8) < min_detectable_rho(30, power=0.8)


def test_rho_posterior_weights_interval():
    d = rho_posterior_weights(4, 0.5, n_pairs=100, n_draws=2000, seed=1)
    lo, hi = d["w_ci95"]
    assert lo <= d["w_median"] <= hi
    assert d["p_contracted"] > 0.9, "n=100 且 ρ=0.5 时后验几乎必然为正"
    # 小样本时后验更宽（不确定性传播到权重）
    d_small = rho_posterior_weights(4, 0.5, n_pairs=14, n_draws=2000, seed=1)
    assert (d_small["w_ci95"][1] - d_small["w_ci95"][0]) > (hi - lo)


def test_bayes_contraction_reduces_to_equicorrelation():
    R = equicorr(4, 0.5)
    out = bayes_contraction(R, n_obs=200, votes=[1, 1, -1, 0], n_draws=800, seed=7)
    assert 1.0 <= out["n_eff_median"] <= 4.0
    assert abs(out["n_eff_median"] - 1.6) < 0.35, out["n_eff_median"]
    p = out["verdict_prob"]
    assert abs(sum(p.values()) - 1.0) < 1e-6
    assert out["verdict_point"] in p
    # 全一致投票 → 判决应稳定
    out2 = bayes_contraction(equicorr(3, 0.3), n_obs=200, votes=[1, 1, 1],
                             n_draws=600, seed=3)
    assert out2["verdict_prob"]["FAIL"] > 0.95
    assert out2["verdict_stability"] == "stable"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print("OK", fn.__name__)
    print("ALL PASS test_independence_v41.py (%d)" % len(fns))
