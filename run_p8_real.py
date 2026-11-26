# -*- coding: utf-8 -*-
"""P8 真实数据落地：结构扰动位移 + 随机化零对照（≥100 合法扰动，TDC hERG 真实分子）。

设计（与 adt/pred_displacement.py 语义一致）：
  - 扰动源：adt.perturbation.variants 生成合法结构变体（去盐 / 中和 / 互变 / 立体翻转），
    全部是"应代表同一化学个体"的变换——它们引起的预测位移就是结构噪声。
  - 真实位移 real_deltas：TDC hERG 官方 test 集（132 分子，对 RF 模型为 held-out）上，
    每个非 no-op 变体的 |proba(variant) − proba(original)|。
  - 零对照 null_deltas：no-op 对照（SMILES 往返规范化，结构不变）。
    诚实边界：对确定性 RF 模型 no-op 位移恒为 0，零对照退化——显著性判定是平凡的；
    因此本脚本同时报告两类**非退化**补充量：
      (a) 变体位移 vs 随机无关分子对位移（instability 比值，语义同 source-shift 对照）；
      (b) 阈值翻转：变体使 hERG 0.5 判级翻转的次数（评审最关心的致命量）。
  - 全部数值来自真实 TDC 分子 + 真实 RF 预测，不臆造。
产出：out_ext/tdc/p8_results.json
"""
import os
import sys
import json
import random
import warnings

warnings.filterwarnings("ignore")

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import numpy as np
from rdkit import Chem
from rdkit.Chem import AllChem, DataStructs
from sklearn.ensemble import RandomForestClassifier

from adt.tdc_local import load_split
from adt.perturbation import variants
from adt.pred_displacement import randomization_null_control

TDC_CACHE = os.path.join(ROOT, "out_ext", "tdc_cache")
OUT = os.path.join(ROOT, "out_ext", "tdc")
SEED = 0


def morgan_arr(smi):
    m = Chem.MolFromSmiles(smi)
    if m is None:
        return None
    fp = AllChem.GetMorganFingerprintAsBitVect(m, 2, nBits=2048)
    arr = np.zeros((2048,), dtype=np.int8)
    DataStructs.ConvertToNumpyArray(fp, arr)
    return arr


def main():
    random.seed(SEED)
    d = load_split(TDC_CACHE, "hERG")
    tv, te = d["train_val"], d["test"]

    # 训练 RF（同 run_tdc_real.py 种子，保证可复现）
    def build(df):
        smis, ys = [], []
        for _, row in df.iterrows():
            if morgan_arr(str(row["Drug"])) is not None:
                smis.append(str(row["Drug"]))
                ys.append(int(float(row["Y"])))
        X = np.array([morgan_arr(s) for s in smis], dtype=np.int8)
        return smis, X, np.array(ys)

    smis_tr, Xtr, ytr = build(tv)
    smis_te, Xte, yte = build(te)
    clf = RandomForestClassifier(n_estimators=400, random_state=SEED, n_jobs=-1)
    clf.fit(Xtr, ytr)
    print("RF trained: n_train=%d n_test=%d" % (len(ytr), len(yte)))

    base_proba = clf.predict_proba(Xte)[:, 1]

    real_deltas = []          # 非no-op 变体位移
    flips = 0                 # 0.5 判级翻转次数
    n_variants = 0
    noop_deltas = []          # no-op 对照位移（应为全 0）
    per_mol = []
    for i, smi in enumerate(smis_te):
        v = variants(smi)
        if "_error" in v:
            continue
        orig = v["original"][0]
        orig_fp = morgan_arr(orig)
        if orig_fp is None:
            continue
        base = float(base_proba[i])
        for name, (s2, note) in v.items():
            if name == "original" or not s2:
                continue
            fp2 = morgan_arr(s2)
            if fp2 is None:
                continue
            delta = abs(float(clf.predict_proba(fp2.reshape(1, -1))[0, 1]) - base)
            is_noop = (s2 == orig)
            if is_noop:
                noop_deltas.append(delta)
                continue
            n_variants += 1
            real_deltas.append(delta)
            base_cls = base >= 0.5
            var_cls = float(clf.predict_proba(fp2.reshape(1, -1))[0, 1]) >= 0.5
            if base_cls != var_cls:
                flips += 1
            per_mol.append(dict(mol=i, variant=name, delta=round(delta, 4),
                                flip=bool(base_cls != var_cls)))

    # 随机无关分子对位移（instability 参照，非 P8 主判定）
    n_pairs = 2000
    pair_deltas = []
    for _ in range(n_pairs):
        a, b = random.randrange(len(smis_te)), random.randrange(len(smis_te))
        if a == b:
            continue
        pair_deltas.append(abs(float(base_proba[a]) - float(base_proba[b])))

    # P8 主判定：真实变体位移 vs no-op 零对照
    p8 = randomization_null_control(real_deltas, noop_deltas, thr=0.05)
    p8_thr10 = randomization_null_control(real_deltas, noop_deltas, thr=0.10)

    # 补充：变体位移 vs 无关对位移的量级比（<1 = 变体影响小于随机差异 → 模型对变体稳定）
    real_med = float(np.median(real_deltas)) if real_deltas else None
    pair_med = float(np.median(pair_deltas)) if pair_deltas else None

    result = dict(
        endpoint="hERG", model="RandomForest(400,seed=0)+Morgan2048",
        n_test_mols=len(smis_te), n_real_variants=n_variants,
        n_noop=len(noop_deltas),
        p8_thr005=p8, p8_thr010=p8_thr10,
        real_delta=dict(mean=float(np.mean(real_deltas)), median=real_med,
                        p90=float(np.percentile(real_deltas, 90)),
                        max=float(np.max(real_deltas))),
        random_pair_delta=dict(median=pair_med,
                               mean=float(np.mean(pair_deltas))),
        instability_ratio=(round(float(np.mean(real_deltas)) / float(np.mean(pair_deltas)), 4)
                           if real_deltas and pair_deltas else None),
        threshold_flips_at_050=flips,
        flip_rate=round(flips / float(n_variants), 4) if n_variants else None,
        noop_delta_max=float(np.max(noop_deltas)) if noop_deltas else None,
        honest_note=("no-op 零对照对确定性模型恒为 0 → 显著性平凡；"
                     "有效信息=位移量级 + 阈值翻转率 + instability 比值"),
        per_mol=per_mol,
    )
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "p8_results.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    per_mol.clear()  # 摘要打印不带明细
    slim = {k: v for k, v in result.items() if k != "per_mol"}
    print(json.dumps(slim, ensure_ascii=False, indent=2)[:1500])


if __name__ == "__main__":
    # C5（2026-11-03 评审）：本脚本无 argparse，此前 `--help` 会被当作普通参数，
    # 直接执行全流程（run_replication_pack 实测会**写出挑战包**）——在 CI/评审复现时
    # 是看不见的写盘者。加早退：--help 只打印用法并 exit 0，不产生任何副作用。
    import sys as _sys
    if any(_a in ("-h", "--help") for _a in _sys.argv[1:]):
        print("用法：%s（无命令行参数；直接运行即按默认配置产出产物）" % __file__)
        raise SystemExit(0)
    main()
