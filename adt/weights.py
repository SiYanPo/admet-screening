# -*- coding: utf-8 -*-
"""R-A1：源级权重方案的实证裁决。

评审 A1 原话（意译）：框架声称"按独立组收缩权重"，但从没证明过它比
①简单等权 ②贝叶斯模型平均(BMA) ③多样性折扣 更好——"无实证裁决"。

本模块把三种方案实现成**同一接口**，让数据来判：

  equal      w_i = 1/k
  shrink     w_i ∝ 1/(1 + (k−1)·ρ̄_i)，ρ̄_i = 与其他源的平均相关（框架现行式）
  bma        Dawid–Skene 式 EM 估每源 (sens, spec)，w_i ∝ 该源的平均对数似然比
  diversity  w_i ∝ acc_i × (1 − 平均不一致率)（Kuncheva 式折扣）

**诚实边界（必须写进报告）**：
  · `bma` 是**源级似然代理**，不是严格的模型边际似然（后者需要对每个源做
    超参积分，本框架没有源级后验）。命名保留 bma 是为了与评审用词对齐，
    返回值里 `strict=False` 会明说这一点。
  · 权重一律在 **calibration split** 上估计，再原样应用到 test；禁止用 test 调权重。
  · k=3 时四种方案的权重差异可能小于种子噪声——那就如实报"无显著差异"，
    不得挑一个最有利的说"更好"。
"""

import math

import numpy as np

EPS = 1e-6


def _norm(w):
    w = np.asarray([max(0.0, float(x)) for x in w], dtype=float)
    s = w.sum()
    if not np.isfinite(s) or s <= 0:
        return np.ones(len(w)) / float(len(w))
    return w / s


def equal_weights(k):
    return np.ones(int(k)) / float(k)


def shrink_weights(P_cal, rho=None):
    """框架现行式：w_i ∝ 1/(1+(k−1)ρ̄_i)，ρ̄_i = 与其他源相关的均值。

    P_cal: (n, k) 校准集上的源概率。ρ 用 Pearson 相关（与 independence.py 同口径）。
    ρ 取 max(ρ,0)：负相关不奖励（与 rho_contraction_weight 一致）。
    """
    P = np.asarray(P_cal, dtype=float)
    k = P.shape[1]
    if rho is None:
        with np.errstate(invalid="ignore", divide="ignore"):
            R = np.corrcoef(P, rowvar=False)
        R = np.nan_to_num(R, nan=0.0)
    else:
        R = np.asarray(rho, dtype=float)
    if k == 1:
        return np.ones(1)
    w = []
    for i in range(k):
        others = [R[i, j] for j in range(k) if j != i]
        rbar = float(np.mean(others)) if others else 0.0
        w.append(1.0 / (1.0 + (k - 1) * max(rbar, 0.0)))
    return _norm(w)


def _em_source_params(P_bin, n_iter=200, tol=1e-8):
    """Dawid–Skene 二分类 EM：估每源 sens/spec 与类别先验。

    P_bin: (n, k) 二值投票（0/1）。
    """
    V = np.asarray(P_bin, dtype=int)
    n, k = V.shape
    pi = float(np.clip(V.mean(), 0.05, 0.95))
    sens = np.full(k, 0.8)
    spec = np.full(k, 0.8)
    for _ in range(n_iter):
        # E 步
        lp1 = math.log(max(pi, EPS))
        lp0 = math.log(max(1 - pi, EPS))
        for i in range(k):
            v = V[:, i]
            lp1 += np.where(
                v == 1, math.log(max(sens[i], EPS)), math.log(max(1 - sens[i], EPS))
            )
            lp0 += np.where(
                v == 0, math.log(max(spec[i], EPS)), math.log(max(1 - spec[i], EPS))
            )
        m = np.maximum(lp1, lp0)
        p1 = np.exp(lp1 - m) / (np.exp(lp1 - m) + np.exp(lp0 - m))
        # M 步
        pi_new = float(np.clip(p1.mean(), 0.01, 0.99))
        sens_new = np.zeros(k)
        spec_new = np.zeros(k)
        for i in range(k):
            v = V[:, i]
            pos = v == 1
            neg = v == 0
            den1 = p1.sum()
            den0 = (1 - p1).sum()
            sens_new[i] = (p1[pos].sum() / den1) if den1 > 0 else sens[i]
            spec_new[i] = ((1 - p1)[neg].sum() / den0) if den0 > 0 else spec[i]
            sens_new[i] = float(np.clip(sens_new[i], 0.05, 0.95))
            spec_new[i] = float(np.clip(spec_new[i], 0.05, 0.95))
        delta = max(
            np.abs(sens_new - sens).max(),
            np.abs(spec_new - spec).max(),
            abs(pi_new - pi),
        )
        pi, sens, spec = pi_new, sens_new, spec_new
        if delta < tol:
            break
    return dict(pi=pi, sens=sens.tolist(), spec=spec.tolist())


