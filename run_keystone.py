# -*- coding: utf-8 -*-
"""基石实验 + 种子误差棒（R08/A10 + R10/A1）。

评审 C1 原话："当前证据链证明的是'框架自洽'，不是'框架有效'。审稿人会用一句话
杀死这篇论文：You have demonstrated that your gates work, not that they help."

本脚本直接跑那个"能杀死论文"的实验：
  ≥3 个 TDC 端点 × ≥20 个随机种子 × 4 种决策策略，主指标为**端点特异代价的期望效用**。

五种策略（同一批源预测，只改决策规则）：
  S1 naive_majority   : 三源二值多数投票，从不弃权
  S2 ad_guard         : 适用域守卫（kNN Tanimoto ≥ 0.35）+ 多数投票，域外弃权
  S3 calibrated_conformal : 校准（Platt/isotonic on val）+ 选择性弃权（满足目标风险的最小覆盖）
  S4 full_admission   : 域守卫 + 分歧守卫 + 独立组计票 + 校准弃权（= 本框架）
  S5 uncalibrated_conf: **未校准**原始均值概率 + 同一套"目标风险最小覆盖"阈值规则

S5 的用途（评审黑榜 1 的裁决点）：
  上一版只拿 S4 比 S3（isotonic 校准 + 阈值调优的强基线），于是"准入层没有性能增益"
  这一负面结论存在第二种解释——**基线过强**。S5 用未校准分数做同一件事：若 S4 连
  S5 也赢不了，则负面结论与基线强度无关；若 S4 稳赢 S5 但输 S3，则说明增益来自校准、
  不来自准入层本身。两种结果都必须原样报告。

源（同一训练集上的三个模型，作为"三个预测源"代理）：
  RF-Morgan2048 / Ridge-RDKit描述符 / RF-MACCS

输出：out_keystone/results.json + summary.md
"""

import argparse
import hashlib
import io
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from rdkit import Chem, DataStructs, RDLogger  # noqa: E402
from rdkit.Chem import AllChem, Descriptors, MACCSkeys, rdMolDescriptors  # noqa: E402

RDLogger.DisableLog("rdApp.*")

from sklearn.ensemble import RandomForestClassifier  # noqa: E402
from sklearn.linear_model import RidgeClassifier  # noqa: E402
from sklearn.preprocessing import StandardScaler  # noqa: E402
from sklearn.isotonic import IsotonicRegression  # noqa: E402
from sklearn.metrics import roc_auc_score  # noqa: E402

from adt import cost_decision as CD  # noqa: E402

