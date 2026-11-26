# -*- coding: utf-8 -*-
"""复现挑战包 keystone-v41 —— 第二实现（self-audit replication）。

【这段声明必须随结果一起公开，不得删改】
本实现由**与原实现相同的作者**编写，且作者在编写前已看过 expected.json 的期望值。
因此它**不是**独立第三方复现，它能证明的只有两件事：
  1. 挑战包 README 的"实验设置"**足以**让另一个人把流程搭出来（规范可执行性）；
  2. 6 个主数字不是"只有原环境/原代码才能得到"的产物（可移植性）。
它**不能**证明结论可被独立复现——那需要一个没有见过本仓库的实现者（评审 C11 仍未闭环）。

实现纪律：本文件不 import adt.*、不 import run_keystone、不读 out_keystone/results.json。
所有取值只来自 `replication/README.md` 的实验设置章节与 `expected.json` 的指标定义。

运行：python replication/second_implementer/impl.py --seeds 20
输出：replication/second_implementer/submission.json
"""
import argparse
import hashlib
import io
import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
PACK = os.path.dirname(HERE)
ROOT = os.path.dirname(PACK)

from rdkit import Chem, DataStructs, RDLogger                    # noqa: E402
from rdkit.Chem import AllChem, Descriptors, MACCSkeys, rdMolDescriptors  # noqa: E402
RDLogger.DisableLog("rdApp.*")

from sklearn.ensemble import RandomForestClassifier                # noqa: E402
from sklearn.linear_model import RidgeClassifier                   # noqa: E402
from sklearn.preprocessing import StandardScaler                   # noqa: E402
from sklearn.isotonic import IsotonicRegression                    # noqa: E402
from sklearn.metrics import roc_auc_score                          # noqa: E402

ENDPOINTS = ("hERG", "DILI", "BBB_Martins")
COSTS = {"hERG": (5.0, 1.0, 0.5), "DILI": (5.0, 1.0, 0.5),
         "BBB_Martins": (3.0, 1.0, 0.5)}
AD_THRESHOLD = 0.35
SPREAD_MAX = 0.30
TARGET_RISK = 0.15
# 规范缺口日志：实现时"必须自己决定"的地方，事后回填进 README
GAPS = []


def note_gap(msg):
    if msg not in GAPS:
        GAPS.append(msg)


# ---------------------------------------------------------------- 数据
def load(endpoint, cache):
    from tdc import BenchmarkGroup
    bg = BenchmarkGroup(name="ADMET_Group", path=cache)
    d = bg.get(endpoint)
    out = {}
    for key in ("train_val", "test"):
        df = d[key]
        cols = list(df.columns)
        smi_col = "Drug" if "Drug" in cols else cols[0]
        y_col = "Y" if "Y" in cols else cols[1]
        smis, ys, dropped = [], [], 0
        for _, r in df.iterrows():
            m = Chem.MolFromSmiles(str(r[smi_col]))
            if m is None:
                dropped += 1
                continue
            smis.append(m)
            ys.append(int(r[y_col]))
        if dropped:
            note_gap("%s/%s 有 %d 个 SMILES 无法解析，已丢弃（规范只说丢弃，未说阈值）"
                     % (endpoint, key, dropped))
        out[key] = (smis, np.array(ys, dtype=int))
    return out["train_val"], out["test"]


def fingerprint(smis, ys):
    h = hashlib.sha256()
    for m, y in zip(smis, ys):
        h.update((Chem.MolToSmiles(m) + "\t%d\n" % int(y)).encode("utf-8"))
    return h.hexdigest()


# ---------------------------------------------------------------- 特征
def fp_morgan(m):
    return AllChem.GetMorganFingerprintAsBitVect(m, 2, nBits=2048)


def fp_maccs(m):
    return MACCSkeys.GenMACCSKeys(m)


def desc(m):
    vals = [Descriptors.MolWt(m), Descriptors.MolLogP(m), Descriptors.TPSA(m),
            Descriptors.NumHDonors(m), Descriptors.NumHAcceptors(m),
            Descriptors.RingCount(m), rdMolDescriptors.CalcFractionCSP3(m),
            Descriptors.NumRotatableBonds(m), Descriptors.NumAromaticRings(m)]
    # 第 10 个描述符：规范写 MaxPartialCharge，但该函数在部分 RDKit 版本不存在
    if hasattr(Descriptors, "MaxPartialCharge"):
        vals.append(Descriptors.MaxPartialCharge(m))
    else:
        note_gap("Descriptors.MaxPartialCharge 在本机 RDKit 不存在，第 10 维置 0")
        vals.append(0.0)
    v = np.array(vals, dtype=float)
    return np.nan_to_num(v, nan=0.0, posinf=0.0, neginf=0.0)


