# -*- coding: utf-8 -*-
"""盲区4：不可回避的模型不确定性量化（UQ）门禁。

硬阈值（LogP>6、Tanimoto>40）只能描述"点估计"，无法区分：
  - 模型极其确信的 0.7；
  - 模型在 0.5~0.9 之间摇摆后平均出的 0.7。

接口策略：
  1. 外部 API 若提供 samples / std / ensemble → 直接计算方差；
  2. 否则**必须**用本地 Morgan kNN 代理模型估计方差与覆盖度；
  3. 方差超阈值或适用域覆盖不足 → 无论均值多"安全"，
     强制 verdict=UNDETERMINED、tier_ceiling=T0。
"""

from __future__ import annotations

import math


def from_samples(samples):
    xs = [float(x) for x in (samples or [])]
    if len(xs) < 2:
        return {
            "ok": False,
            "reason": "NEED_AT_LEAST_2_SAMPLES",
            "mean": xs[0] if xs else None,
            "std": None,
        }
    mean = sum(xs) / len(xs)
    var = sum((x - mean) ** 2 for x in xs) / (len(xs) - 1)
    return {
        "ok": True,
        "mean": mean,
        "variance": var,
        "std": math.sqrt(var),
        "n": len(xs),
        "source": "samples",
    }


def from_ensemble(predictions):
    """Deep Ensembles / MC Dropout 的统一入口。"""
    return from_samples(predictions)


def _fingerprint(smiles):
    from rdkit import Chem
    from rdkit.Chem import rdFingerprintGenerator

    m = Chem.MolFromSmiles(str(smiles))
    if m is None:
        return None
    gen = rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=2048)
    return gen.GetFingerprint(m)


def surrogate_uq(
    smiles, reference, *, endpoint="dili", k=5, min_k=2, min_coverage=0.30
):
    """局部代理：kNN Tanimoto 加权方差 + 适用域惩罚。

    reference: [{"smiles": ..., "value": ..., "endpoint": ...}, ...]
    """
    try:
        from rdkit import DataStructs

        fp = _fingerprint(smiles)
        if fp is None:
            return {
                "ok": False,
                "status": "PARSE_FAILED",
                "std": None,
                "variance": None,
                "coverage": 0.0,
            }
        sims = []
        for ref in reference or []:
            if ref.get("endpoint", endpoint) != endpoint:
                continue
            rfp = _fingerprint(ref.get("smiles"))
            if rfp is None:
                continue
            sims.append(
                (
                    float(DataStructs.TanimotoSimilarity(fp, rfp)),
                    float(ref.get("value")),
                )
            )
        sims.sort(key=lambda x: -x[0])
        chosen = sims[: max(1, k)]
        max_sim = chosen[0][0] if chosen else 0.0
        if len(chosen) < min_k or max_sim < min_coverage:
            return {
                "ok": False,
                "status": "OUT_OF_DOMAIN",
                "std": None,
                "variance": None,
                "coverage": max_sim,
                "n_neighbors": len(chosen),
                "source": "surrogate_knn",
            }
        weights = [max(1e-6, s**4) for s, _ in chosen]
        tw = sum(weights)
        mean = sum(w * v for w, (_, v) in zip(weights, chosen)) / tw
        var = sum(w * (v - mean) ** 2 for w, (_, v) in zip(weights, chosen)) / tw
        # 适用域越远，方差下限越高（避免"最近邻 0.31 却假装很确信"）
        domain_var = ((1.0 - max_sim) ** 2) * 0.25
        total = var + domain_var
        return {
            "ok": True,
            "status": "ESTIMATED",
            "mean": mean,
            "variance": total,
            "std": math.sqrt(total),
            "coverage": max_sim,
            "n_neighbors": len(chosen),
            "source": "surrogate_knn",
        }
    except Exception as exc:
        return {
            "ok": False,
            "status": "UQ_ERROR",
            "detail": str(exc)[:120],
            "std": None,
            "variance": None,
            "coverage": 0.0,
        }