ENDPOINTS = ("hERG", "DILI", "BBB_Martins")
# 端点特异代价：(false_PASS 成本, false_FAIL 成本, 弃权成本)
# 理由：筛选中"把有毒判成安全"远贵于"把安全判成有毒"，弃权便宜于两者（可补实验）
COSTS = {
    "hERG": (5.0, 1.0, 0.5),
    "DILI": (5.0, 1.0, 0.5),
    "BBB_Martins": (3.0, 1.0, 0.5),
    # 2026-11-25 新增：c* 估计器跨数据集可重算性演示（仅用于迁移性验证，
    # 不改动上面三个端点的主分析口径）。代价与 hERG/DILI 同口径，
    # 因为二者的 false_PASS 同样是"把有害判成安全"：Ames 致突变物漏检、
    # CYP3A4 抑制剂漏检，代价均高于误报；弃权便宜于两者（可补实验）。
    "Ames": (5.0, 1.0, 0.5),
    "CYP3A4_Veith": (5.0, 1.0, 0.5),
    # 2026-11-25 扩展：把 c* 从 5 个端点扩到 TDC ADMET_Group 的全部 13 个分类端点。
    # 三元组按"漏检后果是否可逆"分两类，而不是逐端点随意取值：
    #   (a) 安全与药物相互作用类 -> 5:1。漏检致突变物、心脏毒性、肝毒性，或漏检
    #       一个 CYP 抑制剂/底物、P-gp 底物，后果是患者暴露于不可逆风险（毒性或
    #       无效剂量下的治疗失败），下游无法补救。
    #   (b) 药代/暴露类 -> 3:1。漏检低生物利用度、低肠吸收或非脑渗透化合物，代价
    #       低于安全类，且通常可由后续 PK 或配方实验纠正；BBB_Martins 沿用 3:1
    #       正是同一逻辑（见上）。
    # 弃权成本统一 0.5（可补实验，但非免费），与主分析口径一致。
    "CYP2C9_Veith": (5.0, 1.0, 0.5),
    "CYP2D6_Veith": (5.0, 1.0, 0.5),
    "CYP3A4_Substrate_CarbonMangels": (5.0, 1.0, 0.5),
    "CYP2C9_Substrate_CarbonMangels": (5.0, 1.0, 0.5),
    "CYP2D6_Substrate_CarbonMangels": (5.0, 1.0, 0.5),
    "PGP_Broccatelli": (5.0, 1.0, 0.5),
    "Bioavailability_MA": (3.0, 1.0, 0.5),
    "HIA_Hou": (3.0, 1.0, 0.5),
}
# 扩展端点（不属于预注册主分析；用于 endpoint-population 证据，单独标注）
EXTENSION = (
    "CYP2C9_Veith",
    "CYP2D6_Veith",
    "CYP3A4_Substrate_CarbonMangels",
    "CYP2C9_Substrate_CarbonMangels",
    "CYP2D6_Substrate_CarbonMangels",
    "PGP_Broccatelli",
    "Bioavailability_MA",
    "HIA_Hou",
)
# 迁移性演示端点（不属于预注册主分析；写入产物时单独标注，防止混入主结果）
TRANSFER_DEMO = ("Ames", "CYP3A4_Veith")
AD_THRESHOLD = 0.35  # 与框架 kNN Tanimoto 饱和判据同口径
# 模型族（robustness 用；默认 rf 即论文口径）
MODEL_FAMILY = "rf"
# R17/R1-3：代价敏感性网格（评审要求"主结论以代价比扫描曲线的稳定区宽度报告"）
ABSTAIN_GRID = (
    0.05,
    0.10,
    0.20,
    0.50,
    1.00,
)  # 弃权成本（false_pass=5, false_fail=1 固定）
FPASS_GRID = (2.0, 5.0, 10.0)  # false_PASS 成本（abstain=0.2 固定）


def fp_morgan(m):
    return AllChem.GetMorganFingerprintAsBitVect(m, 2, nBits=2048)


def fp_maccs(m):
    return MACCSkeys.GenMACCSKeys(m)


def desc_vec(m):
    v = np.array(
        [
            Descriptors.MolWt(m),
            Descriptors.MolLogP(m),
            Descriptors.TPSA(m),
            Descriptors.NumHDonors(m),
            Descriptors.NumHAcceptors(m),
            Descriptors.RingCount(m),
            rdMolDescriptors.CalcFractionCSP3(m),
            Descriptors.NumRotatableBonds(m),
            Descriptors.NumAromaticRings(m),
            (
                Descriptors.MaxPartialCharge(m)
                if hasattr(Descriptors, "MaxPartialCharge")
                else 0.0
            ),
        ],
        dtype=float,
    )
    # RDKit 部分描述符对含特殊原子的分子返回 NaN/inf（实测触发 RidgeClassifier 报错）
    return np.nan_to_num(v, nan=0.0, posinf=0.0, neginf=0.0)


def load_endpoint(name, cache="out_ext/tdc_cache"):
    from adt.tdc_local import load_split

    d = load_split(cache, name)
    tr, te = d["train_val"], d["test"]

    def _xy(df):
        smis, ys = [], []
        for _, r in df.iterrows():
            m = Chem.MolFromSmiles(str(r["Drug"]))
            if m is None:
                continue
            smis.append(m)
            ys.append(int(float(r["Y"])))
        return smis, np.array(ys, dtype=int)

    return _xy(tr), _xy(te)


