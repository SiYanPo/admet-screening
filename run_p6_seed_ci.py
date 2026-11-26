# -*- coding: utf-8 -*-
"""A10 / F7 补漏：Caco2「泄漏使表观变好 0.0245」的种子噪声裁决。

评审原话（F7）："Caco2 MAE 0.4128→0.3883 的'表观变好 0.0245'，n=182，**未报种子方差**。
RF + Morgan 基线在种子间 MAE 抖动典型可达 ±0.01–0.03——这个'泄漏使表观变好'的旗舰结论
**完全可能在种子噪声范围内**。"

本脚本把该结论放到 20 个种子上做**配对**裁决：
  · 每个种子训练两个模型（干净版 / 注入 ≥0.7 近重复版），其余完全固定；
  · 配对差 Δ = MAE_contaminated − MAE_clean（同一批测试分子、同一批注入样本）；
  · 报 Δ 的中位数与配对 bootstrap 95%CI，以及两个版本各自的种子间 IQR。

判读规则（预先写死，不允许事后改）：
  · CI 完全 < 0  → 泄漏确实使表观误差下降，结论成立；
  · CI 含 0      → 只能写"方向一致但幅度未显著区别于种子噪声"，不得称"提升"；
  · CI 完全 > 0  → 结论反向（注入近重复反而更差）。
输出：out_ext/tdc/p6_seed_ci.json
"""
import io
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from rdkit import Chem, DataStructs, RDLogger                      # noqa: E402
from rdkit.Chem import AllChem                                     # noqa: E402
from sklearn.ensemble import RandomForestRegressor                 # noqa: E402
from sklearn.metrics import mean_absolute_error                    # noqa: E402

RDLogger.DisableLog("rdApp.*")

TDC_CACHE = os.path.join(ROOT, "out_ext", "tdc_cache")
OUT = os.path.join(ROOT, "out_ext", "tdc")


def _bv(smi):
    m = Chem.MolFromSmiles(smi)
    if m is None:
        return None
    return AllChem.GetMorganFingerprintAsBitVect(m, 2, nBits=2048)


def _arr(smi):
    bv = _bv(smi)
    if bv is None:
        return None
    a = np.zeros((2048,), dtype=np.int8)
    DataStructs.ConvertToNumpyArray(bv, a)
    return a


def load_caco2():
    from adt.tdc_local import load_split
    d = load_split(TDC_CACHE, "Caco2_Wang")

    def _xy(df):
        smis, ys = [], []
        for _, r in df.iterrows():
            s = str(r["Drug"])
            if _bv(s) is None:
                continue
            smis.append(s)
            ys.append(float(r["Y"]))
        return smis, ys

    return _xy(d["train_val"]), _xy(d["test"])


def build_sets(tr, te, dup_thr=0.7):
    smis_tr, y_tr = tr
    smis_te, y_te = te
    tr_bv = [_bv(s) for s in smis_tr]
    injected = []
    for s, y in zip(smis_te, y_te):
        bv = _bv(s)
        best = max(DataStructs.BulkTanimotoSimilarity(bv, tr_bv))
        if best >= dup_thr:
            injected.append((s, float(y)))
    aug_smis = list(smis_tr) + [s for s, _ in injected]
    aug_y = list(y_tr) + [y for _, y in injected]
    return aug_smis, aug_y, injected


def _x(smis):
    return np.array([_arr(s) for s in smis], dtype=np.int8)