def resolve_uq(record, *, reference=None, endpoint="dili"):
    """优先使用外部方差；缺失则强制本地代理。"""
    if record.get("variance") is not None and record.get("std") is not None:
        return {
            "ok": True,
            "mean": float(record.get("value")),
            "variance": float(record["variance"]),
            "std": float(record["std"]),
            "source": "external_api",
        }
    if record.get("samples"):
        out = from_samples(record["samples"])
        out["source"] = "external_samples"
        return out
    if record.get("ensemble"):
        out = from_ensemble(record["ensemble"])
        out["source"] = "deep_ensemble"
        return out
    if reference is None:
        return {
            "ok": False,
            "status": "NO_VARIANCE_NO_REFERENCE",
            "std": None,
            "variance": None,
            "coverage": 0.0,
        }
    return surrogate_uq(record.get("smiles"), reference, endpoint=endpoint)


def _max_sim_to_reference(smiles, reference, endpoint):
    try:
        from rdkit import DataStructs

        fp = _fingerprint(smiles)
        if fp is None:
            return 0.0
        sims = []
        for ref in reference or []:
            if ref.get("endpoint", endpoint) != endpoint:
                continue
            rfp = _fingerprint(ref.get("smiles"))
            if rfp is not None:
                sims.append(float(DataStructs.TanimotoSimilarity(fp, rfp)))
        return max(sims) if sims else 0.0
    except Exception:
        return 0.0


def _quantile(xs, q):
    xs = sorted(float(x) for x in xs)
    if not xs:
        return None
    pos = min(len(xs) - 1, max(0, int(math.ceil(q * len(xs))) - 1))
    return xs[pos]


def coverage_by_shift(
    calibration,
    test,
    *,
    reference=None,
    endpoint="dili",
    alpha=0.10,
    bins=(0.20, 0.40, 0.60, 0.80),
):
    """split-conformal 覆盖率 + 按 Tanimoto 偏移强度分层。

    返回每个相似度区间的覆盖率；低相似区间覆盖率跌破标称一半 → 失败。
    """
    cal_res = [abs(float(r["value"]) - float(r["mean"])) for r in calibration]
    qhat = _quantile(cal_res, 1.0 - alpha)
    if qhat is None:
        return {"ok": False, "reason": "EMPTY_CALIBRATION", "bins": []}
    labels = ["[%.2f,%.2f)" % (bins[i], bins[i + 1]) for i in range(len(bins) - 1)]
    labels.append("[%.2f,1.00]" % bins[-1])
    buckets = {lab: {"n": 0, "covered": 0} for lab in labels}
    for r in test:
        sim = _max_sim_to_reference(r.get("smiles"), reference, endpoint)
        idx = len(bins) - 1
        for i in range(len(bins) - 1):
            if bins[i] <= sim < bins[i + 1]:
                idx = i
                break
        lab = labels[idx]
        buckets[lab]["n"] += 1
        if abs(float(r["value"]) - float(r["mean"])) <= qhat:
            buckets[lab]["covered"] += 1
    out = []
    for lab in labels:
        b = buckets[lab]
        out.append(
            {
                "stratum": lab,
                "n": b["n"],
                "coverage": round(b["covered"] / b["n"], 4) if b["n"] else None,
            }
        )
    valid = [b for b in out if b["coverage"] is not None]
    low = (
        min(valid, key=lambda b: float(b["stratum"].split(",")[0].strip("[")))
        if valid
        else None
    )
    nominal = 1.0 - alpha
    reasons = []
    if low and low["coverage"] < nominal * 0.5:
        reasons.append(
            "最远域覆盖率 %.3f < 标称一半 %.3f" % (low["coverage"], nominal * 0.5)
        )
    return {
        "ok": not reasons,
        "reasons": reasons,
        "qhat": qhat,
        "nominal": nominal,
        "bins": out,
        "lowest_bin": low,
        "note": "coverage 只在当前标定与偏移分层下有效，不是全域保证",
    }