def to_np(bitvects, nbits):
    X = np.zeros((len(bitvects), nbits), dtype=np.int8)
    for i, fp in enumerate(bitvects):
        DataStructs.ConvertToNumpyArray(fp, X[i])
    return X


def _make_tree(family, seed):
    """Tree ensemble for the Morgan/MACCS sources, switchable for robustness runs.

    The default (``rf``) is what the manuscript reports. ``et`` and ``gbm`` exist
    to test whether c* is a property of the endpoint or of one model family: if
    the threshold moved substantially with the learner, the "threshold is an
    endpoint attribute" claim would have to be withdrawn.
    """
    if family == "et":
        from sklearn.ensemble import ExtraTreesClassifier

        return ExtraTreesClassifier(n_estimators=300, random_state=seed, n_jobs=1)
    if family == "gbm":
        from sklearn.ensemble import HistGradientBoostingClassifier

        return HistGradientBoostingClassifier(random_state=seed)
    if family == "lr":
        from sklearn.linear_model import LogisticRegression

        return LogisticRegression(max_iter=2000, random_state=seed)
    return RandomForestClassifier(n_estimators=300, random_state=seed, n_jobs=1)


def fit_sources(mols_tr, y_tr, seed, family="rf"):
    Xm_tr = to_np([fp_morgan(m) for m in mols_tr], 2048)
    Xc_tr = to_np([fp_maccs(m) for m in mols_tr], 167)
    Xd_tr = np.array([desc_vec(m) for m in mols_tr])
    sc = StandardScaler().fit(Xd_tr)
    models = {
        "rf_morgan": _make_tree(family, seed).fit(Xm_tr, y_tr),
        "ridge_desc": RidgeClassifier(alpha=1.0).fit(sc.transform(Xd_tr), y_tr),
        "rf_maccs": _make_tree(family, seed).fit(Xc_tr, y_tr),
    }
    return models, sc


def predict_sources(models, sc, mols):
    Xm = to_np([fp_morgan(m) for m in mols], 2048)
    Xc = to_np([fp_maccs(m) for m in mols], 167)
    Xd = np.array([desc_vec(m) for m in mols])
    out = {}
    p = models["rf_morgan"].predict_proba(Xm)[:, 1]
    out["rf_morgan"] = p
    d = models["ridge_desc"].decision_function(sc.transform(Xd))
    out["ridge_desc"] = 1.0 / (1.0 + np.exp(-d))  # 决策值→伪概率（仅排序用）
    p3 = models["rf_maccs"].predict_proba(Xc)[:, 1]
    out["rf_maccs"] = p3
    return out


def knn_ad(mols_ref, mols_query, thr=AD_THRESHOLD):
    """域判据：query 到 ref 的最大 Tanimoto ≥ thr 视为域内。"""
    ref_fps = [fp_morgan(m) for m in mols_ref]
    flags = []
    for m in mols_query:
        fp = fp_morgan(m)
        sims = DataStructs.BulkTanimotoSimilarity(fp, ref_fps)
        flags.append(max(sims) if sims else 0.0)
    return np.array(flags)


def utility(y_true, y_pred, decided, costs):
    """costs=(c_false_pass, c_false_fail, c_abstain)；y/y_pred 中 1=FAIL（阳性）。"""
    c_fp_pass, c_fp_fail, c_abst = costs
    total = 0.0
    for t, p, d in zip(y_true, y_pred, decided):
        if not d:
            total += c_abst
        elif t == 1 and p == 0:  # 真 FAIL 被判 PASS → 最贵
            total += c_fp_pass
        elif t == 0 and p == 1:  # 真 PASS 被判 FAIL
            total += c_fp_fail
    return -total / float(len(y_true))


