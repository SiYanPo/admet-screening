# -*- coding: utf-8 -*-
"""Ames 双方法验证：结构警示层（专家规则）× 统计模型（ICH M7 口径）。

为什么必须跑这个脚本：
  新增 `adt/alerts.py` 之后，如果只写"我们补了专家规则层"，那是把接口当结论。
  本脚本在 TDC AMES（真实标签）上测三件事：
    1. 警示层单独的表现（敏感性/特异度/PPV/NPV），含/不含弱规则各一套；
    2. 统计模型单独的表现（同一切分）；
    3. ICH M7 双方法合成的表现——**只有"统计阴性 + 无警示 + 域内"才放行**。

关键指标不是总体准确率，而是**放行后的错误率**（PPV 的补）：
  ICH M7 允许"两法均阴性 → 判 Class 5"，其风险就是放行里的假阴性。
  若放行错误率高，说明本框架不应给出 Class 5 结论，档位必须退回 not_recommended。

输出：out_ext/tdc/ames_alerts.json
"""
import argparse
import io
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rdkit import Chem, DataStructs, RDLogger                     # noqa: E402
from rdkit.Chem import AllChem                                     # noqa: E402
from sklearn.ensemble import RandomForestClassifier                # noqa: E402

from adt import alerts                                             # noqa: E402

RDLogger.DisableLog("rdApp.*")


def fp(m):
    return AllChem.GetMorganFingerprintAsBitVect(m, 2, nBits=2048)


def to_np(mols):
    X = np.zeros((len(mols), 2048), dtype=np.int8)
    for i, m in enumerate(mols):
        DataStructs.ConvertToNumpyArray(fp(m), X[i])
    return X


def knn_max(mols_ref, mols_q):
    ref = [fp(m) for m in mols_ref]
    out = []
    for m in mols_q:
        s = DataStructs.BulkTanimotoSimilarity(fp(m), ref)
        out.append(max(s) if s else 0.0)
    return np.array(out)