def coverage_by_class(test, *, qhat, labels=(0, 1)):
    """类别条件覆盖：少数类覆盖不足是边际 coverage 看不见的失败。"""
    out = {}
    for lab in labels:
        rows = [r for r in test if int(r.get("label", 0)) == lab]
        if not rows:
            out[str(lab)] = {"n": 0, "coverage": None}
            continue
        cov = sum(
            1 for r in rows if abs(float(r["value"]) - float(r["mean"])) <= qhat
        ) / len(rows)
        out[str(lab)] = {"n": len(rows), "coverage": round(cov, 4)}
    vals = [v["coverage"] for v in out.values() if v["coverage"] is not None]
    return {"per_class": out, "min_coverage": min(vals) if vals else None}


def representation_stability(
    predict_fn, smiles, *, endpoint="dili", n=6, seed=20261122
):
    """不依赖 kNN 方差的独立探针：同一分子的不同 SMILES 写法预测是否稳定。

    模型若"自信地错"，往往对表示扰动也异常敏感；这是方差信号沉默时的
    第二路证据，但仍不是湿实验替代品。
    """
    try:
        from rdkit import Chem

        m = Chem.MolFromSmiles(str(smiles))
        if m is None:
            return {"ok": False, "status": "PARSE_FAILED", "std": None}
        rng = __import__("random").Random(seed)
        variants = {Chem.MolToSmiles(m)}
        for _ in range(max(1, n - 1)):
            variants.add(Chem.MolToSmiles(m, doRandom=True, canonical=False))
        preds = []
        for s in sorted(variants):
            preds.append(float(predict_fn(s, endpoint=endpoint)))
        if len(preds) < 2:
            return {"ok": False, "status": "NO_VARIANTS", "std": None}
        mean = sum(preds) / len(preds)
        var = sum((x - mean) ** 2 for x in preds) / (len(preds) - 1)
        return {
            "ok": True,
            "status": "OK",
            "mean": mean,
            "std": math.sqrt(var),
            "n_variants": len(preds),
            "source": "representation_stability",
        }
    except Exception as exc:
        return {
            "ok": False,
            "status": "STABILITY_ERROR",
            "detail": str(exc)[:120],
            "std": None,
        }


def uq_gate_with_stability(
    record,
    *,
    reference=None,
    endpoint="dili",
    predict_fn=None,
    max_std=0.15,
    min_coverage=0.30,
    max_representation_std=0.10,
    **_,
):
    """UQ + 独立表示稳定性双门禁。"""
    out = uq_gate(
        record,
        reference=reference,
        endpoint=endpoint,
        max_std=max_std,
        min_coverage=min_coverage,
    )
    if predict_fn is not None and record.get("smiles"):
        st = representation_stability(predict_fn, record["smiles"], endpoint=endpoint)
        out["representation_stability"] = st
        if st.get("std") is not None and float(st["std"]) > max_representation_std:
            out["verdict"] = "UNDETERMINED"
            out["tier_ceiling"] = "T0"
            out["reason"] = "REPRESENTATION_INSTABILITY"
            out["detail"] = (
                (out.get("detail") or "")
                + "; 表示扰动 std %.3f > %.3f"
                % (float(st["std"]), max_representation_std)
            ).strip("; ")
    return out


def uq_gate(
    record, *, reference=None, endpoint="dili", max_std=0.15, min_coverage=0.30
):
    """方差/覆盖门禁：不确定就 UNDETERMINED，不管外部均值多"安全"。"""
    uq = resolve_uq(record, reference=reference, endpoint=endpoint)
    reasons = []
    std = uq.get("std")
    if std is None or not uq.get("ok"):
        reasons.append("NO_RELIABLE_VARIANCE:%s" % uq.get("status", "UNKNOWN"))
    else:
        if float(std) > max_std:
            reasons.append("STD_TOO_HIGH:%.4f>%.4f" % (float(std), max_std))
        cov = uq.get("coverage")
        if cov is not None and float(cov) < min_coverage:
            reasons.append("COVERAGE_TOO_LOW:%.3f<%.3f" % (float(cov), min_coverage))
    out = dict(record)
    out["uq"] = uq
    if reasons:
        out["verdict"] = "UNDETERMINED"
        out["tier_ceiling"] = "T0"
        out["certainty_modifier"] = "low_unresolvable"
        out["reason"] = "HIGH_UNCERTAINTY"
        out["detail"] = "; ".join(reasons)
        return out
    return out