def ece(y_true, prob, bins=10):
    idx = np.argsort(prob)
    chunks = np.array_split(idx, bins)
    e = 0.0
    for ch in chunks:
        if len(ch) == 0:
            continue
        conf = float(np.mean(prob[ch]))
        acc = float(np.mean(y_true[ch]))
        e += abs(conf - acc) * len(ch) / len(y_true)
    return e


def bayes_threshold_from_costs(costs):
    """代价敏感的最小期望代价判定阈值：判 FAIL 当 P(FAIL) > c_fp_fail/(c_fp_pass+c_fp_fail)。

    C18 / 外审 A：旧 pick_threshold 的 costs 是**死参数**（函数体零引用），这正是
    「代价只进入事后重标价」的根因之一。本函数给出可审计的代价→阈值映射，
    由 π(c) 流水线逐档调用并写入产物；S1–S5 的既有口径保持不变，便于 A/B 对照。
    """
    c_fp_pass, c_fp_fail, _ = costs
    denom = float(c_fp_pass) + float(c_fp_fail)
    return float(c_fp_fail) / denom if denom > 0 else 0.5


def pick_threshold(prob_cal, y_cal, target_risk=0.15, costs=(5.0, 1.0, 0.5)):
    """在 val 上选"满足目标风险的最小弃权量"阈值：低于阈值则弃权。

    **LEGACY / C18**：`costs` 在此仅为兼容签名的死参数，函数体不消费；分类阈值
    恒为 0.5。因此本函数产出的 S1–S5 流水线**不能**用来证明「代价进入决策」，
    其 cost_sweep 是同一预测的事后重标价（会计恒等式）。代价敏感的对应实现见
    `bayes_threshold_from_costs()` 与 `strategies(costs=...)` 的 S6 分支。
    """
    best = (0.0, None)
    for t in np.linspace(0.05, 0.95, 19):
        keep = prob_cal >= t
        if keep.sum() < max(10, 0.2 * len(prob_cal)):
            continue
        pred = (prob_cal[keep] >= 0.5).astype(int)
        risk = float(np.mean(pred != y_cal[keep]))
        cov = float(keep.mean())
        if risk <= target_risk and cov > best[0]:
            best = (cov, t)
    return best[1] if best[1] is not None else 0.5


def strategies(probs, ad_sim, thr_cal, calib, y_cal=None, thr_raw=None, costs=None):
    """返回 {策略: (pred, decided_mask)}。probs: dict 源→p。

    thr_cal : 校准分数上的弃权阈值（S3/S4）
    thr_raw : 未校准分数上的弃权阈值（S5）；缺省时退回 thr_cal，调用方应显式传值
    costs   : (c_false_pass, c_false_fail, c_abstain)。**B6 / C18（2026-11-04）**：
              传入时新增 S6_cost_sensitive——代价在函数体内直接决定 decided_mask
              （最小期望代价规则），而不是像 R17 cost_sweep 那样只在事后重标价。
              这是对外审 A「costs 在 pick_threshold/strategies 零引用」的正面修复。

    S6 刻意不列入 STRATEGIES 常量：它是**独立第二条流水线**的结论，不能混入
    S1–S5 的配对比较，否则会把「同一预测只改代价」的会计恒等式又偷偷带回主表。
    """
    names = list(probs)
    P = np.vstack([probs[n] for n in names]).T
    n = P.shape[0]
    # 校准后的均值概率（S3/S4 使用）
    Pc = np.vstack([calib[n](probs[n]) for n in names]).T if calib else P
    mean_p = P.mean(axis=1)
    mean_pc = Pc.mean(axis=1)
    out = {}

    # S1 朴素多数（二值）
    votes = (P >= 0.5).astype(int)
    maj = (votes.sum(axis=1) >= (len(names) / 2.0)).astype(int)
    out["S1_naive_majority"] = (maj, np.ones(n, dtype=bool))

    # S2 域守卫 + 多数
    in_ad = ad_sim >= AD_THRESHOLD
    out["S2_ad_guard"] = (maj, in_ad)

    # S3 校准 + 选择性弃权
    dec3 = mean_pc >= thr_cal
    out["S3_calibrated_conformal"] = ((mean_pc >= 0.5).astype(int), dec3)

    # S4 完整准入：域 + 分歧守卫 + 独立组 + 校准弃权
    spread = P.max(axis=1) - P.min(axis=1)
    disagree = spread > 0.30
    dec4 = dec3 & in_ad & (~disagree)
    out["S4_full_admission"] = ((mean_pc >= 0.5).astype(int), dec4)

    # S5 未校准置信度弃权（同一条阈值规则，只换分数）
    thr_raw = thr_cal if thr_raw is None else thr_raw
    out["S5_uncalibrated_conf"] = ((mean_p >= 0.5).astype(int), mean_p >= thr_raw)

    # S6 / B6：代价进入决策。判定动作与弃权掩码都由 costs 与 P(FAIL) 共同决定；
    # 换一档代价 → 不同的 decided_mask（由 run_endpoint 逐档落 sha256 验证）。
    if costs is not None:
        pi = CD.pi_cost_sensitive(mean_pc, costs)
        pred6 = np.array([1 if a == "FAIL" else 0 for a in pi["actions"]], dtype=int)
        dec6 = np.array(pi["decided_mask"], dtype=bool)
        out["S6_cost_sensitive"] = (pred6, dec6)
    return out


