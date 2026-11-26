# -*- coding: utf-8 -*-
"""红线 7–9 的回归断言（第三轮评审 §G）。

每条红线都必须成对断言：
- **违反时必须抛 RedLineError**（否则它只是建议，不是红线）；
- **合规时必须放行**（否则它会被绕过：把护栏做成"永远报错"等于没有护栏）。

外加一条元断言：`red_lines_status()` 必须真的登记 9 条——防止"加了守卫但忘了登记"，
那样发布门禁 G8 读不到它，红线等于没上。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adt import guards as G  # noqa: E402


# --------------------------------------------------------------- 登记完整性
def test_nine_red_lines_registered():
    st = G.red_lines_status()
    assert len(st) == 9, "红线必须 9 条，实际 %d 条：%s" % (len(st), list(st))
    assert all(v["ok"] for v in st.values())
    # 每条都要有落地位置与测试文件，否则无法审计
    for k, v in st.items():
        assert v["where"], "%s 缺落地位置" % k
        assert v["test"], "%s 缺测试文件" % k


# --------------------------------------------------------------- 红线 7
class TestRedLine7GateDistribution:
    """gate 判别力数字必须带评测分布标注；域内 AUC 不能用来评价门。"""

    def test_raises_without_distribution(self):
        with pytest.raises(G.RedLineError) as e:
            G.gate_distribution_line("hERG 上 gate AUC 0.580，说明域外弃权无效")
        assert "红线7" in str(e.value)
        assert "评测分布" in str(e.value)

    def test_raises_on_invalid_distribution(self):
        with pytest.raises(G.RedLineError):
            G.gate_distribution_line("gate 判别力 AUC 0.58", eval_distribution="whatever")

    def test_raises_in_domain_honesty_claim(self):
        # 域内评测下声称"域外诚实"是自相矛盾，必须拦
        with pytest.raises(G.RedLineError) as e:
            G.gate_distribution_line("gate 在域内评测表现良好，域外弃权是诚实的",
                                     eval_distribution="in_domain")
        assert "域内" in str(e.value)

    def test_raises_low_auc_honesty_claim(self):
        with pytest.raises(G.RedLineError):
            G.gate_distribution_line("本框架域外弃权可靠", eval_distribution="out_of_domain",
                                     auc=0.58)

    def test_passes_compliant_claim(self):
        r = G.gate_distribution_line(
            "在域外强制预测实验（out_of_domain）中 gate AUC 0.58，"
            "PASSTHRU 覆盖率不代表谨慎程度",
            eval_distribution="out_of_domain", auc=0.58, endpoint="hERG")
        assert r["ok"] and r["triggered"]

    def test_passes_unrelated_text(self):
        r = G.gate_distribution_line("这批分子的 logP 中位数是 2.3")
        assert r["ok"] and not r["triggered"]


# --------------------------------------------------------------- 红线 8
class TestRedLine8ExternalProvenance:
    """post-cutoff 外源数字必须同句标注"非预注册前瞻"。"""

    def test_raises_forbidden_prospective_phrase(self):
        with pytest.raises(G.RedLineError) as e:
            G.provenance_line("post-cutoff 外源留出 AUC 0.581，前瞻验证通过")
        assert "红线8" in str(e.value)

    def test_raises_missing_annotation(self):
        with pytest.raises(G.RedLineError) as e:
            G.provenance_line("post-cutoff 外源留出集上 AUC 0.581")
        assert "非预注册" in str(e.value)

    def test_passes_with_annotation(self):
        r = G.provenance_line(
            "post-cutoff 外源留出（n=9443，非预注册前瞻）AUC 0.581 [0.569, 0.593]")
        assert r["ok"] and r["triggered"]

    def test_passes_unrelated_text(self):
        r = G.provenance_line("TDC hERG test 集 AUC 0.792")
        assert r["ok"] and not r["triggered"]


# --------------------------------------------------------------- 红线 9
class TestRedLine9EndpointPlurality:
    """端点依赖类结论必须三端点并列，禁单端点外推。"""

    def test_raises_single_endpoint_without_scope(self):
        with pytest.raises(G.RedLineError) as e:
            G.endpoint_plurality_line("模型对活性悬崖迟钝", endpoints=["hERG"])
        assert "红线9" in str(e.value)

    def test_raises_global_claim_with_two_endpoints(self):
        with pytest.raises(G.RedLineError):
            G.endpoint_plurality_line("所有端点上模型对活性悬崖都迟钝",
                                      endpoints=["hERG", "BBB_Martins"])

    def test_passes_three_endpoints(self):
        r = G.endpoint_plurality_line(
            "模型对活性悬崖迟钝；DILI 因功效不足不判",
            endpoints=["hERG", "DILI", "BBB_Martins"])
        assert r["ok"] and r["n_endpoints"] == 3

    def test_passes_explicit_single_endpoint_scope(self):
        r = G.endpoint_plurality_line("单端点结论：hERG 上模型对活性悬崖迟钝，不外推",
                                      endpoints=["hERG"])
        assert r["ok"] and r["scoped_only"] is True

    def test_passes_unrelated_text(self):
        r = G.endpoint_plurality_line("这批分子共 14 个")
        assert r["ok"] and not r["triggered"]


# --------------------------------------------------------------- 红线常量
def test_gate_auc_min_convention():
    assert G.GATE_AUC_MIN == 0.65, "0.65 是约定值（GATE_AND_P8_MMP §1.4），不得静默改动"


def test_antifact_recorded_for_each_new_line():
    st = G.red_lines_status()
    for k in ("7_gate_eval_distribution", "8_external_not_preregistered",
              "9_endpoint_plurality"):
        assert st[k].get("antifact"), "%s 必须记录反例出处" % k


# --------------------------------------------------------------- C3（2026-11-03 评审）
class TestRedLine7CIRequirement:
    """C3：红线 7 的判据从"点估计 < 约定值"改为"必须给 95% CI，且看上界"。

    为什么：0.65 是约定工作点（无文献、无功效分析），点估计在端点级 n<500 时
    SE≈0.02–0.03——用点估计与约定值比较，等于用噪声与人为阈值比较。
    """

    def test_honesty_claim_requires_ci(self):
        with pytest.raises(G.RedLineError) as e:
            G.gate_distribution_line("本框架域外弃权可靠",
                                     eval_distribution="out_of_domain", auc=0.72)
        assert "95" in str(e.value) and "CI" in str(e.value)

    def test_ci_upper_below_workpoint_blocks_claim(self):
        with pytest.raises(G.RedLineError):
            G.gate_distribution_line("本框架域外弃权可靠",
                                     eval_distribution="out_of_domain",
                                     auc=0.62, auc_ci=(0.55, 0.69 - 0.05))

    def test_ci_upper_above_workpoint_allows_claim(self):
        # 点估计 0.62 < 0.65，但 CI 上界 0.71 越过工作点 → 统计上不能否认
        r = G.gate_distribution_line("在域外强制预测中，gate 弃权是诚实的",
                                     eval_distribution="out_of_domain",
                                     auc=0.62, auc_ci=(0.54, 0.71))
        assert r["ok"] and r["auc_ci"] == [0.54, 0.71]

    def test_invalid_ci_rejected(self):
        with pytest.raises(G.RedLineError):
            G.gate_distribution_line("域外弃权可靠", eval_distribution="out_of_domain",
                                     auc=0.7, auc_ci=(0.9, 0.5))

    def test_no_ci_needed_without_honesty_claim(self):
        r = G.gate_distribution_line(
            "out_of_domain 上 gate AUC 0.58 [0.54, 0.62]，PASSTHRU 覆盖率不代表谨慎程度",
            eval_distribution="out_of_domain", auc=0.58)
        assert r["ok"]


def test_workpoint_is_separate_from_redline():
    """约定工作点与红线判据必须是两个概念，禁止再合并。"""
    assert G.GATE_AUC_WORKPOINT == 0.65
    assert G.GATE_AUC_MIN == G.GATE_AUC_WORKPOINT, "旧名保留兼容，但语义已降级为工作点"
