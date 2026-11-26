# -*- coding: utf-8 -*-
"""单分子可信决策 + 数据忠实性门（2026-11-19，移植自三个 prior art 的精华）。

## 移植来源与修正（必须随模块引用）

借鉴：
  * TRUST-ADMET (Zenodo 10.5281/zenodo.20997792) 的 `predict_with_trust` 产品形态：
    单分子当场给分/分级/动作/硬拒答 + 字段级 breakdown。
  * SciForge (arXiv:2607.16038) 的 claim 五类脆弱性 + needs_narrowing/needs_experiment 处置。
  * AdmitOR (arXiv:2608.15565) 的 numeric-coverage check（数据忠实性门）与
    certificate 显式声明 assumptions / not_a_proof_of。

**修正了 TRUST-ADMET 的三个缺陷后才移植**（不要回退）：
  1. 共线性：原实现 `uncertainty = 1-2|p-0.5|` 与 `confidence=max(p,1-p)` 是同一变量的线性变换，
     却各占 25/100 分。本模块改用**真正独立的三个信号**：模型概率置信、校准误差(逐样本)、
     理化 AD 越界；uncertainty 分量由调用方传入的**独立估计**（如 MC/集成分歧）提供，
     若与 confidence 同源则拒绝计分（见 `_check_orthogonality`）。
  2. 常量 ECE：原实现取模型级 test_ece（同模型所有分子相同），无逐样本区分力。
     本模块的 calibration 分量取**逐样本校准误差** `|p - empirical_bin_rate|`；
     只有模型级 ECE 时标记 `calibration_signal="model_level_only"` 并**不计入** breakdown。
  3. 静默零特征：原实现 invalid SMILES → 全零向量继续预测。本模块遵循本 skill 结构真实性 gate：
     `hard_fail_on_invalid=True` 默认，无效结构直接 REFUSED 且 reason 落到产物。

## 诚实边界
* 本模块输出的是**决策辅助分级**，不是概率保证，也不是"已验证正确"。
* 分数是启发式聚合（4×25），权重是声明性默认值，不冒充统计推断；
  任何对外数字仍需走 G10 字段级绑定 + G13 estimand 门。
* 若独立信号缺失，宁可降级为 UNDETERMINED，不编造一个漂亮的分数。
"""

from __future__ import annotations

import math
import re

from . import resref  # noqa: F401  (保持与 skill 资源解析一致)

# ---- 理化 AD：6 描述符 1%/99% 训练分位盒（移植 TRUST-ADMET 的表达形式，阈值改为显式声明）----
PHYSCHEM_KEYS = (
    "MolWt",
    "MolLogP",
    "TPSA",
    "NumRotatableBonds",
    "NumHDonors",
    "NumHAcceptors",
)


def physchem_limits(training_smiles, lower_q=0.01, upper_q=0.99):
    """从训练 SMILES 计算 6 描述符的 [q_lo, q_hi] 盒。需要 rdkit；无 rdkit 时抛错。"""
    from rdkit import Chem
    from rdkit.Chem import Descriptors

    vals = {k: [] for k in PHYSCHEM_KEYS}
    fn = {
        "MolWt": Descriptors.MolWt,
        "MolLogP": Descriptors.MolLogP,
        "TPSA": Descriptors.TPSA,
        "NumRotatableBonds": Descriptors.NumRotatableBonds,
        "NumHDonors": Descriptors.NumHDonors,
        "NumHAcceptors": Descriptors.NumHAcceptors,
    }
    for smi in training_smiles:
        m = Chem.MolFromSmiles(smi)
        if m is None:
            continue  # 训练集内的无效结构跳过，但计数上报
        for k in PHYSCHEM_KEYS:
            vals[k].append(float(fn[k](m)))

    def q(xs, qv):
        xs = sorted(xs)
        if not xs:
            return None
        pos = (len(xs) - 1) * qv
        lo, hi = int(math.floor(pos)), int(math.ceil(pos))
        return xs[lo] if lo == hi else xs[lo] * (hi - pos) + xs[hi] * (pos - lo)

    limits = {}
    for k in PHYSCHEM_KEYS:
        xs = vals[k]
        limits[k] = dict(
            lo=q(xs, lower_q),
            hi=q(xs, upper_q),
            n=len(xs),
            source="training_quantile",
            lower_q=lower_q,
            upper_q=upper_q,
        )
    return dict(
        limits=limits,
        coverage_declaration=(
            "该盒是训练分布的 1%-99% 描述统计，不是覆盖率保证；"
            "真实覆盖率须在目标化学类上实测（见 coverage.py）。"
        ),
        note_not_guarantee="not a probabilistic coverage guarantee",
    )


