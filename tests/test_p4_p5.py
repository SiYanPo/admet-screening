# -*- coding: utf-8 -*-
"""P4（配对 McNemar，C7）/ P5（略优审计护栏，C2）回归测试。"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adt import phrasing, prospective


def test_flag_unqualified_superiority_catches_lueyou():
    hits = phrasing.flag_unqualified_superiority("仅单位守卫 7.83% 略优，提示方向一致")
    assert "略优" in hits
    # 已携带 CI/检验则豁免
    assert phrasing.flag_unqualified_superiority(
        "差异 0.45pp（95% CI [-1.2, 1.3]，含 0）", has_ci_or_test=True) == []


def test_flag_unqualified_superiority_english():
    assert "slightly better" in phrasing.flag_unqualified_superiority(
        "method A is slightly better than B")


def _make_verdicts(correct_keys_a, correct_keys_b, all_keys, truth_val="PASS"):
    truth = {k: truth_val for k in all_keys}
    va = {k: ("PASS" if k in correct_keys_a else "FAIL", 0.0) for k in all_keys}
    vb = {k: ("PASS" if k in correct_keys_b else "FAIL", 0.0) for k in all_keys}
    return va, vb, truth


def test_flag_truth_consistency_claim_by_n():
    """R12（A2/C2）：n=2 的"与真值一致"必须被拦；分级只由 n 决定，不由措辞决定。"""
    s = "裁决与独立真值一致——Diclofenac DILI=FAIL"
    r = phrasing.flag_truth_consistency_claim(s, n=2)
    assert r["hits"] and r["level"] == "blocked"
    assert "不构成验证" in r["advice"]
    assert phrasing.flag_truth_consistency_claim(s, n=60)["level"] == "point_estimate"
    assert phrasing.flag_truth_consistency_claim(s, n=300)["level"] == "statistical"
    # 未声明 n 也不放过（不许靠"不说样本量"绕过）
    assert phrasing.flag_truth_consistency_claim(s)["level"] == "unknown"
    # 合规表述不误伤
    assert phrasing.flag_truth_consistency_claim("未观察到与已知药理矛盾")["level"] == "clean"


def test_paired_mcnemar_detects_difference():
    """R09：n_paired 是"可配对单元数"，不连续一致对数；b/c 才是不一致格。"""
    keys = list(range(40))
    # A 对前 30（0-29）；B 对后 30（10-39）→ 0-9 A对B错(10)，30-39 A错B对(10)，10-29 都對
    correct_a = set(range(30))
    correct_b = set(range(10, 40))
    va, vb, truth = _make_verdicts(correct_a, correct_b, keys)
    r = prospective.paired_mcnemar(va, vb, truth, a_name="S4_full_admission",
                                   b_name="S1_naive_majority", set_name="unit-test")
    # 配对单元 = 40（全部都有 PASS/FAIL 且 truth 已知）
    assert r["n_paired"] == 40
    # 不一致 = 20，b=c=10；两侧对称 → Δ=0，p=1
    assert r["n_discordant"] == 20
    assert r["b"] == 10 and r["c"] == 10
    assert r["n_both_correct"] == 20 and r["n_both_wrong"] == 0
    assert abs(r["delta_acc_a_minus_b"]) < 1e-9
    assert r["p_two_sided"] == 1.0 and not r["significant"]
    # 检验对象必须回写在返回值里（R1-4 的核心诉求）
    assert r["object"]["a"] == "S4_full_admission"
    assert r["object"]["b"] == "S1_naive_majority"
    assert r["object"]["set"] == "unit-test"
    assert r["object"]["unit"] == "(compound_id, endpoint)"
    assert "配对单元" in r["definition"]


def test_paired_mcnemar_one_sided_and_effect_sign():
    """单侧检验必须显式声明；方向 = A−B，正号代表 A 更准。"""
    keys = list(range(100))
    va, vb, truth = _make_verdicts(set(range(80)), set(range(20)), keys)
    r = prospective.paired_mcnemar(va, vb, truth, alternative="greater")
    assert r["object"]["alternative"] == "greater"
    assert r["b"] == 60 and r["c"] == 0            # A 显著更准
    assert r["delta_acc_a_minus_b"] > 0
    assert r["mcnemar_p"] < 0.001 and r["significant"]
    # 同一数据换成双侧，p 必然是单侧的 2 倍量级（更保守）
    r2 = prospective.paired_mcnemar(va, vb, truth, alternative="two-sided")
    assert r2["mcnemar_p"] >= r["mcnemar_p"]


def test_paired_mcnemar_no_difference():
    keys = list(range(30))
    correct = set(range(25))
    va, vb, truth = _make_verdicts(correct, correct, keys)
    r = prospective.paired_mcnemar(va, vb, truth)
    assert r["n_discordant"] == 0          # 全一致 → 无不一致对
    assert r["mcnemar_p"] == 1.0           # 无差异证据，不是"等价"证明
    assert r["test_informative"] is False
    assert "不等于等价" in r["note"]


def test_paired_mcnemar_abstain_not_paired():
    """ABSTAIN 不得进配对分母（否则 Δ 与 n 不可解释）。"""
    keys = list(range(20))
    truth = {k: "PASS" for k in keys}
    va = {k: ("ABSTAIN", 0.0) for k in keys}
    vb = {k: ("PASS", 0.0) for k in keys}
    r = prospective.paired_mcnemar(va, vb, truth)
    assert r["n_paired"] == 0 and r["mcnemar_p"] is None


if __name__ == "__main__":
    for fn in (v for k, v in sorted(globals().items()) if k.startswith("test_")):
        fn()
        print("ok:", fn.__name__)
