# -*- coding: utf-8 -*-
"""P8 回归支：连续端点（溶解度 / Caco2 / 脂溶性）的 MMP 校准检验。

背景（黑榜 2 的尾巴）：
  分类端点的 MMP 判据是"翻转率"，对连续标签无意义（每对都"变"了）。
  `adt/mmp.analyze_regression()` 改用**位移幅度比** R = median|Δpred| / median|Δlabel|，
  但上一版只做了接口与合成测试，**没在真实回归端点上跑过**。本脚本补这一刀。

判据（TOST 风格，配对 bootstrap，预注册）：
  · R 的 95%CI ⊂ (0.5, 1.5) → equivalent（幅度感一致）
  · CI 上界 < 0.5 → insensitive（模型对结构变化不敏感）
  · CI 下界 > 1.5 → oversensitive
  · 其余 → inconclusive
  · n < 30 对 → insufficient_power，不判

辅助指标（不参与判定，仅用于定位方向）：
  · sign_agreement：Δpred 与 Δlabel 同号的占比（随机 ≈ 0.5）
  · median |Δlabel| / |Δpred|：量级对照

输出：out_ext/tdc/p8_mmp_reg_<endpoint>.json
"""
import argparse
import io
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rdkit import Chem, DataStructs, RDLogger                     # noqa: E402
from rdkit.Chem import AllChem, Descriptors, MACCSkeys, rdMolDescriptors  # noqa: E402
from sklearn.ensemble import RandomForestRegressor                # noqa: E402
from sklearn.linear_model import Ridge                            # noqa: E402
from sklearn.preprocessing import StandardScaler                  # noqa: E402

from adt import mmp                                               # noqa: E402

RDLogger.DisableLog("rdApp.*")

MIN_PAIRS = 30
# bootstrap 是 O(n_boot × n_pairs)：溶解度全量能产生数十万对，
# 不设上限会让 4000 次 bootstrap 退化成小时级。抽样上限必须在报告里声明。
MAX_PAIRS = 20000


def fp_morgan(m):
    return AllChem.GetMorganFingerprintAsBitVect(m, 2, nBits=2048)


def fp_maccs(m):
    return MACCSkeys.GenMACCSKeys(m)


def to_np(fps, nbits):
    X = np.zeros((len(fps), nbits), dtype=np.int8)
    for i, f in enumerate(fps):
        DataStructs.ConvertToNumpyArray(f, X[i])
    return X


def desc_vec(m):
    v = np.array([
        Descriptors.MolWt(m), Descriptors.MolLogP(m), Descriptors.TPSA(m),
        Descriptors.NumHDonors(m), Descriptors.NumHAcceptors(m),
        Descriptors.RingCount(m), rdMolDescriptors.CalcFractionCSP3(m),
        Descriptors.NumRotatableBonds(m), Descriptors.NumAromaticRings(m),
    ], dtype=float)
    return np.nan_to_num(v, nan=0.0, posinf=0.0, neginf=0.0)


def fit_models(mols_tr, y_tr, seed=0):
    """训练一次，返回 (models, scaler)。**不重复训练**——扩样本分支只重预测。"""
    Xm = to_np([fp_morgan(m) for m in mols_tr], 2048)
    Xc = to_np([fp_maccs(m) for m in mols_tr], 167)
    Xd = np.array([desc_vec(m) for m in mols_tr])
    sc = StandardScaler().fit(Xd)
    models = {
        "rf_morgan": RandomForestRegressor(n_estimators=400, random_state=seed,
                                           n_jobs=1).fit(Xm, y_tr),
        "rf_maccs": RandomForestRegressor(n_estimators=400, random_state=seed,
                                          n_jobs=1).fit(Xc, y_tr),
        "ridge_desc": Ridge(alpha=1.0).fit(sc.transform(Xd), y_tr),
    }
    return models, sc


def predict_with(models, sc, mols):
    Tm = to_np([fp_morgan(m) for m in mols], 2048)
    Tc = to_np([fp_maccs(m) for m in mols], 167)
    Td = sc.transform(np.array([desc_vec(m) for m in mols]))
    p = {"rf_morgan": models["rf_morgan"].predict(Tm),
         "rf_maccs": models["rf_maccs"].predict(Tc),
         "ridge_desc": models["ridge_desc"].predict(Td)}
    p["ensemble_mean"] = np.mean(list(p.values()), axis=0)
    return p


