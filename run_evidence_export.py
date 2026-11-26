# -*- coding: utf-8 -*-
"""中间量导出：为黑榜三项（C9 统一分数口径 / A1 权重方案裁决 / A4 基线强度）提供
**同一批**分子级预测，避免三项各训一遍模型导致口径漂移。

导出内容（每个端点一个 .npz）：
  y            (n_te,)              测试集真实标签（1=FAIL）
  ad_sim       (n_te,)              到 fit 集的最大 Tanimoto（与种子无关，只算一次）
  y_cal        (n_cal,)             校准集标签
  P_raw        (n_seeds,n_te,K)     未校准源概率（K=4：三源 + 强基线）
  P_cal        (n_seeds,n_te,K)     校准后源概率（isotonic，在 cal 集上拟合）
  Pc_raw/cal   (n_seeds,n_cal,K)    同上，作用于校准集
  SRC                        源名列表
  P_strong_raw (n_seeds,n_te)       强基线未校准（A4 用）
  P_strong_cal (n_seeds,n_te)       强基线校准后

强基线存在的唯一理由是 A4：原实验四个策略共用"弱基线"（RF300 + Ridge + RF-MACCS），
评审 A4 质疑治理结论能否外推到更强模型。此处加 HistGradientBoosting + 指纹/描述符拼接，
只改"基线强度"这一个维度。
"""
import argparse
import io
import json
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from rdkit import Chem, DataStructs, RDLogger                      # noqa: E402
RDLogger.DisableLog("rdApp.*")

from sklearn.ensemble import HistGradientBoostingClassifier          # noqa: E402

import run_keystone as K                                            # noqa: E402

SRC = ("rf_morgan", "ridge_desc", "rf_maccs")


def fit_strong(mols_tr, y_tr, seed):
    """强基线：Morgan2048 + MACCS167 + 10 个描述符拼接 → HistGradientBoosting。"""
    Xm = K.to_np([K.fp_morgan(m) for m in mols_tr], 2048)
    Xc = K.to_np([K.fp_maccs(m) for m in mols_tr], 167)
    Xd = np.array([K.desc_vec(m) for m in mols_tr])
    X = np.hstack([Xm, Xc, Xd]).astype(np.float32)
    m = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.06,
                                       max_leaf_nodes=31, l2_regularization=1.0,
                                       random_state=seed).fit(X, y_tr)
    return m


def strong_proba(m, mols):
    Xm = K.to_np([K.fp_morgan(mm) for mm in mols], 2048)
    Xc = K.to_np([K.fp_maccs(mm) for mm in mols], 167)
    Xd = np.array([K.desc_vec(mm) for mm in mols])
    X = np.hstack([Xm, Xc, Xd]).astype(np.float32)
    return m.predict_proba(X)[:, 1]


def isotonic_fit(v, y):
    from sklearn.isotonic import IsotonicRegression
    iso = IsotonicRegression(out_of_bounds="clip").fit(v, y)
    return lambda x: iso.predict(x)


def run(name, seeds, cache):
    (mols_tr, y_tr), (mols_te, y_te) = K.load_endpoint(name, cache)
    rng = np.random.default_rng(0)
    idx = rng.permutation(len(mols_tr))
    cut = int(0.8 * len(mols_tr))
    fit_i, cal_i = idx[:cut], idx[cut:]
    mols_fit = [mols_tr[i] for i in fit_i]
    y_fit = y_tr[fit_i]
    mols_cal = [mols_tr[i] for i in cal_i]
    y_cal = y_tr[cal_i]

    # ad_sim 与种子无关（fit 集固定）→ 只算一次
    t0 = time.time()
    ad_te = K.knn_ad(mols_fit, mols_te)
    ad_cal = K.knn_ad(mols_fit, mols_cal)
    print("[export] %s AD 相似度算完 %.1fs" % (name, time.time() - t0), flush=True)

    n_te, n_cal = len(mols_te), len(mols_cal)
    K_n = len(SRC) + 1
    P_raw = np.zeros((len(seeds), n_te, K_n), dtype=np.float32)
    P_cal = np.zeros_like(P_raw)
    C_raw = np.zeros((len(seeds), n_cal, K_n), dtype=np.float32)
    C_cal = np.zeros_like(C_raw)

    for si, seed in enumerate(seeds):
        models, sc = K.fit_sources(mols_fit, y_fit, seed)
        p_te = K.predict_sources(models, sc, mols_te)
        p_ca = K.predict_sources(models, sc, mols_cal)
        sm = fit_strong(mols_fit, y_fit, seed)
        p_te_s = strong_proba(sm, mols_te)
        p_ca_s = strong_proba(sm, mols_cal)
        for j, nm in enumerate(SRC):
            P_raw[si, :, j] = p_te[nm]
            C_raw[si, :, j] = p_ca[nm]
            f = isotonic_fit(C_raw[si, :, j], y_cal)
            P_cal[si, :, j] = f(P_raw[si, :, j])
            C_cal[si, :, j] = f(C_raw[si, :, j])
        P_raw[si, :, -1] = p_te_s
        C_raw[si, :, -1] = p_ca_s
        f = isotonic_fit(C_raw[si, :, -1], y_cal)
        P_cal[si, :, -1] = f(P_raw[si, :, -1])
        C_cal[si, :, -1] = f(C_raw[si, :, -1])
        if si % 5 == 0:
            print("[export] %s seed=%d (%d/%d) %.1fs"
                  % (name, seed, si + 1, len(seeds), time.time() - t0), flush=True)

    return dict(y=y_te.astype(np.int8), ad_sim=ad_te.astype(np.float32),
                ad_sim_cal=ad_cal.astype(np.float32),
                y_cal=y_cal.astype(np.int8),
                P_raw=P_raw, P_cal=P_cal, C_raw=C_raw, C_cal=C_cal,
                SRC=np.array(list(SRC) + ["strong_hgb"]),
                seeds=np.array(seeds))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--endpoints", default=",".join(K.ENDPOINTS))
    ap.add_argument("--cache", default="out_ext/tdc_cache")
    ap.add_argument("--outdir", default="out_blacklist")
    a = ap.parse_args()
    os.makedirs(a.outdir, exist_ok=True)
    meta = {}
    for ep in [x for x in a.endpoints.split(",") if x]:
        print("[export] === %s ===" % ep, flush=True)
        d = run(ep, list(range(a.seeds)), a.cache)
        p = os.path.join(a.outdir, "export_%s.npz" % ep)
        np.savez_compressed(p, **d)
        meta[ep] = dict(n_te=int(len(d["y"])), n_cal=int(len(d["y_cal"])),
                        bytes=os.path.getsize(p),
                        pos_rate_te=round(float(d["y"].mean()), 4),
                        pos_rate_cal=round(float(d["y_cal"].mean()), 4))
        print("[export] -> %s (%.1f KB)" % (p, os.path.getsize(p) / 1024.0), flush=True)
    with io.open(os.path.join(a.outdir, "export_meta.json"), "w",
                 encoding="utf-8") as f:
        f.write(json.dumps(meta, ensure_ascii=False, indent=2))
    print(json.dumps(meta, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
