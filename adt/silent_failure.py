# -*- coding: utf-8 -*-
"""静默失败率与置信-误差对齐审计（2026-11-19；100 篇精读移植 #2）。

## 文献依据（真实 PMID，精读语料）
- PMID 42003704 / DOI 10.1080/1062936X.2026.2658500（组1[5]）：明确定义 silent failure
  = "confident but incorrect predictions"，两阶段局部方差 + split conformal 把失败率
  从 12.02% 降到 1.8%；覆盖率 0.952 vs 0.880；区间宽度 1.20 vs 1.63（26% 信息效率）。
- PMID 39005492 / DOI 10.1016/j.patter.2024.100991（组4[95]）：Softmax 对 OOD 样本
  "overconfident mispredictions"，normalizing flow 替换以缓解。
- PMID 42734510 / DOI 10.1021/acs.jcim.6c01878（组4[84]）：多模态精度提升"generally not
  statistically significant"，但 prediction error 与 estimated uncertainty 对齐显著改善。
  这是"数值好看但不显著"的负结果锚点。

## 为什么需要
本 skill 工作包 J 的 silent_empty_source 是"空源"，不等于"自信但错误"。
一个高置信的错误预测会直接通过所有现有门禁——这是真实盲点。
本模块把 silent failure 变成可判定、可门禁的一等指标，且**不把 conformal 升级为独立证明**。

## 诚实边界
* 需要真值标签；无标签时只能报 confidence 分布，不能报 failure rate。
* "高置信"阈值是声明性默认值，须在目标化学类上冻结（不是普适真理）。
* 对齐改善 ≠ 模型更准；只说明不确定性排序更有信息。
"""

from __future__ import annotations

import math


def _quantile(xs, q):
    xs = sorted(xs)
    if not xs:
        return None
    pos = (len(xs) - 1) * q
    lo, hi = int(math.floor(pos)), int(math.ceil(pos))
    return xs[lo] if lo == hi else xs[lo] * (hi - pos) + xs[hi] * (pos - lo)


def silent_failure_rate(confidence, correct, threshold=0.8, min_n=10):
    """统计"高置信但错误"的样本占比（silent failure rate, SFR）。

    confidence: 0..1 的置信度序列（须与 probability 非共线，见 trust.py 纪律）；
    correct: 对应 bool/0-1 的正确性序列。
    """
    n = min(len(confidence), len(correct))
    if n < min_n:
        return dict(
            verdict="INDETERMINATE",
            reason="n=%d < %d，不报 SFR" % (n, min_n),
            n=n,
            human_confirmation_required=True,
        )
    conf = [float(c) for c in confidence][:n]
    cor = [bool(c) for c in correct][:n]
    high = [i for i, c in enumerate(conf) if c >= threshold]
    if not high:
        return dict(
            verdict="NO_HIGH_CONFIDENCE",
            reason="无样本达到置信阈值 %.2f" % threshold,
            n=n,
            n_high=0,
            threshold=threshold,
            human_confirmation_required=True,
        )
    n_high = len(high)
    n_wrong = sum(1 for i in high if not cor[i])
    sfr = n_wrong / float(n_high)
    overall_err = sum(1 for c in cor if not c) / float(n)
    # 高置信组的错误率应显著低于整体；否则置信度没有信息
    enrichment = (sfr / overall_err) if overall_err > 0 else 0.0
    verdict = "ALARM" if sfr > 0.10 else ("WARN" if sfr > 0.05 else "OK")
    return dict(
        verdict=verdict,
        n=n,
        n_high=n_high,
        n_high_wrong=n_wrong,
        silent_failure_rate=round(sfr, 4),
        overall_error_rate=round(overall_err, 4),
        error_enrichment_in_high_conf=round(enrichment, 4),
        threshold=threshold,
        reason=(
            "高置信组错误率 %.1f%%（%d/%d），阈值 %%>10%% 为 ALARM"
            "；置信度信息比 = 高置信错误率/整体错误率 = %.2f"
            % (sfr * 100, n_wrong, n_high, enrichment)
        ),
        evidence="PMID 42003704 (SFR 12.02%→1.8%); PMID 39005492 (OOD overconfidence)",
        human_confirmation_required=True,
        not_a_claim_of="模型正确性 / conformal 有效性 / 因果解释",
    )


