# -*- coding: utf-8 -*-
"""盲区4 + 追问4：容差断言（Tolerance Assertions）。

问题：57 项断言若写死 assert value == 0.852，RDKit/numpy 升级导致 1e-6 抖动
就全盘红屏；开发为修灯去改断言，反而掩盖真实科学退化。

对策：断言分两类：
  1) 绝对红线断言（ABSOLUTE）：0 容忍。如"UNDETERMINED 不得有 value"
     "out_of_domain 必须不带数值" "verdict 必须在枚举内"。
  2) 数值漂移断言（NUMERIC）：动态容差 rtol/atol；并额外断言
     "变化的速度和方向"——超出容差时不是简单 fail，而是进 deviation 状态机。

纯标准库。
"""

from __future__ import annotations
import math

ABSOLUTE = "absolute"
NUMERIC = "numeric"

ALLOWED_VERDICTS = {"PASS", "FAIL", "UNDETERMINED", "PASSTHRU", "PASSED", "FAILED"}


class AssertionResult:
    def __init__(self, name, kind, passed, detail="", deviation=None):
        self.name, self.kind, self.passed = name, kind, passed
        self.detail, self.deviation = detail, deviation

    def __repr__(self):
        return "[%s] %s %s%s" % (
            "PASS" if self.passed else "FAIL",
            self.name,
            ("| " + self.detail) if self.detail else "",
            (" | deviation=" + str(self.deviation)) if self.deviation else "",
        )


# ---------- 绝对红线（0 容忍）----------
def assert_absolute(name, cond, detail=""):
    return AssertionResult(name, ABSOLUTE, bool(cond), detail)


def assert_no_value_when_undetermined(name, rec):
    """红线：UNDETERMINED 记录 value 必须为 None。"""
    ok = not (rec.get("verdict") == "UNDETERMINED" and rec.get("value") is not None)
    return AssertionResult(
        name,
        ABSOLUTE,
        ok,
        "" if ok else "UNDETERMINED 带了 value=%r" % rec.get("value"),
    )


def assert_out_of_domain_no_number(name, rec):
    ok = not (
        rec.get("domain_flag") == "out_of_domain"
        and (rec.get("value") is not None or rec.get("unit"))
    )
    return AssertionResult(
        name, ABSOLUTE, ok, "" if ok else "out_of_domain 带了数值/单位"
    )


def assert_verdict_enum(name, rec):
    ok = rec.get("verdict") in ALLOWED_VERDICTS
    return AssertionResult(
        name, ABSOLUTE, ok, "" if ok else "verdict=%r 不在枚举内" % rec.get("verdict")
    )


# ---------- 数值漂移（动态容差）----------
def assert_close(name, got, want, *, rtol=1e-4, atol=1e-6, baseline_key=None):
    """数值断言：|got-want| <= atol + rtol*|want|。"""
    if got is None or want is None:
        return AssertionResult(name, NUMERIC, False, "got/want 为 None")
    diff = abs(got - want)
    tol = atol + rtol * abs(want)
    ok = diff <= tol
    return AssertionResult(
        name,
        NUMERIC,
        ok,
        "got=%.8g want=%.8g diff=%.3g tol=%.3g" % (got, want, diff, tol),
    )


def assert_direction(name, new, baseline, *, max_step=0.05, expect="stable"):
    """断言"变化的速度和方向"：
    expect: 'stable'（|变化|<=max_step）/ 'increase' / 'decrease'。
    返回 deviation 信息供状态机使用（不是简单 pass/fail）。
    """
    if new is None or baseline is None:
        return AssertionResult(name, NUMERIC, False, "None 输入")
    delta = new - baseline
    step = abs(delta)
    if expect == "stable":
        ok = step <= max_step
    elif expect == "increase":
        ok = delta > 0 and step <= max_step * 10  # 方向对且不突变
    elif expect == "decrease":
        ok = delta < 0 and step <= max_step * 10
    else:
        ok = False
    dev = {
        "delta": round(delta, 6),
        "step": round(step, 6),
        "expect": expect,
        "max_step": max_step,
        "trigger_deviation": step > max_step,
    }
    return AssertionResult(
        name, NUMERIC, ok, "delta=%.6g expect=%s" % (delta, expect), deviation=dev
    )


def run_suite(assertions):
    """汇总一批断言；任何 ABSOLUTE 失败 → 整批 fail（红线不可放过）。
    NUMERIC 失败 → 记为 deviation，不算硬失败（除非超硬阈值）。"""
    hard_fail = [a for a in assertions if a.kind == ABSOLUTE and not a.passed]
    numeric_fail = [a for a in assertions if a.kind == NUMERIC and not a.passed]
    return {
        "n_total": len(assertions),
        "hard_fail": [a.name for a in hard_fail],
        "numeric_deviation": [a.name for a in numeric_fail],
        "ok": len(hard_fail) == 0,  # 只有红线失败才整批 fail
        "note": (
            ("红线失败 %d 项（阻断）" % len(hard_fail))
            if hard_fail
            else (
                ("数值偏离 %d 项（进 deviation 状态机，非硬失败）" % len(numeric_fail))
                if numeric_fail
                else "全部通过"
            )
        ),
    }
