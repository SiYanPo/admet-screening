# -*- coding: utf-8 -*-
"""R29 / R30 执行脚本：从基石实验产物生成**复现挑战包**。

只读取 `out_keystone/results.json` 的 per-seed 行（`per_run`），
按 `adt/replication.py` 的规则推出 6 个主数字 + 容差（tol = 2 × sd_seed），
然后用 `adt/snapshot.py` 的记录把数据快照指纹写进包。

运行：python run_replication_pack.py
输出：replication/  （README.md / expected.json / score.py / SUBMISSION_TEMPLATE.json）
"""
from __future__ import annotations

import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from adt import replication as R          # noqa: E402

RES = os.path.join(HERE, "out_keystone", "results.json")
OUT = os.path.join(HERE, "replication")

# (endpoint, strategy, field, kind, 说明)
SPECS = [
    ("hERG", "S1_naive_majority", "auc", "auc",
     "无准入基线的判别力（校准前原始分数）"),
    # 加这一项是因为：只有 delta 时，一旦超容差就无法判断是 S1 还是 S4 出了问题。
    # 加上 S1 的绝对水平，delta 的误差可以被直接分解（2026-10-31 第二实现时踩过）。
    ("hERG", "S1_naive_majority", "utility", "utility",
     "无准入基线的代价加权效用（delta 指标的分母侧，用于定位误差来源）"),
    ("hERG", "S4_full_admission", "coverage", "coverage",
     "完整准入层的判定覆盖率——**准入层的代价就体现在这里**"),
    ("hERG", "S4_full_admission", "risk_decided", "risk_decided",
     "已判定样本内的错误率（与 coverage 必须成对读，单看会误判）"),
    ("DILI", "S4_full_admission", "utility", "utility",
     "代价加权效用（c=(5,1,0.5)）"),
    ("BBB_Martins", "S4_full_admission", "utility", "utility",
     "端特异代价（c=(3,1,0.5)）"),
]


def _load(path):
    with io.open(path, encoding="utf-8") as fh:
        return json.load(fh)


