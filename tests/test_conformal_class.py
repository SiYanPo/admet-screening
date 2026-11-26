# -*- coding: utf-8 -*-
"""类条件（Mondrian）保形：与少数类失效文献对话。"""
import sys
sys.path.insert(0, ".")

from adt import conformal as CF


def test_class_conditional_math_restores_minority():
    # 校准：多数类(0) 非一致性低(0.1)、少数类(1) 非一致性高(0.7)，多数类占 ~91%（类不平衡）
    cal = [(0.1, 0)] * 909 + [(0.3, 1)] * 91
    # 测试：多数类仍 0.1；少数类非一致性漂移到 0.65——低于类条件 q(0.7) 但高于边际 q(0.1)
    # （注意 _cc_score(yhat,1)=1−yhat，故 yhat=0.3→0.7、yhat=0.65→0.35…此处用 (yhat,1) 表示）
    test = [(0.1, 0)] * 2000 + [(0.35, 1)] * 200
    res = CF.evaluate_disjoint(cal, test, alpha=0.1)
    mq, q1 = res["marginal_q"], res["mondrian_q1"]
    # 边际：多数类主导把 q 拉到多数类水平(0.1)，少数类(0.65 非一致性→对应 yhat 0.35) 被踢出 → 低覆盖
    test1 = [(yh, yt) for (yh, yt) in test if int(yt) == 1]
    marg_cov1 = sum(1 for (yh, yt) in test1 if CF._cc_score(yh, yt) <= mq) / len(test1)
    assert marg_cov1 < 0.5, ("边际低覆盖少数类", marg_cov1, res)
    # 类条件：q1 覆盖少数类 → 恢复
    assert res["class_coverage_1"] > marg_cov1, res
    assert res["class_coverage_1"] >= 0.9, res
    # 类条件 q 高于边际 q（少数类校准非一致性更高 → 配额更宽，正是 Mondrian 的修复）
    assert q1 > mq, res
    assert res["flag"] == "ok"
    # 边际整体覆盖率也被少数类拖累（< 1）
    assert res["marginal_coverage"] < 1.0, res


def test_mondrian_q_per_class_differs():
    cal = [(0.1, 0)] * 20 + [(0.5, 1)] * 5
    test = [(0.1, 0)] * 10 + [(0.7, 1)] * 10
    res = CF.evaluate_disjoint(cal, test, alpha=0.1)
    # 两类校准集分布不同 → 类条件 q 应不同
    assert res["mondrian_q0"] != res["mondrian_q1"]


def test_insufficient_calibration_flag():
    # 少数类校准样本不足 → flag 提示
    cal = [(0.1, 0)] * 20 + [(0.5, 1)] * 2
    test = [(0.1, 0)] * 10 + [(0.7, 1)] * 10
    res = CF.evaluate_disjoint(cal, test, alpha=0.1)
    assert "insufficient" in res["flag"]


def test_self_calibrated_demo_structure():
    # 闭合演示（同集）应返回完整结构（不暴露失效但结构正确）
    pairs = [(0.9, 0)] * 20 + [(0.2, 1)] * 5
    res = CF.class_conditional_coverage(pairs, alpha=0.1)
    assert "marginal_coverage" in res
    assert "class_coverage_0" in res and "class_coverage_1" in res
    assert "minority_coverage_gap" in res


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
