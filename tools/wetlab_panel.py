# -*- coding: utf-8 -*-
"""生成 hERG 湿实验验证面板（30 化合物）——把 estimand NOT_BOUND 变成"可下单"。

为什么需要
----------
`references/ENDPOINT_ESTIMAND_CARDS.yaml` 里 hERG 是 `NOT_AN_ESTIMAND / inference_revoked`：
没有膜片钳金标准，任何"决策价值"主张都只能停在"算法一致性"。
`tools/publication_readiness.py` 把"湿实验"列为 IF≥10 的硬门槛（B3）。

本脚本做的事：从**已有真实数据**（`out_ext/external/herg_holdout_rows.csv`，959 条 ChEMBL
hERG 记录，含 SMILES 与模型预测 p_ext）里，按**预先声明**的三层设计抽 30 个化合物，
并强制化学多样性（两两 Tanimoto < 0.7），产出可直接询价的清单。

设计（预先声明，防止"挑好看的"）
--------------------------------
**分层必须按实测分布定，不能按直觉定**：本数据里 `p_ext` 的最小值 0.348、中位数 0.689，
按"p≤0.20 = 预测非阻断"根本抽不到样本（0 条）——这本身是**校准偏斜的证据**（模型在该外部队列上
从不给出低概率）。因此改用**经验分位**分层，并把这一事实写进协议：

- A 层 10 个：p_ext ≥ p90（模型判为强阻断）
- B 层 10 个：p_ext ≤ p10（**该队列里最"阴性"的十分位**，绝对值仍偏高 → 见协议 §2 的校准说明）
- C 层 10 个：p25 ≤ p_ext ≤ p75（决策相关带：准入层在这里最可能改变结论）
- 多样性：贪心最大化与已选集合的最小 Tanimoto；阈值按 0.70 → 0.80 → 0.90 **分级放宽**（并报告实际达到值）
- **盲法**：交付实验方的清单不含 `y`；真值单独存 KEY 文件。

输出
----
`references/WETLAB_PANEL_herg_30.csv`      交付版（无真值，可发实验方）
`references/WETLAB_PANEL_herg_30_KEY.csv`  内部版（含 y / pic50 / p_ext，用于解盲后评估）

运行：python tools/wetlab_panel.py [--n 30]
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "out_ext", "external", "herg_holdout_rows.csv")
OUT = os.path.join(ROOT, "references", "WETLAB_PANEL_herg_30.csv")
KEY = os.path.join(ROOT, "references", "WETLAB_PANEL_herg_30_KEY.csv")
TAN_CAPS = (0.70, 0.80, 0.90)  # 分级放宽（先严后宽，并报告实际达到值）

STRATA = [
    ("A_pred_blocker", lambda p: p >= 0.80, 10),
    ("B_pred_nonblocker", lambda p: p <= 0.20, 10),
    ("C_decision_band", lambda p: 0.35 <= p <= 0.65, 10),
]


def empirical_strata(ps):
    """按经验分位定层（本数据 p_ext 全在 0.348 以上，硬阈值抽不到阴性层）。"""
    import numpy as np

    p10, p25, p75, p90 = (float(np.percentile(ps, q)) for q in (10, 25, 75, 90))
    return [
        ("A_pred_blocker", lambda p: p >= p90, 10),
        ("B_lowest_decile", lambda p: p <= p10, 10),
        ("C_decision_band", lambda p: p25 <= p <= p75, 10),
    ], dict(p10=p10, p25=p25, p75=p75, p90=p90)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=30)
    a = ap.parse_args(argv)

    from rdkit import Chem, DataStructs, RDLogger
    from rdkit.Chem import AllChem

    RDLogger.DisableLog("rdApp.*")

    rows = []
    with io.open(SRC, encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            smi = (r.get("smiles") or "").strip()
            if not smi:
                continue
            try:
                p = float(r.get("p_ext"))
            except Exception:  # noqa: BLE001
                continue
            m = Chem.MolFromSmiles(smi)
            if m is None:
                continue
            rows.append(
                dict(
                    chembl_id=r.get("chembl_id"),
                    smiles=smi,
                    y=r.get("y"),
                    pic50=r.get("pic50"),
                    p_ext=p,
                    max_tdc=float(r.get("max_tdc_tanimoto") or 0),
                    fp=AllChem.GetMorganFingerprintAsBitVect(m, 2, nBits=2048),
                )
            )
    print("[load] %d 条可用记录" % len(rows))

    strata, cuts = empirical_strata([r["p_ext"] for r in rows])
    print(
        "[cuts] p10=%.3f p25=%.3f p75=%.3f p90=%.3f（按经验分位分层）"
        % (cuts["p10"], cuts["p25"], cuts["p75"], cuts["p90"])
    )

    picked, fps = [], []
    for name, rule, quota in strata:
        cand = sorted(
            [r for r in rows if rule(r["p_ext"])],
            key=lambda r: (r["max_tdc"], -abs(r["p_ext"] - 0.5)),
        )
        got = 0
        cap_used = None
        for cap in TAN_CAPS:
            for r in cand:
                if got >= quota:
                    break
                if any(id(x) == id(r) for x in picked):
                    continue
                if any(DataStructs.TanimotoSimilarity(r["fp"], f) >= cap for f in fps):
                    continue
                r2 = dict(r)
                r2["stratum"] = name
                picked.append(r2)
                fps.append(r["fp"])
                got += 1
                cap_used = cap
            if got >= quota:
                break
        print(
            "  %-18s 候选 %3d -> 选中 %2d（Tanimoto 上限 %s）"
            % (name, len(cand), got, cap_used)
        )

    if len(picked) < a.n:
        print("[warn] 只选到 %d/%d（多样性约束太紧）" % (len(picked), a.n))

    # 交付版：不含真值列
    cols = ["panel_id", "chembl_id", "smiles", "stratum"]
    with io.open(OUT, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for i, r in enumerate(picked, 1):
            w.writerow(
                dict(
                    panel_id="H%02d" % i,
                    chembl_id=r["chembl_id"],
                    smiles=r["smiles"],
                    stratum=r["stratum"],
                )
            )
    # 内部版：含真值
    cols2 = cols + ["p_ext", "y", "pic50", "max_tdc_tanimoto"]
    with io.open(KEY, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols2)
        w.writeheader()
        for i, r in enumerate(picked, 1):
            w.writerow(
                dict(
                    panel_id="H%02d" % i,
                    chembl_id=r["chembl_id"],
                    smiles=r["smiles"],
                    stratum=r["stratum"],
                    p_ext=round(r["p_ext"], 4),
                    y=r["y"],
                    pic50=r["pic50"],
                    max_tdc_tanimoto=round(r["max_tdc"], 4),
                )
            )

    n_y1 = sum(1 for r in picked if str(r["y"]) == "1")
    print(
        "\n[panel] %d 个化合物（真值阳性 %d / 阴性 %d）"
        % (len(picked), n_y1, len(picked) - n_y1)
    )
    print("[panel] 交付版 -> %s" % os.path.relpath(OUT, ROOT))
    print("[panel] 内部版 -> %s（勿发实验方，解盲用）" % os.path.relpath(KEY, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