def run_endpoint(name, seeds, cache, target_risk=0.15, return_pi=False):
    """return_pi=True 时额外返回 π(c) 第二流水线逐档行（含 decided_mask_sha256）。

    默认 False 保持既有调用方兼容；S1–S5 的 rows 结构与数值口径一律不变。
    """
    (mols_tr, y_tr), (mols_te, y_te) = load_endpoint(name, cache)
    rng = np.random.default_rng(0)
    idx = rng.permutation(len(mols_tr))
    cut = int(0.8 * len(mols_tr))
    fit_idx, cal_idx = idx[:cut], idx[cut:]
    mols_fit = [mols_tr[i] for i in fit_idx]
    y_fit = y_tr[fit_idx]
    mols_cal = [mols_tr[i] for i in cal_idx]
    y_cal = y_tr[cal_idx]

    rows = []
    pi_rows = []
    for seed in seeds:
        models, sc = fit_sources(mols_fit, y_fit, seed, MODEL_FAMILY)
        p_cal = predict_sources(models, sc, mols_cal)
        p_te = predict_sources(models, sc, mols_te)
        # 校准器（isotonic，单调）；样本太少则退化为恒等
        calib = {}
        try:
            for k, v in p_cal.items():
                iso = IsotonicRegression(out_of_bounds="clip").fit(v, y_cal)
                calib[k] = (lambda iso_: (lambda x: iso_.predict(x)))(iso)
        except Exception:
            calib = {k: (lambda x: x) for k in p_cal}
        mean_pc_cal = np.mean(np.vstack([calib[k](p_cal[k]) for k in p_cal]), axis=0)
        mean_pc_te = np.mean(np.vstack([calib[k](p_te[k]) for k in p_te]), axis=0)
        # 未校准均值分数（S5 用）；阈值规则与 S3 完全相同，只换分数口径
        mean_p_cal = np.mean(np.vstack([p_cal[k] for k in p_cal]), axis=0)
        mean_p_te = np.mean(np.vstack([p_te[k] for k in p_te]), axis=0)
        thr = pick_threshold(mean_pc_cal, y_cal, target_risk, COSTS[name])
        thr_raw = pick_threshold(mean_p_cal, y_cal, target_risk, COSTS[name])
        ad_sim = knn_ad(mols_fit, mols_te)
        strats = strategies(p_te, ad_sim, thr, calib, thr_raw=thr_raw)
        for sname, (pred, dec) in strats.items():
            is_raw = sname.startswith("S5")
            base = {
                "endpoint": name,
                "seed": seed,
                "strategy": sname,
                "cost_point": "ref",
                "utility": round(utility(y_te, pred, dec, COSTS[name]), 4),
                "coverage": round(float(dec.mean()), 3),
                "risk_decided": (
                    round(float(np.mean(pred[dec] != y_te[dec])), 3)
                    if dec.sum()
                    else None
                ),
                "auc": round(
                    float(roc_auc_score(y_te, mean_p_te if is_raw else mean_pc_te)), 4
                ),
                "score_kind": "raw" if is_raw else "calibrated",
                "abstain_threshold": round(float(thr_raw if is_raw else thr), 3),
                "n": int(len(y_te)),
            }
            rows.append(base)
            # R17：代价敏感性剖面（同一预测，只改代价，不重训）
            for ca in ABSTAIN_GRID:
                rows.append(
                    dict(
                        base,
                        cost_point="abstain=%.2f" % ca,
                        utility=round(utility(y_te, pred, dec, (5.0, 1.0, ca)), 4),
                    )
                )
            for cfp in FPASS_GRID:
                rows.append(
                    dict(
                        base,
                        cost_point="false_pass=%.1f" % cfp,
                        utility=round(utility(y_te, pred, dec, (cfp, 1.0, 0.2)), 4),
                    )
                )

        # ---- B6 / C18（2026-11-04）：第二条流水线 π(c) ----
        # 与 R17「同一预测，只改代价，不重训」的本质区别：这里每档代价都重新
        # 求解决策（最小期望代价），逐档落 sha256(decided_mask)。若各档 hash
        # 全同，说明代价仍未进入决策，Δu(c) 依旧只是事后重标价的会计恒等式。
        pi_cost_points = [("ref", COSTS[name])]
        pi_cost_points += [
            ("abstain=%.2f" % ca, (COSTS[name][0], COSTS[name][1], ca))
            for ca in ABSTAIN_GRID
        ]
        pi_cost_points += [
            ("false_pass=%.1f" % cfp, (cfp, COSTS[name][1], 0.2)) for cfp in FPASS_GRID
        ]
        for cp, cst in pi_cost_points:
            pi_strats = strategies(p_te, ad_sim, thr, calib, thr_raw=thr_raw, costs=cst)
            pred6, dec6 = pi_strats["S6_cost_sensitive"]
            mask_hash = hashlib.sha256(
                json.dumps([bool(x) for x in dec6], separators=(",", ":")).encode(
                    "utf-8"
                )
            ).hexdigest()
            pi_rows.append(
                dict(
                    endpoint=name,
                    seed=seed,
                    cost_point=cp,
                    costs=list(cst),
                    decided_mask_sha256=mask_hash,
                    bayes_fail_threshold=round(bayes_threshold_from_costs(cst), 4),
                    n_decided=int(dec6.sum()),
                    n_abstained=int((~dec6).sum()),
                    coverage=round(float(dec6.mean()), 3),
                    utility=round(utility(y_te, pred6, dec6, cst), 4),
                    n=int(len(y_te)),
                    pipeline="pi_cost_sensitive_S6",
                )
            )
    return (rows, pi_rows) if return_pi else rows


