# -*- coding: utf-8 -*-
"""OOS/OOT 偏差检测与处置（2026-11-19；技能市场 100 skill 移植）。

## 来源
`@clawhub_1kalin/pharma-csv-pro` 等（市场组4[87]）原文：
"OOS/OOT detection, stability trending, and GMP-compliant reporting"。
OOS = Out-of-Specification（单点越界）；OOT = Out-of-Trend（趋势偏离）。
这是药品监管已标准化的偏差 taxonomy，本 skill 现有 silent_failure 只抓
"高置信但错误"，不覆盖"数值在规格内但趋势已漂"这一类。

## 与已有模块的区别
- `silent_failure.py`：置信度 vs 正确性（模型行为）
- `threshold_audit.py` / `knn_sensitivity.py`：阈值本身是否冻结/敏感（方法学）
- 本模块：**逐批观测序列相对注册规格/历史趋势的偏差分类 + 处置状态机**（过程控制）

## 诚实边界
* OOT 的"连续同向"判据是声明性默认（n_consecutive=5），须在目标流程上冻结，不是普适真理。
* 本模块只分类与留痕，不自动改判结论；任何 disposition=closed 须人确认。
* 不冒充 GMP 合规——只借其 taxonomy，不声称符合任何监管体系。
"""

from __future__ import annotations

import math

DISPOSITIONS = ("pending_investigation", "confirmed", "attributed", "closed")
ALLOWED_TRANSITIONS = {
    "pending_investigation": ("confirmed",),
    "confirmed": ("attributed",),
    "attributed": ("closed",),
    "closed": (),
}


def _mean(xs):
    return sum(xs) / float(len(xs)) if xs else None


def _sd(xs):
    if len(xs) < 2:
        return None
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def detect(
    series,
    spec_lo=None,
    spec_hi=None,
    n_consecutive=5,
    oot_k=2.0,
    history=None,
    context="",
):
    """对逐批/逐批次的观测序列做 OOS/OOT 分类。

    series: 数值序列（按时间/批次顺序）。
    spec_lo/spec_hi: 注册规格区间；越界即 OOS（单点）。
    history: 历史基线序列（可选）；给定则用它算均值/SD 判趋势，否则用 series 自身前段。
    n_consecutive / oot_k: OOT 规则——连续 n 点同向偏离基线 k·SD。
    """
    vals = [float(v) for v in series if v is not None]
    if not vals:
        return dict(
            verdict="INDETERMINATE",
            reason="空序列",
            context=context,
            human_confirmation_required=True,
        )

    # 数据完整性：NaN/Inf 绝不能被静默判为 IN_CONTROL（偏差检测会形同虚设）。
    # series 已由上面的 float() 转换，非数值会在此前抛错；这里专抓非有限值。
    bad_idx = [i for i, v in enumerate(vals) if not math.isfinite(v)]
    bad_hist = []
    for i, v in enumerate(history if history is not None else []):
        if v is None:
            continue
        try:
            if not math.isfinite(float(v)):
                bad_hist.append(i)
        except (TypeError, ValueError):
            bad_hist.append(i)
    if bad_idx or bad_hist:
        return dict(
            verdict="INVALID_DATA",
            reason="序列或历史基线含非有限值（NaN/Inf）",
            bad_series_indices=bad_idx[:20],
            bad_history_indices=bad_hist[:20],
            context=context,
            human_confirmation_required=True,
        )

    oos = []
    for i, v in enumerate(vals):
        if (spec_lo is not None and v < spec_lo) or (
            spec_hi is not None and v > spec_hi
        ):
            oos.append(
                dict(
                    index=i,
                    value=v,
                    side=("below" if spec_lo is not None and v < spec_lo else "above"),
                )
            )

    # 基线严格取"参考段"，不得把待检尾部算进去：
    # 给定 history 用 history；否则用 series 自身前段（排除最后 n_consecutive 点），
    # 与 docstring "否则用 series 自身前段" 的契约一致。
    # 旧实现用整段 vals 当基线 → 尾部越极端，mu/SD 被拖偏越大，OOT 被系统性掩盖（漏报）。
    if history is not None:
        ref = [float(v) for v in history if v is not None]
        baseline_source = "history"
    else:
        ref = (
            vals[:-n_consecutive]
            if (n_consecutive > 0 and len(vals) > n_consecutive)
            else []
        )
        baseline_source = "series_prefix"
    mu, sd = _mean(ref), _sd(ref)
    oot = []
    # 不要求 sd>0：sd==0（基线完全平稳）时阈值=mu，尾部严格偏离 mu 即为 OOT；
    # oot_k 必须为正，否则阈值反向会导致假阳性。
    if mu is not None and sd is not None and oot_k > 0:
        tail = (
            vals[-n_consecutive:]
            if (n_consecutive > 0 and len(vals) >= n_consecutive)
            else []
        )
        if len(tail) == n_consecutive and len(tail) > 0:
            above = [v > mu + oot_k * sd for v in tail]
            below = [v < mu - oot_k * sd for v in tail]
            if all(above):
                oot = dict(
                    direction="above",
                    threshold=round(mu + oot_k * sd, 6),
                    n_consecutive=n_consecutive,
                    values=[round(v, 6) for v in tail],
                )
            elif all(below):
                oot = dict(
                    direction="below",
                    threshold=round(mu - oot_k * sd, 6),
                    n_consecutive=n_consecutive,
                    values=[round(v, 6) for v in tail],
                )

    if oos:
        v = "OOS"
    elif oot:
        v = "OOT"
    else:
        v = "IN_CONTROL"
    return dict(
        verdict=v,
        oos=oos[:20],
        n_oos=len(oos),
        oot=oot or None,
        baseline=dict(
            mean=(round(mu, 6) if mu is not None else None),
            sd=(round(sd, 6) if sd is not None else None),
            source=baseline_source,
        ),
        spec=dict(lo=spec_lo, hi=spec_hi),
        rule=dict(
            n_consecutive=n_consecutive,
            oot_k=oot_k,
            note="声明性默认值，须在目标流程上冻结",
        ),
        disposition=(
            "pending_investigation" if v != "IN_CONTROL" else "not_applicable"
        ),
        context=context,
        human_confirmation_required=True,
        not_a_claim_of="GMP 合规 / 根因已确定 / 偏差已关闭",
    )