def main(seeds=20, n_boot=4000):
    tr, te = load_caco2()
    aug_smis, aug_y, injected = build_sets(tr, te)
    Ytr = np.array(tr[1], dtype=float)
    Yaug = np.array(aug_y, dtype=float)
    Yte = np.array(te[1], dtype=float)

    Xtr = _x(tr[0])
    Xaug = _x(aug_smis)
    Xte = _x(te[0])

    clean_mae, cont_mae, deltas = [], [], []
    for sd in range(seeds):
        m_c = RandomForestRegressor(n_estimators=400, random_state=sd, n_jobs=-1)
        m_c.fit(Xtr, Ytr)
        mc = float(mean_absolute_error(Yte, m_c.predict(Xte)))

        m_k = RandomForestRegressor(n_estimators=400, random_state=sd, n_jobs=-1)
        m_k.fit(Xaug, Yaug)
        mk = float(mean_absolute_error(Yte, m_k.predict(Xte)))

        clean_mae.append(mc)
        cont_mae.append(mk)
        deltas.append(mk - mc)

    d = np.array(deltas)
    rng = np.random.default_rng(0)
    boots = np.array([np.median(rng.choice(d, len(d), replace=True))
                      for _ in range(n_boot)])
    lo, hi = float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))
    med = float(np.median(d))

    if hi < 0:
        verdict = "leak_gain_significant"
        interp = ("泄漏确实使表观 MAE 下降（配对中位差 %.4f，95%%CI [%.4f, %.4f] 完全 <0）→ "
                  "原结论成立，可称'数据泄漏使表观性能提升'。" % (med, lo, hi))
    elif lo > 0:
        verdict = "reversed"
        interp = ("配对差中位数 >0（[%.4f, %.4f]）→ 注入近重复后误差反而上升，原结论方向被推翻。"
                  % (lo, hi))
    else:
        verdict = "within_seed_noise"
        interp = ("配对中位差 %.4f，95%%CI [%.4f, %.4f] **含 0** → 只能表述为"
                  "'方向一致但幅度未显著区别于种子噪声'，**禁止**称'泄漏使表观性能提升'。"
                  % (med, lo, hi))

    payload = {
        "endpoint": "Caco2_Wang",
        "n_test": int(len(Yte)), "n_train": int(len(Ytr)),
        "n_injected": int(len(injected)), "dup_threshold": 0.7,
        "seeds": seeds,
        "baseline_model": "RandomForestRegressor(400) + Morgan2048",
        "per_seed": [{"seed": i, "mae_clean": round(clean_mae[i], 4),
                      "mae_contaminated": round(cont_mae[i], 4),
                      "delta": round(deltas[i], 4)} for i in range(seeds)],
        "mae_clean_median": round(float(np.median(clean_mae)), 4),
        "mae_contaminated_median": round(float(np.median(cont_mae)), 4),
        "mae_clean_iqr": [round(float(np.percentile(clean_mae, 25)), 4),
                          round(float(np.percentile(clean_mae, 75)), 4)],
        "mae_contaminated_iqr": [round(float(np.percentile(cont_mae, 25)), 4),
                                 round(float(np.percentile(cont_mae, 75)), 4)],
        "single_seed0_clean": round(clean_mae[0], 4),
        "single_seed0_contaminated": round(cont_mae[0], 4),
        "delta_median": round(med, 4),
        "delta_ci95": [round(lo, 4), round(hi, 4)],
        "delta_iqr": [round(float(np.percentile(d, 25)), 4),
                      round(float(np.percentile(d, 75)), 4)],
        "verdict": verdict,
        "interpretation": interp,
        "note": ("seed0 即历史单次运行值；若 seed0 的 Δ 与 20 种子的 Δ 分布显著不同，"
                 "说明历史上的单次点估计是幸运抽样，而非稳定效应。"),
    }
    os.makedirs(OUT, exist_ok=True)
    io.open(os.path.join(OUT, "p6_seed_ci.json"), "w", encoding="utf-8").write(
        json.dumps(payload, ensure_ascii=False, indent=2))
    print(json.dumps({k: v for k, v in payload.items() if k != "per_seed"},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    # C5（2026-11-03 评审）：本脚本无 argparse，此前 `--help` 会被当作普通参数，
    # 直接执行全流程（run_replication_pack 实测会**写出挑战包**）——在 CI/评审复现时
    # 是看不见的写盘者。加早退：--help 只打印用法并 exit 0，不产生任何副作用。
    import sys as _sys
    if any(_a in ("-h", "--help") for _a in _sys.argv[1:]):
        print("用法：%s（无命令行参数；直接运行即按默认配置产出产物）" % __file__)
        raise SystemExit(0)
    main()
