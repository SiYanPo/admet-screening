# -*- coding: utf-8 -*-
"""P2（评审 v4.0，C5）回归测试：Clopper-Pearson 注册门 + 设计端通过概率。"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adt import stats_ci


def test_clopper_pearson_basic():
    # k=0, n=100 → 95% CI 上界应约为 0.03 量级
    lo, hi = stats_ci.clopper_pearson_ci(0, 100)
    assert lo == 0.0
    assert 0.0 < hi < 0.05


def test_registration_gate_pass_requires_ci_upper_le_tol():
    # 观测 2/100 = 2%：点估计低于 5%，但 CI 上界可能仍 >5% → 不能宣称通过
    g = stats_ci.registration_gate(2, 100, tol=0.05)
    assert g["n"] == 100
    assert g["observed_rate"] == 0.02
    assert "ci_upper" in g
    # 2/100 的 CP 上界约 0.07 > 0.05 → 不通过（这正是 P2 要纠正的"点估计过关"错觉）
    assert g["passes"] is False or g["ci_upper"] > 0.05


def test_registration_gate_clear_pass_large_n():
    # 0/200 → 上界很小，应通过
    g = stats_ci.registration_gate(0, 200, tol=0.05)
    assert g["passes"] is True
    assert g["ci_upper"] <= 0.05


def test_gate_pass_probability_monotonic_in_n():
    # 好源（真实失败率 3%）：n 越大越容易"有把握地"通过 5% 门
    curve = stats_ci.gate_pass_probability(0.03, n_grid=(20, 50, 100, 200))
    assert curve, "需要 scipy 才能跑设计端分析"
    ns = list(curve.keys())
    for i in range(1, len(ns)):
        assert curve[ns[i]] >= curve[ns[i - 1]] - 1e-9


def test_gate_pass_probability_small_n_low():
    # 真实 3% 但 n=20：通过概率应明显低于大 n（论证 n≳60 的必要性）
    curve = stats_ci.gate_pass_probability(0.03, n_grid=(20, 60, 100))
    assert curve[20] < curve[100]


# ---------------------------------------------------------------------------
# P2.4（2026-11-03 评审）：区间估计函数
# ---------------------------------------------------------------------------
def test_auc_bootstrap_ci_covers_point_and_narrows_with_n():
    import random as _r
    _r.seed(7)

    def _data(n):
        y = [0] * (n // 2) + [1] * (n // 2)
        s = [_r.gauss(0, 1) for _ in range(n // 2)] +             [_r.gauss(1.2, 1) for _ in range(n // 2)]
        return y, s

    small = stats_ci.auc_bootstrap_ci(*_data(60), n_boot=400)
    big = stats_ci.auc_bootstrap_ci(*_data(400), n_boot=400)
    for r in (small, big):
        assert r["lo"] <= r["auc"] <= r["hi"], "点估计必须落在 CI 内"
    assert (big["hi"] - big["lo"]) < (small["hi"] - small["lo"]), "n 增大 CI 应变窄"


def test_auc_bootstrap_ci_single_class_is_undefined():
    r = stats_ci.auc_bootstrap_ci([1, 1, 1], [0.1, 0.2, 0.3])
    assert r["auc"] is None and "单一类别" in r.get("note", "")


def test_auc_perfect_separation_ci_upper_is_one():
    y = [0, 0, 1, 1]
    s = [0.1, 0.2, 0.8, 0.9]
    r = stats_ci.auc_bootstrap_ci(y, s, n_boot=300)
    assert r["auc"] == 1.0
    assert r["hi"] <= 1.0 and r["lo"] > 0.5


def test_wilson_ci_bounds_and_shrinkage():
    r = stats_ci.wilson_ci(40, 226)
    assert 0 <= r["lo"] < r["p"] < r["hi"] <= 1
    # 全成功/全失败不得越界
    assert stats_ci.wilson_ci(0, 10)["lo"] == 0.0
    # 浮点等价值：全成功时上界应贴合 1（0.9999999999999999 属正常浮点误差）
    assert abs(stats_ci.wilson_ci(10, 10)["hi"] - 1.0) < 1e-12


def test_newcombe_diff_ci_sign_and_zero_crossing():
    a = stats_ci.newcombe_diff_ci(156, 581, 40, 226)
    assert a["diff"] > 0 and a["lo"] > 0, "Ames 实测差值应显著为正"
    b = stats_ci.newcombe_diff_ci(50, 100, 50, 100)
    assert b["diff"] == 0 and b["lo"] < 0 < b["hi"], "相同两臂应跨越 0"


def test_paired_bootstrap_diff_recovers_known_difference():
    cells = [(40, "A"), (186, "B"), (116, "C"), (239, "D")]

    def _f(cp):
        a = sum(c for c, p in cp if p == "A")
        b = sum(c for c, p in cp if p == "B")
        c_ = sum(c for c, p in cp if p == "C")
        d = sum(c for c, p in cp if p == "D")
        return (a + c_) / (a + b + c_ + d) - a / (a + b)

    r = stats_ci.paired_bootstrap_diff_ci(cells, _f, n_boot=800)
    assert abs(r["diff"] - (156 / 581 - 40 / 226)) < 1e-9
    assert r["lo"] < r["diff"] < r["hi"]
    assert r["lo"] > 0, "该数据下差值应稳定为正"


if __name__ == "__main__":
    for fn in (v for k, v in sorted(globals().items()) if k.startswith("test_")):
        fn()
        print("ok:", fn.__name__)


# ---------------------------------------------------------------- P2.4-d 多重比较
# 2026-11-03：材料此前只报三个端点里最好的那个 p（DILI 0.0267），从不提另两次也测了。
# 这组测试锁死校正行为，尤其是"校正后区间必须比未校正更宽"——
# 因为 _z 曾经对 alpha=0.05/3 静默退回 1.96，让"校正后区间"与 95% 一模一样。


def test_holm_example_matches_textbook():
    r = stats_ci.holm([0.0267, 0.7554, 1.0], alpha=0.05)
    fam = r["family"]
    assert r["m"] == 3
    assert fam[0]["p"] == 0.0267
    assert abs(fam[0]["adj"] - 0.0801) < 1e-9          # 0.0267*3
    assert fam[0]["reject"] is False
    assert r["familywise_any_reject"] is False


def test_holm_is_monotone_in_adj():
    r = stats_ci.holm([0.001, 0.002, 0.9], alpha=0.05)
    adjs = [it["adj"] for it in r["family"]]
    assert adjs == sorted(adjs), "Holm 的调整 p 不得下降（单调化）"


def test_holm_single_comparison_unchanged():
    r = stats_ci.holm([0.04], alpha=0.05)
    assert r["m"] == 1
    assert abs(r["family"][0]["adj"] - 0.04) < 1e-12
    assert r["family"][0]["reject"] is True


def test_z_supports_arbitrary_alpha():
    """0.05/3 必须真的用 2.394，而不是静默退回 1.96。"""
    assert abs(stats_ci._z(0.05) - 1.959963984540054) < 1e-9
    assert abs(stats_ci._z(0.05 / 3) - 2.3939798) < 1e-6
    assert stats_ci._z(0.05 / 3) > stats_ci._z(0.05)


def test_familywise_ci_is_wider_than_95():
    a = stats_ci.newcombe_diff_ci(47, 63, 31, 33, alpha=0.05)
    b = stats_ci.newcombe_diff_ci(47, 63, 31, 33, alpha=0.05 / 3)
    assert (b["lo"] < a["lo"]) and (b["hi"] > a["hi"])
    # 未校正时该差值区间不含 0；族内校正后含 0 —— 这正是"挑最好的一次"能被洗白的地方
    assert a["hi"] < 0 < b["hi"]


def test_wilson_endpoints_are_exact():
    assert stats_ci.wilson_ci(0, 10)["lo"] == 0.0
    assert stats_ci.wilson_ci(10, 10)["hi"] == 1.0