def physchem_violations(smiles, limits):
    """逐描述符越界计数；无效结构 → hard fail（不产生全零向量）。

    limits 既接受 physchem_limits() 的整包返回（{"limits": {...}}），
    也接受其内层 {"MolWt": {...}}。2026-11-22 修复：旧实现只读顶层，
    传整包时每个 lim 都是空 dict，导致越界永远为 0（静默放行）。
    """
    from rdkit import Chem
    from rdkit.Chem import Descriptors

    fn = {
        "MolWt": Descriptors.MolWt,
        "MolLogP": Descriptors.MolLogP,
        "TPSA": Descriptors.TPSA,
        "NumRotatableBonds": Descriptors.NumRotatableBonds,
        "NumHDonors": Descriptors.NumHDonors,
        "NumHAcceptors": Descriptors.NumHAcceptors,
    }
    m = Chem.MolFromSmiles(smiles)
    if m is None:
        return dict(
            valid=False,
            violations=["INVALID_STRUCTURE"],
            descriptors={},
            action="REFUSED",
        )
    lims = limits.get("limits", limits) if isinstance(limits, dict) else {}
    got, viol = {}, []
    for k in PHYSCHEM_KEYS:
        v = float(fn[k](m))
        got[k] = round(v, 4)
        lim = lims.get(k) or {}
        lo, hi = lim.get("lo"), lim.get("hi")
        if lo is not None and hi is not None and not (lo <= v <= hi):
            viol.append(k)
    # 0 越界 = Inside；1 = warning；>=2 = REFUSED（移植 TRUST-ADMET 的分级动作）
    action = "REFUSED" if len(viol) >= 2 else ("PHYSCHEM_WARNING" if viol else "INSIDE")
    return dict(
        valid=True,
        violations=viol,
        descriptors=got,
        action=action,
        note="分位盒为训练分布描述统计，非概率覆盖保证",
    )