def bma_weights(P_cal, y_cal, n_iter=200):
    """源级似然代理权重：w_i ∝ 平均对数似然比（越大越有判别信息）。"""
    P = np.asarray(P_cal, dtype=float)
    k = P.shape[1]
    par = _em_source_params((P >= 0.5).astype(int), n_iter=n_iter)
    w = []
    for i in range(k):
        se, sp = par["sens"][i], par["spec"][i]
        llr_pos = math.log(max(se, EPS) / max(1 - sp, EPS))
        llr_neg = math.log(max(sp, EPS) / max(1 - se, EPS))
        w.append(0.5 * (llr_pos + llr_neg))
    return _norm(w)


def diversity_weights(P_cal, y_cal, gamma=4.0, lam=0.5):
    """冗余感知权重：w_i ∝ acc_i^gamma · (1 - lam · max_agree_i)。

    两个坑都是实测踩出来的，写在这里防止再犯：

    (1) 方向：初版按「与其他源的平均不一致率」降权，惩罚了提供互补信息的源
        （3 源里两源重复、一源独特时，独特源拿到最低权重）——方向相反。
    (2) 量级：若让冗余因子单独主导（acc × (1-max_agree)），完全重复的源会被压到 0，
        **随机源反而成为最大权重**（随机源与谁都只 ~50% 一致）。所以必须让准确率
        主导：gamma=4 时 acc 0.8 与 0.6 的权重比约 3.2:1，冗余只做微扰。

    推论（必须写进报告，不能藏）：**两个信息完全相同的源在数学上不可区分**，
    本方案会给它们相同权重。多样性折扣能做的只是压制「与全体高度雷同但准确率平平」
    的源，它无法凭空造出区分度。在小 k（3 源）场景它通常只是等权的小幅扰动——
    实际后果由 A1 的实测结果说话。
    """
    P = np.asarray(P_cal, dtype=float)
    y = np.asarray(y_cal).astype(int)
    k = P.shape[1]
    V = (P >= 0.5).astype(int)
    acc = np.array([float(np.mean(V[:, i] == y)) for i in range(k)])
    w = []
    for i in range(k):
        agrees = [float(np.mean(V[:, i] == V[:, j])) for j in range(k) if j != i]
        mx = max(agrees) if agrees else 0.0
        w.append(max(0.0, acc[i]) ** gamma * (1.0 - lam * mx))
    return _norm(w)


SCHEMES = {
    "equal": lambda P, y: equal_weights(P.shape[1]),
    "shrink": lambda P, y: shrink_weights(P),
    "bma": lambda P, y: bma_weights(P, y),
    "diversity": lambda P, y: diversity_weights(P, y),
}


def combine(P, w):
    """加权组合源概率（归一化权重）。"""
    P = np.asarray(P, dtype=float)
    w = _norm(w)
    return P @ w


def score_prob(y_true, p, bins=10):
    """概率质量三件套：log-loss / Brier / AUC / acc@0.5。"""
    y = np.asarray(y_true).astype(int)
    p = np.clip(np.asarray(p, dtype=float), 1e-9, 1 - 1e-9)
    ll = float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
    brier = float(np.mean((p - y) ** 2))
    try:
        from sklearn.metrics import roc_auc_score

        auc = float(roc_auc_score(y, p)) if len(set(y.tolist())) > 1 else None
    except Exception:
        auc = None
    acc = float(np.mean((p >= 0.5).astype(int) == y))
    return {
        "log_loss": round(ll, 4),
        "brier": round(brier, 4),
        "auc": round(auc, 4) if auc is not None else None,
        "acc_at_0.5": round(acc, 4),
    }


def compare(P_cal, y_cal, P_te, y_te, schemes=None):
    """在 cal 上估权重 → 在 test 上打分。返回 {scheme: {weights, metrics}}。"""
    schemes = schemes or list(SCHEMES)
    out = {}
    for name in schemes:
        w = SCHEMES[name](P_cal, y_cal)
        p = combine(P_te, w)
        m = score_prob(y_te, p)
        m["weights"] = [round(float(x), 4) for x in w]
        m["strict"] = name != "bma"
        out[name] = m
    return out