def binary_metrics(y, pred):
    """y, pred ∈ {0,1}；1 = 致突变（阳性）。"""
    y = np.asarray(y, dtype=int)
    p = np.asarray(pred, dtype=int)
    tp = int(np.sum((y == 1) & (p == 1)))
    fn = int(np.sum((y == 1) & (p == 0)))
    tn = int(np.sum((y == 0) & (p == 0)))
    fp_ = int(np.sum((y == 0) & (p == 1)))
    sens = tp / (tp + fn) if (tp + fn) else None
    spec = tn / (tn + fp_) if (tn + fp_) else None
    ppv = tp / (tp + fp_) if (tp + fp_) else None
    npv = tn / (tn + fn) if (tn + fn) else None
    acc = (tp + tn) / len(y) if len(y) else None
    return {"n": len(y), "tp": tp, "fn": fn, "tn": tn, "fp": fp_,
            "sensitivity": round(sens, 3) if sens is not None else None,
            "specificity": round(spec, 3) if spec is not None else None,
            "ppv": round(ppv, 3) if ppv is not None else None,
            "npv": round(npv, 3) if npv is not None else None,
            "accuracy": round(acc, 3) if acc is not None else None}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default="out_ext/tdc_cache")
    ap.add_argument("--ad-threshold", type=float, default=0.35, dest="ad_threshold")
    ap.add_argument("--model-threshold", type=float, default=0.5, dest="model_threshold")
    a = ap.parse_args(argv)

    from adt.tdc_local import load_split
    d = load_split(a.cache, "ames")

    def _xy(df):
        mols, ys = [], []
        for _, r in df.iterrows():
            m = Chem.MolFromSmiles(str(r["Drug"]))
            if m is None:
                continue
            mols.append(m)
            ys.append(int(float(r["Y"])))
        return mols, np.array(ys, dtype=int)

    mols_tr, y_tr = _xy(d["train_val"])
    mols_te, y_te = _xy(d["test"])
    print("[ames] train=%d test=%d  阳性率=%.3f"
          % (len(mols_tr), len(mols_te), y_te.mean()), flush=True)

    # ---- 1. 结构警示层（含/不含弱规则）
    hits_all = []
    for m in mols_te:
        ids = {h[0] for h in alerts.alerts_of(m)}
        hits_all.append(ids)
    pred_alert_full = np.array([1 if s else 0 for s in hits_all])
    pred_alert_core = np.array([1 if (s - {"n_aryl_amide"}) else 0 for s in hits_all])

    alert_stats = {
        "with_weak_rule": binary_metrics(y_te, pred_alert_full),
        "core_only": binary_metrics(y_te, pred_alert_core),
        "alert_positive_rate": round(float(pred_alert_full.mean()), 3),
    }
    # 逐条规则的命中数与阳性率（审计用）
    per_rule = {}
    for aid, _patt, mech, _note in alerts._compiled():
        mask = np.array([aid in s for s in hits_all])
        if mask.sum() == 0:
            per_rule[aid] = {"n_hits": 0, "mutagen_rate": None}
            continue
        per_rule[aid] = {"n_hits": int(mask.sum()),
                         "mutagen_rate": round(float(y_te[mask].mean()), 3)}
    alert_stats["per_rule"] = per_rule

    # ---- 2. 统计模型
    clf = RandomForestClassifier(n_estimators=400, random_state=0, n_jobs=1)
    clf.fit(to_np(mols_tr), y_tr)
    prob_te = clf.predict_proba(to_np(mols_te))[:, 1]
    pred_stat = (prob_te >= a.model_threshold).astype(int)
    stat_metrics = binary_metrics(y_te, pred_stat)

    # 适用域
    sim = knn_max(mols_tr, mols_te)
    in_ad = sim >= a.ad_threshold

    # ---- 3. ICH M7 双方法合成
    verdicts, reasons = [], []
    for i in range(len(y_te)):
        stat_v = "FAIL" if pred_stat[i] == 1 else "PASS"
        hit = bool(hits_all[i])
        v, why = alerts.two_method_verdict(stat_v, hit, bool(in_ad[i]))
        verdicts.append(v)
        reasons.append(why)
    verdicts = np.array(verdicts)
    n_pass = int(np.sum(verdicts == "PASS"))
    n_fail = int(np.sum(verdicts == "FAIL"))
    n_undet = int(np.sum(verdicts == "UNDETERMINED"))

    # 放行（PASS）里的假阴性 = 真阳性被放行
    pass_mask = verdicts == "PASS"
    released_mutagen = int(np.sum((y_te == 1) & pass_mask))
    release_error = (round(released_mutagen / n_pass, 4) if n_pass else None)

    # FAIL 里的真阳性（用于看"升级"策略的检出力）
    fail_mask = verdicts == "FAIL"
    fail_true = int(np.sum((y_te == 1) & fail_mask))

    combo = {
        "n_pass_class5_direction": n_pass,
        "n_fail": n_fail,
        "n_undetermined": n_undet,
        "pass_rate": round(n_pass / len(y_te), 3),
        "fail_rate": round(n_fail / len(y_te), 3),
        "undet_rate": round(n_undet / len(y_te), 3),
        "released_mutagens": released_mutagen,
        "release_error_rate": release_error,
        "fail_precision": (round(fail_true / n_fail, 3) if n_fail else None),
        "note": ("ICH M7 口径：只有 PASS 才等于 Class 5 方向。"
                 "release_error_rate = 被放行的真致突变物 / 放行总数，"
                 "这是该策略唯一值得看的风险数字。"),
    }

    # ---- 4. 反事实：若不做双方法（只看统计模型），放行错误是多少
    stat_pass = pred_stat == 0
    stat_combo = {
        "n_pass": int(stat_pass.sum()),
        "pass_rate": round(float(stat_pass.mean()), 3),
        "released_mutagens": int(np.sum((y_te == 1) & stat_pass)),
        "release_error_rate": (round(float(np.sum((y_te == 1) & stat_pass) / stat_pass.sum()), 4)
                               if stat_pass.sum() else None),
        "note": "只看统计模型（无专家规则层）时的同口径风险，用于对比双方法是否真的降低了放行错误",
    }

    payload = {"endpoint": "ames", "n_test": len(mols_te),
               "prevalence": round(float(y_te.mean()), 3),
               "ad_threshold": a.ad_threshold,
               "model_threshold": a.model_threshold,
               "alert_layer": alert_stats,
               "stat_model": stat_metrics,
               "two_method_ich_m7": combo,
               "stat_only_counterfactual": stat_combo,
               "rule_table": alerts.rule_table(),
               "caveat": ("警示集是官能团级最小集，不是 Benigni–Bossa/Kazius 全表，"
                          "也不等价于 Derek/Sarah；假阴性是默认风险，"
                          "正确用法是'命中即升级'，不是'未命中即放行'")}
    os.makedirs("out_ext/tdc", exist_ok=True)
    p = "out_ext/tdc/ames_alerts.json"
    with io.open(p, "w", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False, indent=2))

    print("[ames] 警示层(含弱规则) sens=%s spec=%s PPV=%s"
          % (alert_stats["with_weak_rule"]["sensitivity"],
             alert_stats["with_weak_rule"]["specificity"],
             alert_stats["with_weak_rule"]["ppv"]), flush=True)
    print("[ames] 警示层(仅核心)   sens=%s spec=%s PPV=%s"
          % (alert_stats["core_only"]["sensitivity"],
             alert_stats["core_only"]["specificity"],
             alert_stats["core_only"]["ppv"]), flush=True)
    print("[ames] 统计模型         sens=%s spec=%s PPV=%s"
          % (stat_metrics["sensitivity"], stat_metrics["specificity"],
             stat_metrics["ppv"]), flush=True)
    print("[ames] 双方法(IchM7)   PASS=%d(%.3f) FAIL=%d UNDET=%d 放行错误率=%s"
          % (n_pass, n_pass / len(y_te), n_fail, n_undet, release_error), flush=True)
    print("[ames] 只统计模型       PASS=%d 放行错误率=%s"
          % (stat_combo["n_pass"], stat_combo["release_error_rate"]), flush=True)
    print("[ames] -> %s" % p)


if __name__ == "__main__":
    main()