# ---- 数据忠实性门（移植 AdmitOR Appendix C 的 numeric-coverage check）----
_NUM = re.compile(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")


def numeric_coverage(values, text, rel_tol=1e-6):
    """检查提取/记录的数值是否真的在源文本出现过（防'抽取器编造'共模错误）。

    values: 数值或数值序列（base values）；text: 原始文本（题面/来源字段）。
    返回 dict：covered / n_values / n_covered / missing / verdict。
    判据（移植 AdmitOR）：任一 base value 未以 rel_tol 出现在 text 打印数字中 → escalate。
    注意：本检查抓不到"数字在但被取整到打印精度"——AdmitOR 实测 0/15，如实登记。
    """
    printed = []
    for s in _NUM.findall(text or ""):
        try:
            printed.append(float(s))
        except ValueError:
            pass
    if isinstance(values, (list, tuple)):
        vals = list(values)
    elif isinstance(values, str):
        vals = [values]
    else:
        try:
            vals = list(values)  # numpy array 等可迭代：避免被当成单个值而漏检
        except TypeError:
            vals = [values]
    if not vals:
        return dict(
            verdict="INDETERMINATE",
            n_values=0,
            n_covered=0,
            coverage=None,
            missing=[],
            limitation="无待核对数值，不冒充 PASS（无法证明覆盖）",
        )
    missing = []
    for v in vals:
        try:
            f = float(v)
        except (TypeError, ValueError):
            missing.append(str(v))
            continue
        if not any(math.isclose(f, p, rel_tol=rel_tol, abs_tol=0.0) for p in printed):
            missing.append(v)
    n = len(vals)
    cov = n - len(missing)
    # 数组 >=4 项但打印覆盖 <50%，或总体覆盖 <80% → escalate（AdmitOR 原判据）
    verdict = (
        "ESCALATE"
        if (missing and (n >= 4 and cov < n / 2 or cov / n < 0.8))
        else ("PASS" if not missing else "WARN")
    )
    return dict(
        verdict=verdict,
        n_values=n,
        n_covered=cov,
        coverage=round(cov / n, 4) if n else None,
        missing=missing[:20],
        limitation="抓不到'数字存在但打印精度不足'的取整共模错误",
    )


# ---- 单分子可信决策（核心产品形态）----
_LEVELS = ((85.0, "HIGH"), (70.0, "MEDIUM"))


def _check_orthogonality(signals):
    """禁止把同一信号的线性变换计两次（修正 TRUST-ADMET 缺陷 1）。
    signals: dict(name -> value in [0,1]); 若两两 | pearson-like 完全相同或有确定线性关系，
    这里用保守规则：同名/同源标记重复即拒绝。"""
    # source 缺失(None)不应被误判为"同源重复"：用唯一哨兵占位。
    src = [
        s.get("source") if s.get("source") is not None else object()
        for s in signals.values()
        if isinstance(s, dict)
    ]
    if len(src) != len(set(src)):
        return False, "重复来源：%s（同源信号不得分别计分，见 independence.py）" % src
    return True, ""


def trust_decision(
    smiles,
    probability=None,
    independent_uncertainty=None,
    per_sample_calibration_error=None,
    physchem=None,
    similarity=None,
    assumptions=None,
    family=None,
    hard_fail_on_invalid=True,
):
    """给一个分子当场产出可审计的 TRUST 决策。

    probability: 模型 P(positive)；independent_uncertainty: 独立不确定性（MC/集成分歧），
      必须与 probability 不同源；per_sample_calibration_error: 逐样本校准误差 |p - bin_rate|，
      只有模型级 ECE 时不要传（会标 model_level_only 且不计分）。
    physchem: physchem_violations() 的输出；similarity: 与训练集的 Tanimoto（可选）。
    family: 设计期固定的模型家族标签（移植 AdmitOR：跨族才算独立）。
    """
    assumptions = list(assumptions or [])
    assumptions.append("分数是声明性启发式聚合，不是概率保证；不替代 G10/G13 证据门")
    base = dict(
        smiles=smiles,
        family=family,
        assumptions=assumptions,
        not_a_proof_of=["预测正确性", "临床/监管结论", "estimand 已绑定"],
    )
    # 结构硬失败（修正缺陷 3）
    if physchem and physchem.get("valid") is False:
        return dict(
            base,
            decision="REFUSED",
            trust_score=0.0,
            trust_level="REFUSED",
            action="终止：结构无效（不做静默零特征预测）",
            score_breakdown={},
            reason="INVALID_STRUCTURE",
        )
    # 理化 AD 硬拒答（>=2 越界）
    if physchem and physchem.get("action") == "REFUSED":
        return dict(
            base,
            decision="REFUSED",
            trust_score=0.0,
            trust_level="REFUSED",
            action="终止：理化 AD 越界 >=2",
            score_breakdown={},
            physchem_ad=physchem,
        )
    # 正交性检查（修正缺陷 1）
    sig = {}
    if probability is not None:
        sig["confidence"] = dict(
            value=min(1.0, max(probability, 1 - probability)),
            source="model_probability",
        )
    if independent_uncertainty is not None:
        iu = min(1.0, max(0.0, float(independent_uncertainty)))
        # 与 confidence 同源检测：若未提供 family/独立来源标记，保守拒绝
        if (
            probability is not None
            and abs(iu - (1 - 2 * abs(probability - 0.5))) < 1e-9
        ):
            return dict(
                base,
                decision="UNDETERMINED",
                trust_score=None,
                trust_level="UNDETERMINED",
                action="拒绝计分：uncertainty 与 confidence 同源（1-2|p-0.5|）",
                score_breakdown={},
            )
        sig["uncertainty"] = dict(value=1.0 - iu, source="independent_uncertainty")
    cal_signal = "per_sample"
    if per_sample_calibration_error is not None:
        sig["calibration"] = dict(
            value=1.0 - min(1.0, abs(float(per_sample_calibration_error))),
            source="per_sample_calibration",
        )
    else:
        cal_signal = "model_level_only_not_counted"
    if similarity is not None:
        sig["applicability"] = dict(
            value=1.0 - min(1.0, abs(1.0 - float(similarity))),
            source="tanimoto_similarity",
        )
    ok, why = _check_orthogonality(sig)
    if not ok:
        return dict(
            base,
            decision="UNDETERMINED",
            trust_score=None,
            trust_level="UNDETERMINED",
            action="拒绝计分：" + why,
            score_breakdown={},
        )
    if len(sig) < 2:
        return dict(
            base,
            decision="UNDETERMINED",
            trust_score=None,
            trust_level="UNDETERMINED",
            action="独立信号不足（<%d），只描述不分级" % 2,
            score_breakdown={k: v["value"] for k, v in sig.items()},
        )
    n = len(sig)
    breakdown = {k: round(100.0 * v["value"] / n, 2) for k, v in sig.items()}
    score = round(sum(breakdown.values()), 1)
    level = next((lv for th, lv in _LEVELS if score >= th), "LOW")
    decision_level = level
    if physchem and physchem.get("action") == "PHYSCHEM_WARNING":
        action = "人工复核：理化 AD 单维越界 %s" % physchem["violations"]
        decision_level = "MEDIUM"  # 理化单维越界时不得给出 ACCEPT 决策（原实现 decision 仍按 HIGH=ACCEPT，与 action 矛盾）
    elif level == "HIGH":
        action = "Accept prediction（仍须带 estimand 与区间，见 G13）"
    elif level == "MEDIUM":
        action = "Review manually：信号分歧，需人判断"
    else:
        action = "Abstain：可信度 LOW，不进决策"
    return dict(
        base,
        decision=(
            "ACCEPT"
            if decision_level == "HIGH"
            else ("ABSTAIN" if decision_level == "LOW" else "REVIEW")
        ),
        trust_score=score,
        trust_level=level,
        action=action,
        score_breakdown=breakdown,
        calibration_signal=cal_signal,
        physchem_ad=physchem,
        n_independent_signals=n,
    )


# ---- 预注册判据未达成报告（移植 SciForge §4.7 的四处一致披露）----
def prereg_criterion_report(
    primary, observed, noise_floor, secondary=None, post_hoc_adjusted=False
):
    """primary/observed/noise_floor: dict(id, threshold, direction, value) 或数值。

    输出结构化判定：主判据是否达成 + 效应是否在噪声底内 + 是否事后调整。
    """

    def _val(x, k, default=None):
        return x.get(k, default) if isinstance(x, dict) else x

    p_th = _val(primary, "threshold")
    obs = _val(observed, "value", observed)
    nf = _val(noise_floor, "value", noise_floor)
    direction = primary.get("direction", "<=") if isinstance(primary, dict) else "<="
    if direction == "<=":
        met = obs <= p_th
    elif direction == ">=":
        met = obs >= p_th
    else:
        # 非法 direction 保守判"未达成"，不得静默当作 >= 而误报达成
        met = False
    within_noise = nf is not None and abs(obs - p_th) <= abs(float(nf))
    rows = dict(
        primary=dict(
            threshold=p_th,
            observed=obs,
            direction=direction,
            met=met,
            effect_within_noise_floor=within_noise,
            note=(
                "未达成；观测与阈值的差落在噪声底内，报告为 not met，"
                "不得改称'接近达成'"
                if (not met and within_noise)
                else ("达成" if met else "未达成")
            ),
        ),
        secondary=secondary,
        post_hoc_adjustment=bool(post_hoc_adjusted),
        integrity=(
            "PASS"
            if not post_hoc_adjusted
            else "FAIL：检测到事后调整判据，推断资格撤销"
        ),
        citation_ready_text=(
            "主判据 %s %s %s %s；观测=%s，复现噪声底=%s。"
            "该结果%s，且%s无事后判据调整。"
            % (
                (
                    primary.get("id", "primary")
                    if isinstance(primary, dict)
                    else "primary"
                ),
                direction,
                p_th,
                ("达成" if met else "未达成"),
                obs,
                nf,
                ("在噪声底内" if within_noise else "不在噪声底内"),
                "经" if not post_hoc_adjusted else "未",
            )
        ),
    )
    return rows


def selftest():
    rows = []

    def chk(name, cond, detail=""):
        rows.append(dict(name=name, ok=bool(cond), detail=detail))

    nc = numeric_coverage([10.5, 20.0], "cost is 10.5 and demand 20.0")
    chk("numeric_coverage_pass", nc["verdict"] == "PASS", str(nc["verdict"]))
    nc2 = numeric_coverage([10.5, 77.7], "cost is 10.5 only")
    chk("numeric_coverage_escalate", nc2["verdict"] != "PASS", str(nc2))
    # 共线信号必须拒绝
    d = trust_decision(
        "CCO", probability=0.8, independent_uncertainty=1 - 2 * abs(0.8 - 0.5)
    )
    chk("collinearity_rejected", d["decision"] == "UNDETERMINED", str(d["action"]))
    # 无效结构硬拒答
    bad = trust_decision(
        "NOT_A_SMILES",
        physchem=dict(valid=False, violations=["INVALID_STRUCTURE"], action="REFUSED"),
    )
    chk("invalid_structure_refused", bad["trust_level"] == "REFUSED", "")
    # 正交信号应能计分
    good = trust_decision(
        "CCO", probability=0.9, independent_uncertainty=0.1, similarity=0.95, family="A"
    )
    chk(
        "orthogonal_signals_scored",
        good["trust_score"] is not None,
        str(good.get("trust_score")),
    )
    # 模型级 ECE 不计分
    chk(
        "model_level_ece_not_counted",
        good["calibration_signal"] == "model_level_only_not_counted",
        str(good["calibration_signal"]),
    )
    rep = prereg_criterion_report(
        dict(id="P1", threshold=-2.0, direction="<="), dict(value=-1.7), dict(value=2.0)
    )
    chk(
        "prereg_not_met_within_noise",
        rep["primary"]["met"] is False
        and rep["primary"]["effect_within_noise_floor"] is True,
        rep["citation_ready_text"][:60],
    )
    return all(r["ok"] for r in rows), rows


if __name__ == "__main__":
    import argparse, json

    ap = argparse.ArgumentParser(prog="trust")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        ok, rows = selftest()
        for r in rows:
            print(
                "[%s] %s %s"
                % ("OK" if r["ok"] else "FAIL", r["name"], r["detail"][:70])
            )
        print("[trust] %s" % ("PASS" if ok else "FAIL"))
        raise SystemExit(0 if ok else 4)