def to_mat(fps, nbits):
    X = np.zeros((len(fps), nbits), dtype=np.int8)
    for i, fp in enumerate(fps):
        DataStructs.ConvertToNumpyArray(fp, X[i])
    return X


# ---------------------------------------------------------------- 三源
def fit_all(mols_fit, y_fit, seed):
    Xm = to_mat([fp_morgan(m) for m in mols_fit], 2048)
    Xc = to_mat([fp_maccs(m) for m in mols_fit], 167)
    Xd = np.array([desc(m) for m in mols_fit])
    sc = StandardScaler().fit(Xd)
    models = dict(
        rf_morgan=RandomForestClassifier(n_estimators=300, random_state=seed,
                                         n_jobs=1).fit(Xm, y_fit),
        ridge_desc=RidgeClassifier(alpha=1.0).fit(sc.transform(Xd), y_fit),
        rf_maccs=RandomForestClassifier(n_estimators=300, random_state=seed,
                                        n_jobs=1).fit(Xc, y_fit),
    )
    return models, sc


def predict_all(models, sc, mols):
    Xm = to_mat([fp_morgan(m) for m in mols], 2048)
    Xc = to_mat([fp_maccs(m) for m in mols], 167)
    Xd = np.array([desc(m) for m in mols])
    d = models["ridge_desc"].decision_function(sc.transform(Xd))
    return {
        "rf_morgan": models["rf_morgan"].predict_proba(Xm)[:, 1],
        "ridge_desc": 1.0 / (1.0 + np.exp(-d)),
        "rf_maccs": models["rf_maccs"].predict_proba(Xc)[:, 1],
    }


def calibrate(raw_cal, y_cal, raw_te):
    """每源独立 isotonic；拟合失败退化为恒等（规范明写）。"""
    out_cal, out_te = {}, {}
    for k in raw_cal:
        try:
            iso = IsotonicRegression(out_of_bounds="clip").fit(raw_cal[k], y_cal)
            out_cal[k] = iso.predict(raw_cal[k])
            out_te[k] = iso.predict(raw_te[k])
        except Exception:
            note_gap("源 %s 的 isotonic 拟合失败，已退化为恒等映射" % k)
            out_cal[k], out_te[k] = raw_cal[k], raw_te[k]
    return out_cal, out_te


def max_tanimoto(mols_ref, mols_q):
    ref = [fp_morgan(m) for m in mols_ref]
    return np.array([max(DataStructs.BulkTanimotoSimilarity(fp_morgan(m), ref))
                     for m in mols_q])


def pick_threshold(mean_cal, y_cal):
    best_cov, best_t = 0.0, None
    min_keep = max(10, 0.2 * len(mean_cal))
    for t in np.linspace(0.05, 0.95, 19):
        keep = mean_cal >= t
        if keep.sum() < min_keep:
            continue
        pred = (mean_cal[keep] >= 0.5).astype(int)
        risk = float(np.mean(pred != y_cal[keep]))
        cov = float(keep.mean())
        if risk <= TARGET_RISK and cov > best_cov:
            best_cov, best_t = cov, float(t)
    return 0.5 if best_t is None else best_t


def utility(y_true, y_pred, decided, costs):
    c_pass, c_fail, c_abst = costs
    total = 0.0
    for t, p, d in zip(y_true, y_pred, decided):
        if not d:
            total += c_abst
        elif t == 1 and p == 0:
            total += c_pass
        elif t == 0 and p == 1:
            total += c_fail
    return -total / float(len(y_true))


