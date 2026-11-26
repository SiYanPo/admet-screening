# -*- coding: utf-8 -*-
"""R14 / R19 / R20 的回归测试（v4.2 补）。

背景：这两组功能此前只有代码、从未在真实数据上执行过，因而"实现是否存在"
被误当成"结论是否成立"。本文件钉住的是**判定语义**：

  · gate 判别力不足时必须明确说"不可解释为域外诚实"，而不是留白；
  · MMP 检验必须区分"迟钝"与"过敏"，禁止把迟钝写成"稳定"；
  · 未做判别力测量时，摘要必须自报 not_measured（不许默认正面）。
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
if os.path.dirname(HERE) not in sys.path:
    sys.path.insert(0, os.path.dirname(HERE))

from adt import gate_audit as GA      # noqa: E402
from adt import mmp                   # noqa: E402


# --------------------------------------------------------------- R19/R20
def test_gate_power_flags_uninformative_when_sims_carry_no_signal():
    rng = np.random.default_rng(0)
    n = 600
    y = (rng.random(n) > 0.5).astype(int)
    pred = (rng.random(n) > 0.5).astype(int)
    sims = rng.random(n)                     # 与正确性无关
    p = GA.discriminative_power(sims, y, pred)
    assert p["verdict"] == "uninformative"
    assert p["auc"] < GA.GATE_AUC_FLOOR
    # P2.4-b：无 CI 时不再断言"与随机不可区分"，而是拒绝下结论（见 STATISTICAL_POLICY §P2.4-b）
    assert "未提供 95" in p["interpretation"]
    assert p["verdict_ci"] == "no_ci"


def test_gate_power_flags_informative_when_sims_predict_correctness():
    rng = np.random.default_rng(1)
    n = 800
    y = (rng.random(n) > 0.5).astype(int)
    # 正确性由 sims 决定：sims 高 -> 预测对
    correct = (rng.random(n) < (0.15 + 0.7 * rng.random(n)))
    pred = np.where(correct, y, 1 - y)
    sims = np.where(correct, rng.uniform(0.6, 1.0, n), rng.uniform(0.0, 0.45, n))
    p = GA.discriminative_power(sims, y, pred)
    assert p["verdict"] == "informative"
    assert p["auc"] >= GA.GATE_AUC_FLOOR


def test_forced_prediction_justified_only_when_out_of_domain_really_worse():
    y = np.array([1] * 50 + [0] * 50)
    pred_good_in = y.copy()
    out = np.zeros(100, bool)
    out[80:] = True                            # 20 个域外，全错
    pred = pred_good_in.copy()
    pred[out] = 1 - pred[out]
    r = GA.forced_prediction_test(y, pred, out)
    assert r["verdict"] == "passthru_justified"

    pred_equal = pred_good_in.copy()           # 域外也不错 -> 无差异
    r2 = GA.forced_prediction_test(y, pred_equal, out)
    assert r2["verdict"] == "passthru_unfounded"


def test_actionability_summary_refuses_to_praise_coverage_without_power():
    rows = GA.sweep([0.1] * 50 + [0.9] * 50,
                    np.array([1, 0] * 50), np.array([1, 1] * 50))
    s = GA.actionability_summary(rows, 0.35)
    assert s["gate_verdict"] == "not_measured"
    assert "不得" in s["passthru_interpretation"]

    power = GA.discriminative_power([0.1] * 50 + [0.9] * 50,
                                    np.array([1, 0] * 50), np.array([1, 1] * 50))
    s2 = GA.actionability_summary(rows, 0.35, power=power)
    assert s2["gate_verdict"] in ("informative", "uninformative")
    assert s2["gate_power"]["auc"] == power["auc"]


# --------------------------------------------------------------- R14
def test_mmp_status_is_directional_not_a_bare_not_equivalent():
    """旧的 status 只有 NOT_equivalent 一个字符串，方向信息全丢。"""
    assert "equivalent" == mmp._overall_status(0.0, True, 0.10)
    ins = mmp._overall_status(-0.13, False, 0.10)
    over = mmp._overall_status(+0.13, False, 0.10)
    assert "insensitive" in ins and "oversensitive" not in ins
    assert "oversensitive" in over and "insensitive" not in over
    assert ins != over
    # 迟钝必须明确禁止被叙述成"稳定"
    assert "禁止" in mmp._overall_interpretation(-0.13, False, 0.10)


def _cliff_blind_pairs(n_pairs, label_rate=0.2):
    """构造"模型从不翻转、标签按 label_rate 翻转"的合成 MMP 对。"""
    labels, probs, pairs = [], [], []
    step = max(1, int(round(1.0 / label_rate)))
    for k in range(n_pairs):
        i, j = 2 * k, 2 * k + 1
        flip = (k % step == 0)
        labels += [1.0, 0.0 if flip else 1.0]
        probs += [0.80, 0.79]                    # 模型几乎不动 -> 从不翻转
        pairs.append(("c%d" % k, i, j, "C", "O"))
    return pairs, labels, probs


def test_mmp_power_block_refuses_to_judge_on_small_samples():
    """n=20 对时连完美模型也判不了等效 -> 必须报 insufficient_power，不许报迟钝。"""
    pairs, labels, probs = _cliff_blind_pairs(20)
    res = mmp.analyze(pairs, labels, probs, equiv_margin=0.10)
    assert res["power"]["adequate"] is False
    assert res["direction"] == "insufficient_power"
    assert "INSUFFICIENT_POWER" in res["status"]
    assert "不得" in res["interpretation"]


def test_mmp_analyze_reports_direction_on_synthetic_cliff_blind_model():
    """合成数据：20% 的 MMP 对标签真的翻转，但模型概率几乎不动 → 必须判 insensitive。

    这正是 hERG / BBB 真实数据的形态（标签翻转 13–16%，模型翻转 0–5%），
    它必须被判为**失败**，而不是被判为"稳定"。样本量取 120 对以保证功效充足。
    """
    pairs, labels, probs = _cliff_blind_pairs(120)

    res = mmp.analyze(pairs, labels, probs, equiv_margin=0.10)
    assert res["power"]["adequate"] is True
    assert res["overall"]["label_change_rate"] == 0.2
    assert res["overall"]["model_flip_rate"] == 0.0
    assert res["overall"]["tost_equivalent"] is False
    assert res["direction"] == "insensitive"
    assert "禁止" in res["interpretation"]


# ------------------------------------------------- 黑4：召回/特异度拆分
def test_cliff_recall_and_specificity_are_reported_separately():
    """单一翻转率读不出召回：模型完全不动时 recall=0 而 specificity=1。"""
    pairs, labels, probs = _cliff_blind_pairs(120)
    res = mmp.analyze(pairs, labels, probs, equiv_margin=0.10)
    o = res["overall"]
    assert o["cliff_recall"] == 0.0, "从未翻转 -> 悬崖召回必须为 0"
    assert o["flat_specificity"] == 1.0, "从未翻转 -> 对未变对全部守静"
    assert o["cliff_recall_n"] + o["flat_n"] == res["n_pairs"]


def test_cliff_recall_is_one_for_oracle_like_model():
    pairs, labels, _ = _cliff_blind_pairs(120)
    oracle = [0.95 if l > 0.5 else 0.05 for l in labels]   # 完全跟着标签
    res = mmp.analyze(pairs, labels, oracle, equiv_margin=0.10)
    assert res["overall"]["cliff_recall"] == 1.0
    assert res["overall"]["flat_specificity"] == 1.0


# ------------------------------------------------- 黑2：回归支与守卫
def test_analyze_rejects_continuous_labels():
    pairs, labels, probs = _cliff_blind_pairs(40)
    cont = [0.3 + 0.01 * i for i in range(len(labels))]
    try:
        mmp.analyze(pairs, cont, probs)
    except ValueError as e:
        assert "analyze_regression" in str(e)
    else:
        raise AssertionError("连续标签必须被拒绝，否则每对都会被判成翻转")


def test_analyze_regression_separates_compressed_from_insensitive():
    """R<1 有两种来源：幅度压缩（方向对）与结构迟钝（方向也错）。

    2026-11-01 实测驱动的这条拆分：脂溶性 4636 对上 R=0.32 被判 insensitive，
    但符号一致率 0.73。若不拆，会把"回归到均值"误报成"结构迟钝"，
    与 P8 旧版"把缺陷当优点"是同一类错误的镜像。
    """
    n = 60
    pairs, ys, dpreds_dir, dpreds_rand = [], [], [], []
    for k in range(n):
        i, j = 2 * k, 2 * k + 1
        ys += [1.0, 1.0 + 0.5]                 # 真实 Δ 恒为 +0.5
        dpreds_dir += [1.0, 1.0 + 0.02]        # 同向、幅度 1/25 → 压缩
        # 一半同向、一半反向：幅度仍是 0.02，但方向不再有信息
        dpreds_rand += [1.0, 1.0 + (0.02 if k % 2 == 0 else -0.02)]
        pairs.append(("c%d" % k, i, j, "C", "O"))

    r = mmp.analyze_regression(pairs, ys, dpreds_dir, n_boot=600)
    assert r["power"]["adequate"] is True
    assert r["direction"] == "compressed", r["direction"]
    assert r["sign_agreement"] == 1.0
    assert r["overall"]["displacement_ratio"] < 0.2
    assert "回归到均值" in r["interpretation"]

    r1 = mmp.analyze_regression(pairs, ys, dpreds_rand, n_boot=600)
    assert r1["overall"]["displacement_ratio"] < 0.2     # 幅度同样小
    assert r1["direction"] == "insensitive", r1["direction"]
    assert r1["sign_z"] < r1["sign_z_floor"]

    dpreds_ok = []
    for k in range(n):
        dpreds_ok += [1.0, 1.0 + 0.5]           # 模型幅度与标签一致
    r2 = mmp.analyze_regression(pairs, ys, dpreds_ok, n_boot=600)
    assert r2["direction"] == "equivalent"


def test_analyze_regression_flags_insufficient_power():
    pairs, ys, dpreds = [], [], []
    for k in range(10):
        i, j = 2 * k, 2 * k + 1
        ys += [1.0, 1.5]
        dpreds += [1.0, 1.01]
        pairs.append(("c%d" % k, i, j, "C", "O"))
    r = mmp.analyze_regression(pairs, ys, dpreds, n_boot=300)
    assert r["power"]["adequate"] is False
    assert r["direction"] == "insufficient_power"


# ---------------------------------------------------------------- P2.4-b 回归
# 2026-11-03：一句机器生成的判读，在 DILI（AUC 0.668 > 0.65）上被写成
# "点估计低于工作点 0.65" —— 工具自己造谣。根因是那句话写死成 hERG 的叙事。
# 下面这组测试锁死：判读**必须**由 (点估计, CI) 联合决定，且两种状态不许混说。


def _perfect_separation():
    """构造一个门确实有效的场景：正确性完全由 sim 排序决定（AUC=1）。"""
    import numpy as np
    y = np.array([1] * 50 + [0] * 50)
    sims = [0.9] * 50 + [0.1] * 50
    pred = y.copy()
    pred[50:] = 1 - pred[50:]                 # 低相似度的 50 条全预测错
    return sims, y, pred


def test_ci_state_informative_supported_requires_ci_lower_above_floor():
    sims, y, pred = _perfect_separation()
    p = GA.discriminative_power(sims, y, pred,
                                auc_ci={"lo": 0.90, "hi": 1.00, "method": "test"})
    assert p["verdict"] == "informative"
    assert p["verdict_ci"] == "informative_supported"
    assert "判别力" in p["interpretation"]


def test_interpretation_never_claims_below_floor_when_point_is_above():
    """点估计 > 工作点但 CI 下界 < 工作点：只能说"未证实"，绝不能说"低于"。"""
    sims, y, pred = _perfect_separation()
    p = GA.discriminative_power(sims, y, pred,
                                auc_ci={"lo": 0.50, "hi": 0.80, "method": "test"})
    assert p["auc"] >= p["auc_floor"]
    assert p["verdict_ci"] == "informative_unconfirmed"
    assert "高于工作点" in p["interpretation"]
    assert "低于工作点" not in p["interpretation"]


def test_ci_state_uninformative_supported_only_when_upper_below_floor():
    """区间上界也低于工作点，才允许说"已证明无判别力"。"""
    import numpy as np
    y = np.array([1] * 50 + [0] * 50)
    sims = [0.5] * 100                        # 分数全平 -> AUC 0.5
    pred = np.array([1] * 50 + [0] * 50)
    pred[::2] = 1 - pred[::2]                 # 打乱正确性，使 sim 无信息
    p = GA.discriminative_power(sims, y, pred,
                                auc_ci={"lo": 0.40, "hi": 0.60, "method": "test"})
    assert p["verdict_ci"] == "uninformative_supported"
    assert "禁止" in p["interpretation"]


def test_no_ci_state_refuses_to_conclude():
    sims, y, pred = _perfect_separation()
    p = GA.discriminative_power(sims, y, pred)
    assert p["auc_ci"] is None
    assert p["verdict_ci"] == "no_ci"
    assert "未提供 95" in p["interpretation"]


def test_forced_prediction_reports_interval_not_just_p_value():
    """p 大不等于"证明了没差异"；必须给差值区间并声明功效不足。"""
    import numpy as np
    y = np.array([1] * 50 + [0] * 50)
    pred = y.copy()
    pred[45:50] = 1 - pred[45:50]             # 5 条错，全在域内
    out = np.zeros(100, bool)
    out[80:] = True                           # 20 条域外，全对
    r = GA.forced_prediction_test(y, pred, out)
    assert r["diff_ci"] is not None
    for k in ("diff", "lo", "hi"):
        assert isinstance(r["diff_ci"][k], float)
    if r["fisher_p"] >= 0.05:
        assert "功效不足" in r["interpretation"] or "跨 0" in r["interpretation"]
