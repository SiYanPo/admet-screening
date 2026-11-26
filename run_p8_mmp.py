# -*- coding: utf-8 -*-
"""R14：P8 的 MMP 校准检验（真实数据）。

替代旧版"随机无关分子对"零对照（评审 F4 判定其为弱对照）。
数据：TDC hERG（train_val 523 / test 132），RF+Morgan 基线。
输出：out_ext/tdc/p8_mmp_results_<endpoint>.json
"""
import io
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rdkit import Chem, DataStructs, RDLogger                     # noqa: E402
from rdkit.Chem import AllChem                                    # noqa: E402
from sklearn.ensemble import RandomForestClassifier               # noqa: E402

from adt import mmp                                               # noqa: E402

RDLogger.DisableLog("rdApp.*")


def fp(m):
    return AllChem.GetMorganFingerprintAsBitVect(m, 2, nBits=2048)


def to_np(mols):
    X = np.zeros((len(mols), 2048), dtype=np.int8)
    for i, m in enumerate(mols):
        DataStructs.ConvertToNumpyArray(fp(m), X[i])
    return X


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint", default="hERG")
    ap.add_argument("--cache", default="out_ext/tdc_cache")
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
            ys.append(int(float(r["Y"])))
        return mols, np.array(ys)

    mols_tr, y_tr = _xy(d["train_val"])
    mols_te, y_te = _xy(d["test"])
    clf = RandomForestClassifier(n_estimators=400, random_state=0, n_jobs=1)
    clf.fit(to_np(mols_tr), y_tr)

    # 只用 held-out test 集做 MMP 对（避免 in-sample 污染）
    smis_te = [Chem.MolToSmiles(m) for m in mols_te]
    probs_te = clf.predict_proba(to_np(mols_te))[:, 1]

    pairs, stats_te = mmp.fragment_pairs(smis_te, max_cuts=1, min_core=6, min_frag=1)
    print("[p8-mmp] test 集 MMP 对：%d（cores=%d）stats=%s"
          % (len(pairs), len({p[0] for p in pairs}), stats_te), flush=True)

    scope = "test_only"
    if len(pairs) < 30:
        # 扩到全量（含训练集成员）——必须在报告里声明 in-sample 混入
        smis_all = [Chem.MolToSmiles(m) for m in mols_tr + mols_te]
        probs_all = clf.predict_proba(to_np(mols_tr + mols_te))[:, 1]
        labels_all = np.concatenate([y_tr, y_te])
        pairs, stats_all = mmp.fragment_pairs(smis_all, max_cuts=1, min_core=6, min_frag=1)
        labels, probs = labels_all, probs_all
        scope = "train_plus_test(in_sample_mixed)"
        print("[p8-mmp] 扩到全量：%d 对（scope=%s）stats=%s"
              % (len(pairs), scope, stats_all), flush=True)
    else:
        labels, probs = y_te, probs_te

    res = mmp.analyze(pairs, labels, probs, equiv_margin=0.10)
    neg = mmp.controls(pairs, labels, probs, shrink=0.15, equiv_margin=0.10)
    payload = {
        "endpoint": ep,
        "model": "RandomForest(400,seed=0)+Morgan2048",
        "mmp_scope": scope,
        "n_test_mols": len(mols_te),
        "mmp_stats": (stats_te if scope == "test_only" else stats_all),
        "analysis": res,
        "controls": {
            "original": neg["original"]["overall"],
            "oracle_like": neg["oracle_like"]["overall"],
            "cliff_blind": neg["cliff_blind"]["overall"],
            "test_has_power": neg["test_has_power"],
            "note": ("正对照（标签构造的伪概率）应通过、负对照（向 0.5 收缩）应被判迟钝；"
                     "两者同时成立才说明判据有辨别力"),
        },
        "old_design_note": "旧版以随机无关分子对为零对照，任何模型都会显示大位移（评审 F4）",
    }
    os.makedirs("out_ext/tdc", exist_ok=True)
    outp = "out_ext/tdc/p8_mmp_results_%s.json" % ep
    with io.open(outp, "w", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False, indent=2))
    if ep == "hERG":                       # 保持旧路径可引用
        with io.open("out_ext/tdc/p8_mmp_results.json", "w", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False, indent=2))
    print(json.dumps(res["overall"], ensure_ascii=False, indent=2))
    print("status:", res["status"])
    print("controls test_has_power:", payload["controls"]["test_has_power"])


if __name__ == "__main__":
    main()
