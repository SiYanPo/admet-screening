# -*- coding: utf-8 -*-
"""P1 回归测试（评审 v4.0，C1/C10 致命修复）：n_eff 截断 + ρ<0 冲突分流。

覆盖：
  - 负相关 ρ=-0.574 / ρ=-0.999 必须触发 source_conflict（不收缩、不放大等效票）
  - ρ=+0.594 方向确定（ci_lo>0）→ 收缩为 1/(1+0.594)=0.6274
  - ρ=+0.594 但 CI 含 0 → 按 ρ=0 计，不收缩（weight=1.0）
  - 无 ρ 数据 → inconclusive，保守不收缩
  - ρ=0 方向确定 → 收缩为 1.0
"""
import math
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adt.independence import rho_contraction_weight, SOURCE_CONFLICT_REASON


def test_negative_rho_triggers_source_conflict():
    # 报告 badcase 1 实证：hERG ρ=-0.574，CI 不含 0
    w, status, note = rho_contraction_weight(-0.574, ci_lo=-0.78, ci_hi=-0.30)
    assert status == "source_conflict", note
    assert w == 1.0
    # 极端负相关
    w2, s2, _ = rho_contraction_weight(-0.999, ci_lo=-1.0, ci_hi=-0.95)
    assert s2 == "source_conflict"
    assert w2 == 1.0


def test_positive_rho_contracts_when_ci_direction_certain():
    # F7 合成基准"真基准 max ρ=0.594"：方向确定时收缩
    w, status, note = rho_contraction_weight(0.594, ci_lo=0.41, ci_hi=0.72)
    assert status == "contracted", note
    assert abs(w - 1.0 / (1.0 + 0.594)) < 1e-3


def test_positive_rho_no_contraction_when_ci_spans_zero():
    # CI 含 0：方向不确定，按 ρ=0 计，不收缩（防止滥用收缩掩盖不确定性）
    w, status, note = rho_contraction_weight(0.594, ci_lo=-0.10, ci_hi=0.85)
    assert status == "independent", note
    assert w == 1.0


def test_no_rho_data_is_inconclusive_no_contraction():
    w, status, note = rho_contraction_weight(None)
    assert status == "inconclusive"
    assert w == 1.0


def test_zero_rho_contracts_to_one():
    # ρ=0 且 CI 方向确定为正（下界>0）→ 收缩公式给出 1/(1+0)=1.0
    w, status, _ = rho_contraction_weight(0.0, ci_lo=0.05, ci_hi=0.20)
    assert status == "contracted"
    assert w == 1.0


def test_source_conflict_reason_constant():
    assert SOURCE_CONFLICT_REASON == "source_conflict"


def test_contraction_increases_monotonically_with_rho():
    # 收缩权重应随 ρ 增大单调下降（ρ 越大越冗余），且永不低于 0.5（min_weight 等价）
    prev = 1.0
    for rho in (0.1, 0.3, 0.5, 0.7, 0.9):
        # ci_lo 严格为正（方向确定）才能进入 contracted 分支
        w, status, _ = rho_contraction_weight(rho, ci_lo=rho - 0.02, ci_hi=rho + 0.02)
        assert status == "contracted"
        assert w < prev + 1e-9
        assert w >= 0.5 - 1e-9
        prev = w


if __name__ == "__main__":
    for fn in (v for k, v in sorted(globals().items()) if k.startswith("test_")):
        fn()
        print("ok:", fn.__name__)