def summarize(rows):
    out = []
    keys = sorted(
        {(r["endpoint"], r["strategy"], r.get("cost_point", "ref")) for r in rows}
    )
    for ep, st, cp in keys:
        sub = [
            r
            for r in rows
            if r["endpoint"] == ep
            and r["strategy"] == st
            and r.get("cost_point", "ref") == cp
        ]
        u = np.array([r["utility"] for r in sub])
        c = np.array([r["coverage"] for r in sub])
        rk = [r["risk_decided"] for r in sub if r["risk_decided"] is not None]
        out.append(
            {
                "endpoint": ep,
                "strategy": st,
                "cost_point": cp,
                "n_seeds": len(sub),
                "utility_median": round(float(np.median(u)), 4),
                "utility_iqr": [
                    round(float(np.percentile(u, 25)), 4),
                    round(float(np.percentile(u, 75)), 4),
                ],
                "coverage_median": round(float(np.median(c)), 3),
                "risk_decided_median": (round(float(np.median(rk)), 3) if rk else None),
            }
        )
    return out


STRATEGIES = (
    "S1_naive_majority",
    "S2_ad_guard",
    "S3_calibrated_conformal",
    "S4_full_admission",
    "S5_uncalibrated_conf",
)


def paired_vs_baseline(rows, base="S1_naive_majority", cost_point="ref", targets=None):
    """R08/A10：配对差值（同种子）的 median [IQR]，并给 bootstrap 95%CI。"""
    out = []
    eps = sorted({r["endpoint"] for r in rows})
    rows = [r for r in rows if r.get("cost_point", "ref") == cost_point]
    targets = targets or [s for s in STRATEGIES if s != base]
    for ep in eps:
        for st in targets:
            if st == base:
                continue
            a = {
                r["seed"]: r["utility"]
                for r in rows
                if r["endpoint"] == ep and r["strategy"] == st
            }
            b = {
                r["seed"]: r["utility"]
                for r in rows
                if r["endpoint"] == ep and r["strategy"] == base
            }
            common = sorted(set(a) & set(b))
            if not common:
                continue
            d = np.array([a[s] - b[s] for s in common])
            rng = np.random.default_rng(0)
            # 统计量必须与点估计一致：点估计报 median，bootstrap 也必须对 median 做。
            # （v4.2 及以前这里用的是 mean，导致出现"中位数落在 CI 之外"的自相矛盾结果。）
            boot = np.array(
                [np.median(rng.choice(d, len(d), replace=True)) for _ in range(2000)]
            )
            lo, hi = np.percentile(boot, [2.5, 97.5])
            out.append(
                {
                    "endpoint": ep,
                    "cost_point": cost_point,
                    "compare": "%s - %s" % (st, base),
                    "n_pairs": len(d),
                    "delta_median": round(float(np.median(d)), 4),
                    "delta_iqr": [
                        round(float(np.percentile(d, 25)), 4),
                        round(float(np.percentile(d, 75)), 4),
                    ],
                    "boot_ci95": [round(float(lo), 4), round(float(hi), 4)],
                    "significant": bool(lo > 0 or hi < 0),
                    "direction": "better" if np.median(d) > 0 else "worse",
                }
            )
    return out


