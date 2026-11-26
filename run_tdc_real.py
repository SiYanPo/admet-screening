# -*- coding: utf-8 -*-
"""真实 TDC ADMET 基准闭环（用户指令：安装软件用正版来源 + 继续执行未完成任务）。

目的：用 TDC 官方 ADMET benchmark（pytdc，官方 PyPI 安装）的真实切分与真实标签，
把 v4 拔高评审中"待真实数据"的 🟡 项跑出真实数值，而非合成占位：
  - P3  risk–coverage 曲线 + AURC + 全弃权基线 + 最优弃权率（hERG 真实标签）
  - L2-1 交换性漂移诊断（hERG 风险分层覆盖漂移）
  - P6  去污染：三档阈值真实剔除数 + 测试集近重复泄漏率 + 真实污染/干净两版 MAE 对照
  - L2-2 TDC 对齐：官方协议下真实 AUROC/AUPRC/MAE/R²，与 leaderboard 显式脱钩

全部数值来自真实 TDC 数据与真实基线模型（RandomForest + Morgan 指纹），不臆造。
预测性 AUROC 来自基线模型；框架贡献的是治理层（risk-coverage / 弃权 / 去污染 / 交换性）。
"""
import os
import sys
import json
import math
import warnings

warnings.filterwarnings("ignore")

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import numpy as np
from rdkit import Chem
from rdkit.Chem import AllChem, DataStructs
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.metrics import (roc_auc_score, average_precision_score,
                             mean_absolute_error, r2_score)

from adt.tdc_local import load_split
from adt.selective import risk_coverage_report, base_rate_stratified
from adt.decontamination import decontamination_report, remove_similar
from adt.conformal import exchangeability_drift
from adt.pred_displacement import randomization_null_control

TDC_CACHE = os.path.join(ROOT, "out_ext", "tdc_cache")
OUT = os.path.join(ROOT, "out_ext", "tdc")
os.makedirs(OUT, exist_ok=True)


def morgan_arr(smi):
    m = Chem.MolFromSmiles(smi)
    if m is None:
        return None
    fp = AllChem.GetMorganFingerprintAsBitVect(m, 2, nBits=2048)
    arr = np.zeros((2048,), dtype=np.int8)
    DataStructs.ConvertToNumpyArray(fp, arr)
    return arr


def morgan_bv(smi):
    """RDKit ExplicitBitVect（供 Tanimoto 相似度用）。"""
    m = Chem.MolFromSmiles(smi)
    if m is None:
        return None
    return AllChem.GetMorganFingerprintAsBitVect(m, 2, nBits=2048)


def fetch(name):
    d = load_split(TDC_CACHE, name)
    return d["train_val"], d["test"]


def xy(df):
    smis, ys = [], []
    for _, row in df.iterrows():
        smi = str(row["Drug"])
        arr = morgan_arr(smi)
        if arr is None:
            continue
        try:
            y = float(row["Y"])
        except Exception:
            continue
        smis.append(smi)
        ys.append(y)
    X = np.array([morgan_arr(s) for s in smis], dtype=np.int8)
    return smis, X, np.array(ys, dtype=float)