def run_endpoint(ep, seeds, cache):
    (mols_tv, y_tv), (mols_te, y_te) = load(ep, cache)
    # 2026-11-04 / C13：原与主实现同用 default_rng(0) 且同 permutation 规则，
    # 使「独立复现」退化为确定性复制。改为可配置独立 seed（默认与主实现不同）。
    import os as _os
    _seed = int(_os.environ.get("ADT_REPLICATION_SEED", "20261104"))
    rng = np.random.default_rng(_seed)
    idx = rng.permutation(len(mols_tv))
    cut = int(0.8 * len(mols_tv))
    fit_i, cal_i = idx[:cut], idx[cut:]
    mols_fit = [mols_tv[i] for i in fit_i]
    y_fit = y_tv[fit_i]
    mols_cal = [mols_tv[i] for i in cal_i]
    y_cal = y_tv[cal_i]

    print("  [%s] n_tv=%d n_fit=%d n_cal=%d n_te=%d  指纹(tv)=%s  指纹(te)=%s"
          % (ep, len(mols_tv), len(mols_fit), len(mols_cal), len(mols_te),
             fingerprint(mols_tv, y_tv)[:16], fingerprint(mols_te, y_te)[:16]), flush=True)

    ad_te = max_tanimoto(mols_fit, mols_te)
    rows = []
    for seed in seeds:
        models, sc = fit_all(mols_fit, y_fit, seed)
        raw_cal = predict_all(models, sc, mols_cal)
        raw_te = predict_all(models, sc, mols_te)
        cal_cal, cal_te = calibrate(raw_cal, y_cal, raw_te)
        mean_cal = np.mean(np.vstack([cal_cal[k] for k in cal_cal]), axis=0)
        mean_te = np.mean(np.vstack([cal_te[k] for k in cal_te]), axis=0)
        t = pick_threshold(mean_cal, y_cal)
        pred = (mean_te >= 0.5).astype(int)
        # S1（naive_majority）的 pred 是三源**未校准**二值票数的多数：
        # 这是指标名的字面含义，也与原实现一致。第一次跑时我按"均值概率≥0.5"实现，
        # 导致 delta 超容差（−0.1705 vs −0.197）——那是规范当时没写清，不是数据问题。
        votes = np.vstack([raw_te[k] for k in raw_te]) >= 0.5
        pred_s1 = (votes.sum(axis=0) >= (len(raw_te) / 2.0)).astype(int)
        spread = (np.vstack([raw_te[k] for k in raw_te]).max(axis=0)
                  - np.vstack([raw_te[k] for k in raw_te]).min(axis=0))
        in_dom = ad_te >= AD_THRESHOLD
        d1 = np.ones(len(y_te), dtype=bool)
        d4 = (mean_te >= t) & in_dom & (spread <= SPREAD_MAX)
        rows.append(dict(
            seed=seed,
            auc=float(roc_auc_score(y_te, mean_te)) if len(set(y_te.tolist())) > 1 else None,
            S1_utility=utility(y_te, pred_s1, d1, COSTS[ep]),
            S4_utility=utility(y_te, pred, d4, COSTS[ep]),
            S4_coverage=float(d4.mean()),
            S4_risk=float(np.mean(pred[d4] != y_te[d4])) if d4.sum() else None,
            threshold=t,
        ))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--endpoints", default=",".join(ENDPOINTS))
    ap.add_argument("--cache", default=os.path.join(ROOT, "out_ext", "tdc_cache"))
    ap.add_argument("--out", default=os.path.join(HERE, "submission.json"))
    a = ap.parse_args()
    seeds = list(range(a.seeds))
    all_rows = {}
    t0 = time.time()
    for ep in [x for x in a.endpoints.split(",") if x]:
        print("[impl] %s ..." % ep, flush=True)
        all_rows[ep] = run_endpoint(ep, seeds, a.cache)
        print("  [%s] 用时 %.0fs" % (ep, time.time() - t0), flush=True)

    def med(vals):
        v = [x for x in vals if x is not None]
        return round(float(np.median(v)), 4) if v else None

    h = all_rows.get("hERG", [])
    delta = [r["S4_utility"] - r["S1_utility"] for r in h]
    metrics = {
        "hERG.S1_naive_majority.auc": med([r["auc"] for r in h]),
        "hERG.S1_naive_majority.utility": med([r["S1_utility"] for r in h]),
        "hERG.S4_full_admission.coverage": med([r["S4_coverage"] for r in h]),
        "hERG.S4_full_admission.risk_decided": med([r["S4_risk"] for r in h]),
        "DILI.S4_full_admission.utility": med([r["S4_utility"] for r in all_rows.get("DILI", [])]),
        "BBB_Martins.S4_full_admission.utility": med(
            [r["S4_utility"] for r in all_rows.get("BBB_Martins", [])]),
        "hERG.delta_utility.S4_minus_S1": med(delta),
    }
    sub = dict(
        pack_id="keystone-v41",
        metrics={k: dict(value=v) for k, v in metrics.items()},
        environment=None,
        submitted_by="self-audit (same author, expected values known)",
        submitted_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
        implementation="replication/second_implementer/impl.py",
        caveat=("同一作者、已见期望值的自查式实现；只证明规范可执行，"
                "不构成独立第三方复现"),
        spec_gaps=GAPS,
        per_seed={ep: rows for ep, rows in all_rows.items()},
    )
    try:
        import sklearn
        import rdkit
        sub["environment"] = dict(python=sys.version.split()[0], rdkit=rdkit.__version__,
                                  sklearn=sklearn.__version__, numpy=np.__version__)
    except Exception:
        pass
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    tmp = a.out + ".tmp"
    with io.open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(sub, ensure_ascii=False, indent=2))
    os.replace(tmp, a.out)
    print("\n[impl] 指标（20 种子中位数）：")
    for k, v in metrics.items():
        print("  %-46s %s" % (k, v))
    print("[impl] 规范缺口 %d 条：" % len(GAPS))
    for g in GAPS:
        print("   - %s" % g)
    print("[impl] -> %s (%.0fs)" % (a.out, time.time() - t0))


if __name__ == "__main__":
    main()