def legacy_delta_points(sweep, compare="S4_full_admission - S1_naive_majority"):
    """从 cost_sweep 提取**旧流水线** Δu(c) 的 (c_abstain, delta_median) 点，按端点分组。

    只取 abstain 轴；false_pass 轴不是同一条 c 轴，混进线性拟合会伪造 R²。
    """
    out = {}
    for cp, ds in (sweep or {}).items():
        if not cp.startswith("abstain="):
            continue
        try:
            c = float(cp.split("=", 1)[1])
        except (ValueError, IndexError):
            continue
        for d in ds:
            if d.get("compare") == compare:
                out.setdefault(d["endpoint"], []).append((c, d["delta_median"]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--endpoints", default=",".join(ENDPOINTS))
    ap.add_argument("--model-family", default="rf", choices=["rf", "et", "gbm", "lr"],
                    help="tree ensemble behind the Morgan/MACCS sources; "
                         "used to test whether c* depends on the learner")
    ap.add_argument("--cache", default="out_ext/tdc_cache")
    ap.add_argument("--outdir", default="out_keystone")
    ap.add_argument("--target-risk", type=float, default=0.15, dest="target_risk")
    a = ap.parse_args()
    global MODEL_FAMILY
    MODEL_FAMILY = a.model_family
    os.makedirs(a.outdir, exist_ok=True)
    all_rows = []
    all_pi_rows = []
    for ep in [x for x in a.endpoints.split(",") if x]:
        print("[keystone] endpoint=%s seeds=%d ..." % (ep, a.seeds), flush=True)
        rows, pi_rows = run_endpoint(
            ep, list(range(a.seeds)), a.cache, a.target_risk, return_pi=True
        )
        all_rows.extend(rows)
        all_pi_rows.extend(pi_rows)
        for s in summarize(rows):
            print(
                "   %-14s %-26s U=%-8s cov=%-6s risk=%-6s"
                % (
                    s["strategy"],
                    "",
                    s["utility_median"],
                    s["coverage_median"],
                    s["risk_decided_median"],
                ),
                flush=True,
            )
    summ = summarize(all_rows)
    diffs = paired_vs_baseline(all_rows)
    diffs_s5 = paired_vs_baseline(all_rows, base="S5_uncalibrated_conf")
    cps = (
        ["ref"]
        + ["abstain=%.2f" % c for c in ABSTAIN_GRID]
        + ["false_pass=%.1f" % c for c in FPASS_GRID]
    )
    sweep = {cp: paired_vs_baseline(all_rows, cost_point=cp) for cp in cps}
    sweep_s5 = {
        cp: paired_vs_baseline(all_rows, cost_point=cp, base="S5_uncalibrated_conf")
        for cp in cps
    }
    # B6 / C18：把「旧流水线是不是会计恒等式」与「新流水线代价是否进决策」
    # 分别裁决后写入产物；旧主张 c* / 无差异点 / 条件性优势区的撤回状态由
    # R18_accounting_identity 在报告落盘前机械拦截，不依赖人去记。
    cost_audit = CD.audit_pipeline(all_pi_rows, legacy_delta_points(sweep))
    payload = {
        "seeds": a.seeds,
        "endpoints": a.endpoints,
        "costs": COSTS,
        "ad_threshold": AD_THRESHOLD,
        "target_risk": a.target_risk,
        "strategies": list(STRATEGIES),
        "per_run": all_rows,
        "summary": summ,
        "paired_vs_S1": diffs,
        "paired_vs_S5": diffs_s5,
        "cost_sweep": sweep,
        "cost_sweep_vs_S5": sweep_s5,
        "cost_decision_audit": cost_audit,
        "pi_cost_sensitive_rows": all_pi_rows,
        "schema_version": "2.0_cost_sensitive",
    }
    with io.open(os.path.join(a.outdir, "results.json"), "w", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False, indent=2))
    print("[keystone] -> %s/results.json" % a.outdir)
    print(
        "[keystone][C18] legacy_accounting_only=%s | pi 决策随代价变化的组 %d/%d | "
        "cost_sensitive_decision_verified=%s | 旧主张=%s"
        % (
            cost_audit["legacy_accounting_only"],
            cost_audit["groups_with_decision_varying"],
            cost_audit["n_groups"],
            cost_audit["cost_sensitive_decision_verified"],
            cost_audit["legacy_claim_status"],
        ),
        flush=True,
    )
    for label, sw in (("vs S1", sweep), ("vs S5(未校准)", sweep_s5)):
        print("=== 代价扫描 %s ===" % label)
        for cp, ds in sw.items():
            win = sum(1 for d in ds if d["significant"] and d["direction"] == "better")
            lose = sum(1 for d in ds if d["significant"] and d["direction"] == "worse")
            print(
                "   [cost %-14s] 显著更优 %d / 显著更差 %d / 共 %d"
                % (cp, win, lose, len(ds))
            )
    for label, ds in (("vs S1", diffs), ("vs S5", diffs_s5)):
        print("=== 配对差值 %s ===" % label)
        for d in ds:
            print(
                "   %-14s %-46s Δ=%+.4f CI[%+.4f,%+.4f] %s"
                % (
                    d["endpoint"],
                    d["compare"],
                    d["delta_median"],
                    d["boot_ci95"][0],
                    d["boot_ci95"][1],
                    "SIG" if d["significant"] else "ns",
                )
            )


if __name__ == "__main__":
    main()
