# -*- coding: utf-8 -*-
"""黑榜三项（C6 成因拆解 / C9 统一分数口径 / A1 权重方案）的回归测试。

这些测试的共同原则：**断言"方法与结论的对应关系"，而不是断言某个具体数字**。
一旦有人改了分解公式或弃权口径，测试应从"恒等式"或"边界行为"上失败，
而不是因为小数点后第四位变了。
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
if os.path.dirname(HERE) not in sys.path:
    sys.path.insert(0, os.path.dirname(HERE))

from adt import independence as I      # noqa: E402
from adt import selective as SEL       # noqa: E402
from adt import weights as W           # noqa: E402


def _toy(n=400, seed=0):
    rng = np.random.default_rng(seed)
    y = (rng.random(n) > 0.6).astype(float)
    e1 = rng.normal(0, 0.30, n)
    e2 = 0.8 * e1 + rng.normal(0, 0.20, n)      # 与 e1 共享
    e3 = rng.normal(0, 0.30, n)                  # 独立
    clip = lambda v: np.clip(v, 0.0, 1.0)
    return y, clip(y + e1), clip(y + e2), clip(y + e3)


# --------------------------------------------------------------- C6
def test_error_variance_decomposition_is_identity():
    y, p1, p2, _ = _toy()
    d = I.decompose_error_variance(p1, p2, y)
    assert abs(d["indep_term"] + d["shared_term"] - d["var_err_mean"]) < 1e-9
    # 旧版协方差分解不恒等，这里显式钉住"必须是方差分解"
    assert "cov_error" in d


def test_shared_error_flagged_but_independent_not():
    y, p1, p2, p3 = _toy()
    d_shared = I.decompose_error_variance(p1, p2, y)
    d_indep = I.decompose_error_variance(p1, p3, y)
    assert d_shared["verdict"] == "shared_errors"
    assert d_shared["r_error"] > 0.5
    assert d_indep["r_error"] < d_shared["r_error"]
    assert d_indep["verdict"] != "shared_errors"


def test_high_total_corr_can_be_signal_dominated():
    """两源都接近完美 → total_corr 极高，但误差几乎不共享：不得读作方法不独立。"""
    rng = np.random.default_rng(3)
    y = (rng.random(500) > 0.5).astype(float)
    p1 = np.clip(y + rng.normal(0, 0.05, 500), 0, 1)
    p2 = np.clip(y + rng.normal(0, 0.05, 500), 0, 1)
    d = I.decompose_error_variance(p1, p2, y)
    assert d["total_corr"] > 0.9
    assert d["verdict"] != "shared_errors"
    s = I.attribution_summary([d])
    assert "不得做独立性归因" in s["statement"] or "共同真值" in s["statement"]


def test_attribution_summary_never_claims_independence_cause():
    y, p1, p2, _ = _toy()
    s = I.attribution_summary(I.pairwise_decomposition(
        np.vstack([p1, p2]).T, y, ["a", "b"]))
    assert "仍未拆解" in s["statement"]      # 成因不得被断言


# --------------------------------------------------------------- C9
def test_unified_curve_endpoint_equals_all_risk():
    y, p1, _, _ = _toy()
    pred = (p1 >= 0.5).astype(int)
    score = SEL.unified_confidence(p1)
    c = SEL.unified_risk_coverage(y, pred, score)
    assert c["curve"][-1]["coverage"] == 1.0
    assert abs(c["curve"][-1]["risk"] - float(np.mean(pred != y))) < 1e-6


def test_frontier_interpolation_is_between_neighbours():
    y, p1, _, _ = _toy()
    pred = (p1 >= 0.5).astype(int)
    curve = SEL.unified_risk_coverage(y, pred, SEL.unified_confidence(p1))["curve"]
    lo = SEL.frontier_risk_at(curve, 0.15)
    hi = SEL.frontier_risk_at(curve, 0.25)
    mid = SEL.frontier_risk_at(curve, 0.20)
    assert min(lo, hi) - 1e-9 <= mid <= max(lo, hi) + 1e-9


def test_operating_point_gap_is_zero_for_confidence_abstention():
    """S3 就是"按置信度弃权"本身 → 它的运行点必须落在统一前沿上（gap≈0）。

    这是口径正确性的自检：若 gap 明显非 0，说明 score 与 decided 不是同一个分数。
    """
    y, p1, _, _ = _toy()
    pred = (p1 >= 0.5).astype(int)
    score = SEL.unified_confidence(p1)
    for q in (0.5, 0.6, 0.7):
        thr = np.quantile(score, q)
        op = SEL.operating_point(y, pred, score >= thr, score)
        assert op["efficiency_gap"] is not None
        assert abs(op["efficiency_gap"]) <= 0.06, (q, op)


def test_operating_point_penalises_wrong_abstention():
    """故意用"越置信越弃权"的反向规则 → gap 应显著为正。"""
    y, p1, _, _ = _toy()
    pred = (p1 >= 0.5).astype(int)
    score = SEL.unified_confidence(p1)
    thr = np.quantile(score, 0.5)
    op = SEL.operating_point(y, pred, score < thr, score)   # 反向
    assert op["efficiency_gap"] > 0.1


# --------------------------------------------------------------- A1
def test_all_schemes_live_on_simplex():
    y, p1, p2, p3 = _toy()
    P = np.vstack([p1, p2, p3]).T
    for name, fn in W.SCHEMES.items():
        w = fn(P, y)
        assert w.shape == (3,), name
        assert abs(float(w.sum()) - 1.0) < 1e-9, name
        assert float(w.min()) >= 0.0, name


def test_shrink_equals_equal_when_uncorrelated():
    rng = np.random.default_rng(7)
    P = rng.random((500, 3))
    w = W.shrink_weights(P, rho=np.zeros((3, 3)))
    assert np.allclose(w, np.ones(3) / 3.0, atol=1e-9)


def test_shrink_downweights_correlated_source():
    y, p1, p2, p3 = _toy()
    P = np.vstack([p1, p2, p3]).T      # p1,p2 共享误差；p3 独立
    w = W.shrink_weights(P)
    assert w[2] > w[0] and w[2] > w[1]


def test_bma_downweights_noise_source():
    rng = np.random.default_rng(11)
    n = 800
    y = (rng.random(n) > 0.5).astype(int)
    good = np.clip(y * 0.8 + 0.1 + rng.normal(0, 0.05, n), 0, 1)
    mid = np.clip(y * 0.5 + 0.25 + rng.normal(0, 0.15, n), 0, 1)
    noise = rng.random(n)
    P = np.vstack([good, mid, noise]).T
    w = W.bma_weights(P, y)
    assert w[0] > w[2], w            # 好源权重必须高于噪声源
    assert w[0] == w.max()


def test_diversity_ties_for_duplicates_and_discounts_noise():
    """完全重复的两个源在信息上不可区分 → 必须同权；噪声源必须被压到最低。

    这里刻意**不**断言"重复源权重更低"：第一版实现那样做过，结果是把重复对压到 0、
    让随机源成了最大权重（随机源与谁都只 ~50% 一致）。所以改为"准确率主导"，
    并接受数学事实：完全相同的信息无法被折扣区分。
    """
    rng = np.random.default_rng(13)
    n = 600
    y = (rng.random(n) > 0.5).astype(int)
    a = np.clip(y * 0.7 + 0.15 + rng.normal(0, 0.08, n), 0, 1)
    dup = a.copy()
    noise = rng.random(n)
    w = W.diversity_weights(np.vstack([a, dup, noise]).T, y)
    assert abs(w[0] - w[1]) < 1e-12, w      # 不可区分 → 同权
    assert w[2] < 0.2, w                    # 噪声被显著压权
    assert w[2] == w.min(), w


def test_compare_reports_strict_flag_for_bma():
    y, p1, p2, p3 = _toy()
    P_cal = np.vstack([p1, p2, p3]).T
    P_te = P_cal.copy()
    out = W.compare(P_cal, y, P_te, y)
    assert out["bma"]["strict"] is False     # 必须是"代理"，不得冒称严格 BMA
    for k in ("equal", "shrink", "diversity"):
        assert out[k]["strict"] is True


def main():
    fns = [(k, v) for k, v in sorted(globals().items()) if k.startswith("test_")]
    for name, fn in fns:
        fn()
        print("OK", name)
    print("ALL PASS test_blacklist_v41.py (%d)" % len(fns))


if __name__ == "__main__":
    main()