def sign_agreement(pairs, y_values, preds):
    same = 0
    n = 0
    for _core, ia, ib, _fa, _fb in pairs:
        dy = float(y_values[ib]) - float(y_values[ia])
        dp = float(preds[ib]) - float(preds[ia])
        if abs(dy) < 1e-12 or abs(dp) < 1e-12:
            continue
        n += 1
        if (dy > 0) == (dp > 0):
            same += 1
    return (round(same / n, 3) if n else None), n


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint", default="solubility_aqsoldb")
    ap.add_argument("--cache", default="out_ext/tdc_cache")
    ap.add_argument("--ratio-margin", type=float, default=0.5, dest="ratio_margin")
    a = ap.parse_args(argv)
    ep = a.endpoint

    from adt.tdc_local import load_split
    d = load_split(a.cache, ep)

    def _xy(df):
        mols, ys = [], []
        for _, r in df.iterrows():
            m = Chem.MolFromSmiles(str(r["Drug"]))
            if m is None:
                continue
            mols.append(m)
            ys.append(float(r["Y"]))
        return mols, np.array(ys, dtype=float)

    mols_tr, y_tr = _xy(d["train_val"])
    mols_te, y_te = _xy(d["test"])
    print("[p8-reg] %s train=%d test=%d  y_range=[%.2f, %.2f]"
          % (ep, len(mols_tr), len(mols_te), y_te.min(), y_te.max()), flush=True)

    models, sc = fit_models(mols_tr, y_tr, seed=0)
    preds_all = predict_with(models, sc, mols_te)
    smis_te = [Chem.MolToSmiles(m) for m in mols_te]
    pairs, stats_te = mmp.fragment_pairs(smis_te, max_cuts=1, min_core=6, min_frag=1)
    scope = "test_only"
    stats_all = stats_te
    y_use = y_te
    n_pairs_raw, n_pairs = len(pairs), len(pairs)
    # 分类版在 test 对子不足时会扩到 train+test；**回归版不这样做**：
    # 扩样本会把 in-sample 预测混进来，而回归的 Δpred 对 in-sample 天然更贴合，
    # 会让 R 偏向 1（假阳性"等效"）。宁可判 insufficient_power。
    if n_pairs < MIN_PAIRS:
        print("[p8-reg] test 集只有 %d 对（<%d）→ 将判 insufficient_power，"
              "不扩到 train+test（避免 in-sample 偏差）" % (n_pairs, MIN_PAIRS),
              flush=True)
    subsampled = False
    if n_pairs > MAX_PAIRS:
        rng = np.random.default_rng(0)
        keep = np.sort(rng.choice(n_pairs, MAX_PAIRS, replace=False))
        pairs = [pairs[i] for i in keep]
        subsampled = True
        n_pairs = len(pairs)
        print("[p8-reg] 对子数 %d > 上限 %d，已按种子 0 无放回抽样（报告须声明）"
              % (n_pairs_raw, MAX_PAIRS), flush=True)

    results = {}
    for src, pred in preds_all.items():
        res = mmp.analyze_regression(pairs, y_use, pred,
                                     ratio_margin=a.ratio_margin, n_boot=2000)
        if res.get("n_pairs", 0) == 0:
            results[src] = res
            continue
        sa, sa_n = sign_agreement(pairs, y_use, pred)
        res["sign_agreement"] = sa
        res["sign_agreement_n"] = sa_n
        results[src] = res

    payload = {
        "endpoint": ep,
        "task": "regression",
        "mmp_scope": scope,
        "n_pairs_used": res.get("n_pairs"),
        "n_pairs_raw": n_pairs_raw,
        "subsampled": subsampled,
        "max_pairs": MAX_PAIRS,
        "n_train": len(mols_tr), "n_test": len(mols_te),
        "mmp_stats": (stats_te if scope == "test_only" else stats_all),
        "ratio_margin": a.ratio_margin,
        "min_pairs": MIN_PAIRS,
        "results": results,
        "note": ("位移幅度比 R 对基准值敏感：R 是相对量，若模型整体压缩了预测幅度"
                 "（回归到均值），R<1 是数学必然，不等于结构不敏感。"
                 "因此本表必须与 sign_agreement 合读：R<1 但符号一致率高，"
                 "说明模型方向对、幅度被压缩；R<1 且符号一致率≈0.5，才是真迟钝。"),
    }
    os.makedirs("out_ext/tdc", exist_ok=True)
    outp = "out_ext/tdc/p8_mmp_reg_%s.json" % ep
    with io.open(outp, "w", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False, indent=2))

    print("[p8-reg] scope=%s pairs=%d" % (scope, res.get("n_pairs")), flush=True)
    for src, r in results.items():
        if "overall" not in r:
            print("   %-16s %s" % (src, r.get("status")), flush=True)
            continue
        o = r["overall"]
        print("   %-16s R=%.3f CI[%.3f,%.3f] power=%-5s dir=%-18s sign=%s (n=%s)"
              % (src, o["displacement_ratio"], o["ratio_ci95"][0],
                 o["ratio_ci95"][1], r.get("power", {}).get("adequate"),
                 r["direction"], r.get("sign_agreement"),
                 r.get("sign_agreement_n")), flush=True)
    print("[p8-reg] -> %s" % outp)


if __name__ == "__main__":
    main()