def transition(disposition, action):
    """处置状态机；非法跃迁拒绝（不静默放行）。"""
    if disposition not in DISPOSITIONS:
        return dict(ok=False, reason="未知处置状态 %r" % disposition)
    if action not in ALLOWED_TRANSITIONS[disposition]:
        return dict(
            ok=False,
            reason="非法跃迁 %s → %s；允许：%s"
            % (disposition, action, ALLOWED_TRANSITIONS[disposition]),
        )
    return dict(
        ok=True,
        disposition=action,
        note=("关闭须人确认并留痕" if action == "closed" else ""),
    )


def selftest():
    rows = []

    def chk(name, cond, detail=""):
        rows.append(dict(name=name, ok=bool(cond), detail=detail))

    r = detect([1.0, 1.1, 0.9, 2.5, 1.0], spec_lo=0.5, spec_hi=2.0)
    chk("oos_detected", r["verdict"] == "OOS" and r["n_oos"] == 1, str(r["n_oos"]))
    # 趋势偏离：历史稳定，最后5点全在 +2SD 之上
    hist = [10.0 + (i % 3) * 0.01 for i in range(30)]
    trend = hist + [11.0, 11.1, 11.05, 11.02, 11.08]
    r2 = detect(trend, spec_lo=0, spec_hi=100, history=hist, n_consecutive=5, oot_k=2.0)
    chk("oot_detected", r2["verdict"] == "OOT", str(r2["verdict"]))
    r3 = detect([1.0, 1.1, 0.9], spec_lo=0.5, spec_hi=2.0)
    chk("in_control", r3["verdict"] == "IN_CONTROL", r3["verdict"])
    chk("empty_guard", detect([])["verdict"] == "INDETERMINATE", "")
    chk(
        "transition_chain",
        transition("pending_investigation", "confirmed")["ok"]
        and transition("confirmed", "attributed")["ok"]
        and transition("attributed", "closed")["ok"],
        "",
    )
    chk(
        "illegal_transition_rejected",
        transition("pending_investigation", "closed")["ok"] is False,
        "",
    )
    chk("closed_is_terminal", transition("closed", "confirmed")["ok"] is False, "")
    return all(x["ok"] for x in rows), rows


if __name__ == "__main__":
    import argparse, json

    ap = argparse.ArgumentParser(prog="deviation")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        ok, rows = selftest()
        for r in rows:
            print(
                "[%s] %s %s"
                % ("OK" if r["ok"] else "FAIL", r["name"], r["detail"][:60])
            )
        print("[deviation] %s" % ("PASS" if ok else "FAIL"))
        raise SystemExit(0 if ok else 4)
