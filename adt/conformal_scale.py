# -*- coding: utf-8 -*-
"""工作包 F 的难度尺度：描述符空间 k-NN 距离 -> sigma。

为什么需要它
------------
标准 split-conformal 用绝对残差分位数 q，所有化合物区间同宽（2q）。
这样"UNDETERMINED 是否区间更宽"根本无法检验——宽度不随化合物变化。
归一化 conformal 用

    score = |y − ŷ| / sigma(x),   区间 = ŷ ± q · sigma(x)

其中 sigma(x) 是逐化合物难度。本模块用**训练集描述符空间的第 k 近邻距离**
定义 sigma = 1 + d_k(x)：离训练集越远，区间越宽。它**不使用源间分歧**，
因此与框架的弃权逻辑相对独立，适合做 F 的外部验证。
"""

import csv
import io
import os


def compute(train_compounds, target_compounds, k=5):
    from .external import _compound_smiles, _descriptor_matrix
    import numpy as np
    from sklearn.neighbors import NearestNeighbors
    from sklearn.preprocessing import StandardScaler

    tr = _compound_smiles(train_compounds)
    te = _compound_smiles(target_compounds)
    cids_tr = [c for c in sorted(tr) if tr[c]]
    cids_te = [c for c in sorted(te) if te[c]]
    if not cids_tr or not cids_te:
        return []
    Xtr = _descriptor_matrix([tr[c] for c in cids_tr])
    Xte = _descriptor_matrix([te[c] for c in cids_te])
    scaler = StandardScaler().fit(Xtr)
    Xtr = scaler.transform(Xtr)
    Xte = scaler.transform(Xte)
    kk = max(1, min(int(k), len(Xtr)))
    nn = NearestNeighbors(n_neighbors=kk).fit(Xtr)
    dist, _ = nn.kneighbors(Xte)
    rows = []
    for cid, d in zip(cids_te, dist[:, -1]):
        d = float(d)
        rows.append(
            dict(
                compound_id=cid, sigma=round(1.0 + d, 6), knn_distance=round(d, 6), k=kk
            )
        )
    return rows


def write(path, rows):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with io.open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(
            fh,
            fieldnames=["compound_id", "sigma", "knn_distance", "k"],
            extrasaction="ignore",
        )
        w.writeheader()
        w.writerows(rows)
    return len(rows)
