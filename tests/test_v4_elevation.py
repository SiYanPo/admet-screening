# -*- coding: utf-8 -*-
"""评审 v4.0 拔高项回归测试：P8 随机化零对照 / L1-1 贝叶斯三态 / P3 risk-coverage / L2-1 交换性。

全部用合成数据，验证统计函数行为正确、不依赖外部实验室数据。
运行：python tests/test_v4_elevation.py
"""
import math
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adt import pred_displacement, decision_value, selective, conformal


def _approx(a, b, tol=1e-6):
    return abs(a - b) <= tol


def test_p8_null_control_significant():
    # 真实结构扰动：多数分子位移明显 >0；零分布：几乎都在 0 附近
    real = [0.4, 0.5, 0.3, 0.6, 0.45, 0.55, 0.35, 0.5, 0.42, 0.48,
            0.52, 0.38, 0.47, 0.58, 0.41, 0.49, 0.44, 0.53, 0.39, 0.46]
    null = [0.01, 0.0, 0.02, 0.0, 0.01, 0.0, 0.0, 0.03, 0.0, 0.01,
            0.0, 0.0, 0.02, 0.0, 0.0, 0.01, 0.0, 0.0, 0.01, 0.0]
    r = pred_displacement.randomization_null_control(real, null, thr=0.1)
    assert r["p_real_above"] > r["p_null_above"], r
    assert r["significant"] is True, r
    assert r["ci"][0] > 0, r
    print("P8 显著:", r["rate_diff"], r["ci"], r["conclusion"])


def test_p8_null_control_non_significant():
    # 真实与零分布同分布 → 不应判显著
    rng = [0.30, 0.31, 0.29, 0.32, 0.28, 0.30, 0.31, 0.29, 0.30, 0.32] * 4
    r = pred_displacement.randomization_null_control(rng, list(rng), thr=0.1)
    assert r["significant"] is False, r
    assert r["ci"][0] <= 0 <= r["ci"][1], r
    print("P8 不显著(自比):", r["rate_diff"], r["ci"])


def test_l11_bayes_three_state_defer():
    # 中等后验风险 + 适度 defer 代价（筛选场景：放行坏 >> 误杀好）
    r = decision_value.bayes_three_state(p_bad=0.2, c_fp=1.0, c_fn=5.0, c_defer=0.5)
    assert r["action"] == "UNDETERMINED", r
    # 验证：c_defer 必须小于两个直接判定的期望代价
    assert r["expected_cost"] < min(r["costs"]["PASS"], r["costs"]["FAIL"]), r
    print("L1-1 中风险-适度defer:", r["action"], r["costs"])


def test_l11_bayes_three_state_commit():
    # 极低后验风险 + 高 defer 代价 → 直接 PASS
    r = decision_value.bayes_three_state(p_bad=0.02, c_fp=1.0, c_fn=5.0, c_defer=1.5)
    assert r["action"] == "PASS", r
    print("L1-1 低后验-高defer:", r["action"], r["expected_cost"])


def test_l13_cost_ratio_grid():
    # 中风险 p_bad=0.2 应存在 UNDETERMINED 稳定区（筛选成本结构）
    g = decision_value.cost_ratio_sensitivity_grid(p_bad=0.2, c_fp=1.0, c_fn=5.0)
    assert g["undetermined_region"] is not None, g
    lo, hi = g["undetermined_region"]
    assert lo <= hi
    # 稳定区内的 c_defer 必须确实返回 UNDETERMINED
    mid = (lo + hi) / 2.0
    r = decision_value.bayes_three_state(0.2, c_fp=1.0, c_fn=5.0, c_defer=mid)
    assert r["action"] == "UNDETERMINED", (mid, r)
    print("L1-3 稳定区:", g["undetermined_region"])


def test_p3_risk_coverage_report():
    # 构造：高 score 的分子更可能正确 → 曲线应下降
    pairs = [(0.95, True), (0.90, True), (0.85, True), (0.80, False),
             (0.75, True), (0.70, False), (0.65, True), (0.60, False),
             (0.55, False), (0.50, False), (0.45, False), (0.40, False)]
    rep = selective.risk_coverage_report(pairs, target_risk=0.2)
    assert rep["aurc"] is not None
    assert 0.0 <= rep["aurc"] <= 1.0, rep
    assert rep["full_abstain"]["coverage"] == 0.0
    # 高 coverage 处 risk 应高于低 coverage 处（曲线单调不降）
    pts = rep["curve"]
    assert pts[0]["risk"] <= pts[-1]["risk"], "low-coverage risk 应更低"
    print("P3 AURC=%.4f 最优弃权率=%.2f" % (rep["aurc"], rep["optimal_abstain_rate"]))


def test_p3_base_rate_stratified():
    hi = [(0.9, True), (0.8, True), (0.7, True), (0.6, True)]   # 高基率层
    lo = [(0.9, False), (0.8, False), (0.7, True), (0.6, False)]  # 低基率层
    strata = [("high_base", hi), ("low_base", lo)]
    out = selective.base_rate_stratified(hi + lo, strata)
    by = {d["stratum"]: d["risk"] for d in out}
    assert by["high_base"] < by["low_base"], by
    print("P3 分层 risk:", by)


def test_l21_exchangeability_drift():
    # 时间分箱：早期箱覆盖正常，晚期箱显著掉队 → 应检测到漂移
    bins = [("t<2020", 0.92, 200), ("2020-2022", 0.90, 200),
            ("2023-2024", 0.78, 200), ("2025+", 0.70, 200)]
    r = conformal.exchangeability_drift(bins, alpha=0.1)
    assert r["any_drift"] is True, r
    drifted = [b["bin"] for b in r["bins"] if b["drift"]]
    assert "2025+" in drifted, drifted
    print("L2-1 漂移分箱:", drifted)


def test_l21_no_drift():
    bins = [("a", 0.90, 300), ("b", 0.91, 300), ("c", 0.89, 300)]
    r = conformal.exchangeability_drift(bins, alpha=0.1)
    assert r["any_drift"] is False, r
    print("L2-1 无漂移 OK")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        try:
            fn()
            passed += 1
        except AssertionError as e:
            print("FAILED", fn.__name__, "->", e)
            raise
    print("\n全部 %d 项通过" % passed)