# ----------------------------------------------------------------------------
# 1) hERG（分类）—— P3 risk-coverage + L2-1 exchangeability
# ----------------------------------------------------------------------------
def run_herg():
    tv, te = fetch("hERG")
    smis_tr, Xtr, ytr = xy(tv)
    smis_te, Xte, yte = xy(te)
    ytr = ytr.astype(int)
    yte = yte.astype(int)
    clf = RandomForestClassifier(n_estimators=400, random_state=0, n_jobs=-1)
    clf.fit(Xtr, ytr)
    proba = clf.predict_proba(Xte)[:, 1]
    pred = (proba >= 0.5).astype(int)
    ok = (pred == yte)
    # risk = 模型自身的不确定性（判错概率上界）：1 - max(prob, 1-prob)
    risk = 1.0 - np.maximum(proba, 1.0 - proba)

    pairs = list(zip(risk.tolist(), ok.tolist()))
    rep = risk_coverage_report(pairs, target_risk=0.2)

    # 风险三分位分层（同一端点内按预测风险分低/中/高）
    idx = np.argsort(risk)
    n = len(idx)
    strata = []
    for lo, hi, lab in [(0, n // 3, "risk_low"), (n // 3, 2 * n // 3, "risk_mid"),
                        (2 * n // 3, n, "risk_high")]:
        sub = [pairs[i] for i in idx[lo:hi]]
        strata.append((lab, sub))
    strat = base_rate_stratified(pairs, strata)

    # L2-1 交换性漂移：按预测风险十分位分箱，箱内准确率 vs 全局准确率
    overall_acc = float(ok.mean())
    alpha = 1.0 - overall_acc
    edges = np.quantile(risk, np.linspace(0, 1, 11))
    bins = []
    for i in range(10):
        m = (risk > edges[i]) & (risk <= edges[i + 1]) if i < 9 else (risk >= edges[i])
        seg_ok = ok[m]
        nseg = int(seg_ok.size)
        acc = float(seg_ok.mean()) if nseg else 0.0
        bins.append((f"risk_decile_{i}", acc, nseg))
    drift = exchangeability_drift(bins, alpha=alpha)

    return dict(
        endpoint="hERG", n_train=len(ytr), n_test=len(yte),
        base_rate_pos=float(yte.mean()),
        auc_roc=float(roc_auc_score(yte, proba)),
        auc_pr=float(average_precision_score(yte, proba)),
        accuracy=overall_acc,
        p3=rep,
        p3_stratified=strat,
        l21=drift,
    )


# ----------------------------------------------------------------------------
# 2) Caco2_Wang（回归）—— P6 去污染 + 真实污染/干净两版 MAE 对照
# ----------------------------------------------------------------------------
def run_caco2():
    tv, te = fetch("Caco2_Wang")
    smis_tr, Xtr, ytr = xy(tv)
    smis_te, Xte, yte = xy(te)

    # 干净版：train_val 训练 -> test 评估
    rf_clean = RandomForestRegressor(n_estimators=400, random_state=0, n_jobs=-1)
    rf_clean.fit(Xtr, ytr)
    pred_clean = rf_clean.predict(Xte)
    mae_clean = float(mean_absolute_error(yte, pred_clean))
    r2_clean = float(r2_score(yte, pred_clean))

    # 去污染报告（训练集结构近重复三档）
    dec_report = decontamination_report(smis_tr, gears=(0.6, 0.7, 0.8))

    # 测试集近重复泄漏率：每个 test 分子对 train 的最大 Tanimoto
    train_bv = [morgan_bv(s) for s in smis_tr]
    test_bv = [morgan_bv(s) for s in smis_te]
    leak_hits = 0
    leak_max = []
    for tfp in test_bv:
        best = 0.0
        for kfp in train_bv:
            t = DataStructs.TanimotoSimilarity(tfp, kfp)
            if t > best:
                best = t
        leak_max.append(best)
        if best >= 0.7:
            leak_hits += 1
    leak_rate = leak_hits / float(len(test_bv))

    # 真实污染实验：把 test 的近重复（≥0.7）副本注入训练集，重训，看 test MAE 变化
    augmented_smis, augmented_y = list(smis_tr), list(ytr)
    injected = 0
    for s, yv in zip(smis_te, yte):
        # 找其最近 train 邻居
        tfp = morgan_bv(s)
        best = 0.0
        for kfp in train_bv:
            t = DataStructs.TanimotoSimilarity(tfp, kfp)
            if t > best:
                best = t
        if best >= 0.7:
            augmented_smis.append(s)
            augmented_y.append(float(yv))
            injected += 1
    Xaug = np.array([morgan_arr(s) for s in augmented_smis], dtype=np.int8)
    rf_cont = RandomForestRegressor(n_estimators=400, random_state=0, n_jobs=-1)
    rf_cont.fit(Xaug, np.array(augmented_y, dtype=float))
    pred_cont = rf_cont.predict(Xte)
    mae_cont = float(mean_absolute_error(yte, pred_cont))
    r2_cont = float(r2_score(yte, pred_cont))

    compare = compare_two_version_metrics_real(
        clean=dict(endpoint="Caco2_Wang", mae=mae_clean, r2=r2_clean),
        contaminated=dict(endpoint="Caco2_Wang", mae=mae_cont, r2=r2_cont))

    return dict(
        endpoint="Caco2_Wang", n_train=len(ytr), n_test=len(yte),
        mae_clean=mae_clean, r2_clean=r2_clean,
        mae_contaminated=mae_cont, r2_contaminated=r2_cont,
        injected_duplicates=injected,
        decontamination=dec_report,
        test_train_leak_rate=round(leak_rate, 4),
        test_train_leak_n=leak_hits,
        p6_compare=compare,
        baseline_mae_note="RandomForest+Morgan(2048) 基线，仅用于治理层演示，非 SOTA",
    )


def compare_two_version_metrics_real(clean, contaminated):
    """包装 decontamination.compare_two_version_metrics 的真实喂入。"""
    from adt.decontamination import compare_two_version_metrics
    clean_rows = [{"endpoint": clean["endpoint"], "mae": clean["mae"], "r2": clean["r2"]}]
    contaminated_rows = {contaminated["endpoint"]:
                        {"mae": contaminated["mae"], "r2": contaminated["r2"]}}
    return compare_two_version_metrics(clean_rows, contaminated_rows, metric_name="mae")


def main():
    print("==> hERG (P3 / L2-1)")
    herg = run_herg()
    print("    AUC-ROC=%.3f  AUC-PR=%.3f  acc=%.3f  AURC=%.3f  optimal_abstain=%.3f"
          % (herg["auc_roc"], herg["auc_pr"], herg["accuracy"],
             herg["p3"]["aurc"], herg["p3"]["optimal_abstain_rate"]))
    print("    exchangeability any_drift=%s" % herg["l21"]["any_drift"])

    print("==> Caco2_Wang (P6 / L2-2)")
    caco = run_caco2()
    print("    MAE(clean)=%.4f  MAE(contaminated)=%.4f  injected=%d  leak_rate=%.3f"
          % (caco["mae_clean"], caco["mae_contaminated"], caco["injected_duplicates"],
             caco["test_train_leak_rate"]))

    result = dict(herg=herg, caco2=caco,
                  generated_by="run_tdc_real.py", source="TDC ADMET_Group (pytdc, official PyPI)")
    with open(os.path.join(OUT, "results.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print("==> wrote", os.path.join(OUT, "results.json"))
    return result


if __name__ == "__main__":
    # C5（2026-11-03 评审）：本脚本无 argparse，此前 `--help` 会被当作普通参数，
    # 直接执行全流程（run_replication_pack 实测会**写出挑战包**）——在 CI/评审复现时
    # 是看不见的写盘者。加早退：--help 只打印用法并 exit 0，不产生任何副作用。
    import sys as _sys
    if any(_a in ("-h", "--help") for _a in _sys.argv[1:]):
        print("用法：%s（无命令行参数；直接运行即按默认配置产出产物）" % __file__)
        raise SystemExit(0)
    main()