def main():
    if not os.path.exists(RES):
        print("缺少 %s：先跑 run_keystone.py" % RES)
        return 2
    d = _load(RES)
    rows = d["per_run"]
    seeds = sorted({r["seed"] for r in rows})

    def series(endpoint, strategy, field):
        out = {}
        for r in rows:
            if r["endpoint"] != endpoint or r["strategy"] != strategy:
                continue
            if r.get("cost_point") not in (None, "ref"):
                continue
            out[r["seed"]] = r[field]
        return [out[s] for s in sorted(out)]

    metrics = []
    for ep, st, field, kind, note in SPECS:
        vals = series(ep, st, field)
        if not vals:
            print("跳过（无数据）：%s/%s/%s" % (ep, st, field))
            continue
        t = R.tolerance_from_seeds(vals)
        metrics.append(dict(name="%s.%s.%s" % (ep, st, field),
                            value=t["median"], tol=t["tol"], kind=kind,
                            seed_sd=t["sd"], n_seeds=t["n_seeds"],
                            note=("%s；期望值取 %d 个种子的中位数，容差=2×种子sd"
                                  % (note, t["n_seeds"])) if not t["degenerate"]
                            else ("%s；%s" % (note, t["note"]))))

    # 第 6 项：Δutility(S4 − S1)，逐种子配对
    diffs = []
    for ep in ("hERG", "DILI", "BBB_Martins"):
        a = series(ep, "S4_full_admission", "utility")
        b = series(ep, "S1_naive_majority", "utility")
        if len(a) == len(b) and a:
            diffs.append((ep, [x - y for x, y in zip(a, b)]))
    # 取 hERG 的配对数作为主指标（另两端点并入附注，避免"挑端点"质疑）
    if diffs:
        ep0, dv = diffs[0]
        t = R.tolerance_from_seeds(dv)
        others = ", ".join("%s %+0.4f" % (e, R.seed_stats(v)["median"])
                           for e, v in diffs[1:])
        metrics.append(dict(
            name="%s.delta_utility.S4_minus_S1" % ep0,
            value=t["median"], tol=t["tol"], kind="delta_utility",
            seed_sd=t["sd"], n_seeds=t["n_seeds"],
            note="逐种子配对差；其余端点中位数（仅供对照，不单独做容差）：" + (others or "—")))

    snapshots = []
    for src in sorted(os.listdir(os.path.join(HERE, "snapshots"))):
        idx = os.path.join(HERE, "snapshots", src, "index.jsonl")
        if not os.path.exists(idx):
            continue
        last = None
        with io.open(idx, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    last = json.loads(line)
        if last:
            snapshots.append(dict(source=src, snapshot_id=last.get("snapshot_id"),
                                  sha256=last.get("sha256"), bytes=last.get("bytes")))

    # ------------------------------------------------------------------
    # 实验设置：必须**自足**（不得指向任何 .py），否则包不可独立复现。
    # 2026-10-31 自查发现旧版写的是「切分脚本与种子列表见 run_keystone.py」——
    # 而包内并不提供该文件，等于要求第二实现者去读原实现（照抄而非复现）。
    # ------------------------------------------------------------------
    spec = dict(
        data=dict(
            source="TDC ADMET_Group 的 hERG / DILI / BBB_Martins 三个端点",
            columns="SMILES 在列 `Drug`，标签在列 `Y`；列名不同时按下标取第 1/2 列",
            split=("对每个端点的 train_val 取 numpy.random.default_rng(0).permutation(n)，"
                   "前 80% 为 fit 集、后 20% 为 calibration 集（取整：cut=int(0.8*n)）；"
                   "test 集全量用于评估，**不参与任何拟合、校准或阈值选择**"),
            label_semantics="y=1 表示 FAIL（阳性）",
            invalid_molecules="RDKit 无法解析的 SMILES 直接丢弃，不插补、不替换",
        ),
        sources=[
            dict(name="rf_morgan",
                 features="Morgan 指纹 radius=2, nBits=2048（ECFP4 等价）",
                 model="RandomForestClassifier(n_estimators=300, random_state=seed, n_jobs=1)",
                 score="predict_proba(X)[:, 1]"),
            dict(name="ridge_desc",
                 features=("10 个 RDKit 描述符，顺序固定：MolWt, MolLogP, TPSA, NumHDonors, "
                           "NumHAcceptors, RingCount, CalcFractionCSP3, NumRotatableBonds, "
                           "NumAromaticRings, MaxPartialCharge；NaN/inf 一律置 0"),
                 model="StandardScaler（在 fit 集拟合）+ RidgeClassifier(alpha=1.0)",
                 score="sigmoid(decision_function)；这是伪概率，只用于排序与求均值"),
            dict(name="rf_maccs",
                 features="MACCS keys，167 位",
                 model="RandomForestClassifier(n_estimators=300, random_state=seed, n_jobs=1)",
                 score="predict_proba(X)[:, 1]"),
        ],
        calibration=dict(
            method=("每个源各拟合一个 IsotonicRegression(out_of_bounds='clip')，"
                    "x=该源在 calibration 集上的原始分数，y=calibration 标签；"
                    "同一转换再应用到 test"),
            mean="mean_pc = 三个源校准后概率的算术平均",
            fallback="任一源拟合抛异常时，该源退化为恒等映射（不得借此剔除该源）",
        ),
        domain=dict(
            rule=("对每个 test 分子，计算它到 **fit 集全部训练分子** 的 Morgan2-2048 "
                  "Tanimoto 相似度的最大值；max_sim ≥ 0.35 判为域内"),
            note="域判据只用 fit 集做参照，不得用 calibration 或 test",
        ),
        threshold_rule=dict(
            grid="t 取 numpy.linspace(0.05, 0.95, 19)",
            min_keep="只接受 keep=(mean_pc_cal ≥ t) 且 keep.sum() ≥ max(10, 0.2×len(cal)) 的 t",
            risk="在 keep 子集上 pred=(mean_pc_cal ≥ 0.5)，risk=mean(pred ≠ y_cal)",
            select=("在 risk ≤ 0.15 的候选中取 coverage 最大者对应的 t；"
                    "若无候选满足，取 t=0.5"),
            apply="选出的 t 原样用于 test，不得在 test 上重新调",
        ),
        strategies={
            "S1_naive_majority": ("pred = 三源**未校准**概率各自以 0.5 二值化后的多数投票"
                                  "（≥2 票为 FAIL）；对全部 test 样本给出判定（不弃权）。"
                                  "注意：不是用均值概率阈值（那与票数多数在本数据上差约 0.03 效用），"
                                  "而是用三源二值票数的多数"),
            "S2_ad_guard": ("pred 同 S1（票数多数）；仅当 max_sim ≥ 0.35 时给出判定，否则弃权"),
            "S3_calibrated_conformal": "pred = (mean_pc ≥ 0.5)；仅当 mean_pc ≥ t 时给出判定",
            "S4_full_admission": ("pred = (mean_pc ≥ 0.5)；仅当 mean_pc ≥ t 且 max_sim ≥ 0.35 "
                                  "且 spread ≤ 0.30 时给出判定，其中 "
                                  "spread = max(三源**未校准**概率) − min(三源未校准概率)"),
            "口径说明（重要）": ("auc / risk 字段一律在 mean_pc_te（三源校准后概率均值）上计算，"
                                   "**与策略无关**；指标名前缀只表示该策略对应的基线，"
                                   "不代表 AUC 用的是该策略自己的二值分数——这是已知的命名缺陷，"
                                   "读取时请按本条理解"),
        },
        utility=dict(
            formula=("utility = −(1/N)·Σ_i cost_i，N=test 样本数；"
                     "cost = 0（判对）/ c_false_PASS（y=1 判成 PASS）/ "
                     "c_false_FAIL（y=0 判成 FAIL）/ c_abstain（弃权）"),
            costs=d.get("costs"),
            note="弃权样本计入分母 N，且只计 c_abstain",
        ),
        seeds=list(seeds),
        environment=dict(note="提交时必须附 python/rdkit/scikit-learn/numpy 实测版本"),
    )
    exp = R.build_pack(OUT, metrics, spec=spec, snapshots=snapshots,
                       pack_id="keystone-v41", strict_spec=True)
    print("挑战包写出：%s" % OUT)
    for m in exp["metrics"]:
        print("  %-46s value=%-10s tol=%-9s sd=%-9s n=%s" % (
            m["name"], m["value"], m["tol"], m["seed_sd"], m["n_seeds"]))

    # 自检：把期望值原样提交，应 all_pass 但触发 suspicious_identical
    self_sub = dict(metrics={m["name"]: dict(value=m["value"]) for m in exp["metrics"]})
    s = R.score(OUT, self_sub)
    print("自检（照抄期望值）：all_pass=%s suspicious_identical=%s"
          % (s["all_pass"], s["suspicious_identical"]))
    return 0


if __name__ == "__main__":
    # C5（2026-11-03 评审）：本脚本无 argparse，此前 `--help` 会被当作普通参数，
    # 直接执行全流程（run_replication_pack 实测会**写出挑战包**）——在 CI/评审复现时
    # 是看不见的写盘者。加早退：--help 只打印用法并 exit 0，不产生任何副作用。
    import sys as _sys
    if any(_a in ("-h", "--help") for _a in _sys.argv[1:]):
        print("用法：%s（无命令行参数；直接运行即按默认配置产出产物）" % __file__)
        raise SystemExit(0)
    sys.exit(main())