def confidence_error_alignment(confidence, abs_error, bins=5, min_per_bin=3):
    """置信分箱 vs 平均绝对误差：单调下降才算"置信度有排序信息"。

    返回每箱 (n, mean_conf, mean_abs_error) 与 Spearman 秩相关 ρ(conf, abs_error)。
    ρ 应显著为负；若 ≥0 说明高置信反而误差大 → 置信度不可用。
    """
    n = min(len(confidence), len(abs_error))
    if n < max(bins * min_per_bin, 10):
        return dict(
            verdict="INDETERMINATE",
            reason="样本不足 n=%d" % n,
            n=n,
            human_confirmation_required=True,
        )
    conf = [float(c) for c in confidence][:n]
    err = [abs(float(e)) for e in abs_error][:n]
    order = sorted(range(n), key=lambda i: conf[i])
    groups = []
    for b in range(bins):
        idx = order[b * n // bins : (b + 1) * n // bins]
        if not idx:
            continue
        groups.append(
            dict(
                bin=b + 1,
                n=len(idx),
                mean_conf=round(sum(conf[i] for i in idx) / len(idx), 4),
                mean_abs_error=round(sum(err[i] for i in idx) / len(idx), 4),
            )
        )
    # 秩相关（复用 evidence_streams 的实现，避免重复）
    try:
        from .evidence_streams import _spearman
    except ImportError:  # 兼容 `python adt/silent_failure.py --selftest` 直接运行
        import os as _os, sys as _sys

        _sys.path.insert(
            0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
        )
        from adt.evidence_streams import _spearman
    rho = _spearman(conf, err)
    mono = all(
        groups[i]["mean_abs_error"] >= groups[i + 1]["mean_abs_error"] - 1e-9
        for i in range(len(groups) - 1)
    )
    ok = rho is not None and rho < -0.2
    return dict(
        verdict=("ALIGNED" if (ok and mono) else ("PARTIAL" if ok else "MISALIGNED")),
        bins=groups,
        rho_conf_vs_abs_error=(round(rho, 4) if rho is not None else None),
        monotone_decreasing=mono,
        n=n,
        reason=(
            "ρ(conf,|error|)=%s；单调下降=%s。ρ<-0.2 且单调才算对齐"
            % (("%.3f" % rho) if rho is not None else "n/a", mono)
        ),
        evidence="PMID 42734510 (error-uncertainty alignment improved though accuracy gains ns)",
        human_confirmation_required=True,
    )


def selftest():
    rows = []

    def chk(name, cond, detail=""):
        rows.append(dict(name=name, ok=bool(cond), detail=detail))

    n = 40
    conf = [0.95 if i < 20 else 0.55 for i in range(n)]
    cor = [True] * 18 + [False] * 2 + [True] * 12 + [False] * 8  # 高置信组 2/20 错
    s = silent_failure_rate(conf, cor, threshold=0.8)
    # 2/20 = 0.10 → WARN（ALARM 阈值是 >0.10，严格大于）
    chk(
        "sfr_computes",
        s["verdict"] == "WARN"
        and s["n_high_wrong"] == 2
        and abs(s["silent_failure_rate"] - 0.1) < 1e-9,
        "verdict=%s sfr=%s" % (s["verdict"], s.get("silent_failure_rate")),
    )
    bad = silent_failure_rate([0.95] * 20, [True] * 5 + [False] * 15)
    chk("sfr_alarm_on_overconfidence", bad["verdict"] == "ALARM", bad["verdict"])
    small = silent_failure_rate([0.9, 0.8], [True, False])
    chk("small_n_indeterminate", small["verdict"] == "INDETERMINATE", "")
    # 对齐：置信高→误差小
    c = [0.1 + 0.02 * i for i in range(n)]
    e = [1.0 - 0.02 * i for i in range(n)]
    al = confidence_error_alignment(c, e, bins=5)
    chk(
        "alignment_detected",
        al["verdict"] == "ALIGNED",
        "rho=%s" % al["rho_conf_vs_abs_error"],
    )
    mis = confidence_error_alignment(c, list(reversed(e)), bins=5)
    chk(
        "misalignment_detected",
        mis["verdict"] != "ALIGNED",
        "rho=%s" % mis["rho_conf_vs_abs_error"],
    )
    return all(x["ok"] for x in rows), rows


if __name__ == "__main__":
    import argparse, json

    ap = argparse.ArgumentParser(prog="silent-failure")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        ok, rows = selftest()
        for r in rows:
            print(
                "[%s] %s %s"
                % ("OK" if r["ok"] else "FAIL", r["name"], r["detail"][:60])
            )
        print("[silent-failure] %s" % ("PASS" if ok else "FAIL"))
        raise SystemExit(0 if ok else 4)
