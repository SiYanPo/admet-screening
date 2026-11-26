# -*- coding: utf-8 -*-
"""方向一：验证策略的乐观偏差审计（Split-Sensitivity Meta-Assertion）。

变异分数证明"代码变异能被断言抓住"，不证明"断言在真实分布偏移下仍成立"。
本模块把验证分割本身变成门禁对象：

  random / scaffold(Bemis-Murcko) / cluster(sphere-exclusion) / time

同一组预测值在四种分割上分别算 MCC；若聚类或时间分割相对随机分割
的下降超过红线，`ci_gate` 直接失败——不允许用"机制全过"掩盖
"验证场景乐观"。
"""

from __future__ import annotations

import math
import random
from collections import defaultdict

try:
    from rdkit import Chem, DataStructs
    from rdkit.Chem import rdFingerprintGenerator
    from rdkit.Chem.Scaffolds import MurckoScaffold

    _HAS_RDKIT = True
except Exception:
    _HAS_RDKIT = False


def mcc(y_true, y_pred):
    tp = sum(1 for a, b in zip(y_true, y_pred) if a == 1 and b == 1)
    tn = sum(1 for a, b in zip(y_true, y_pred) if a == 0 and b == 0)
    fp = sum(1 for a, b in zip(y_true, y_pred) if a == 0 and b == 1)
    fn = sum(1 for a, b in zip(y_true, y_pred) if a == 1 and b == 0)
    den = math.sqrt((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn))
    return 0.0 if den == 0 else (tp * tn - fp * fn) / den


def _fp(smiles):
    if not _HAS_RDKIT:
        return None
    m = Chem.MolFromSmiles(str(smiles))
    if m is None:
        return None
    return rdFingerprintGenerator.GetMorganGenerator(
        radius=2, fpSize=2048
    ).GetFingerprint(m)


def scaffold_of(smiles):
    if not _HAS_RDKIT:
        return str(smiles)
    m = Chem.MolFromSmiles(str(smiles))
    if m is None:
        return "PARSE_FAILED"
    return MurckoScaffold.MurckoScaffoldSmiles(mol=m) or "NO_SCAFFOLD"


def split_random(records, *, frac=0.2, seed=20261122):
    idx = list(range(len(records)))
    random.Random(seed).shuffle(idx)
    n_test = max(1, int(len(idx) * frac))
    return idx[n_test:], idx[:n_test]


def split_scaffold(records, *, frac=0.2, seed=20261122):
    groups = defaultdict(list)
    for i, r in enumerate(records):
        groups[scaffold_of(r.get("smiles"))].append(i)
    keys = sorted(groups)
    random.Random(seed).shuffle(keys)
    total, target = len(records), max(1, int(len(records) * frac))
    test = []
    for k in keys:
        if len(test) >= target:
            break
        test.extend(groups[k])
    test_set = set(test)
    train = [i for i in range(total) if i not in test_set]
    return train, test


def cluster_assignments(records, *, threshold=0.4):
    """sphere-exclusion 聚类；返回 idx -> cluster_id。"""
    fps = [_fp(r.get("smiles")) for r in records]
    clusters = {}
    seeds = []
    for i, fp in enumerate(fps):
        if fp is None:
            clusters[i] = "PARSE_FAILED"
            continue
        assigned = None
        for sid, sfp in seeds:
            if DataStructs.TanimotoSimilarity(fp, sfp) >= threshold:
                assigned = sid
                break
        if assigned is None:
            assigned = "C%d" % len(seeds)
            seeds.append((assigned, fp))
        clusters[i] = assigned
    return clusters


def split_cluster(records, *, frac=0.2, threshold=0.4, seed=20261122):
    clusters = cluster_assignments(records, threshold=threshold)
    groups = defaultdict(list)
    for i, c in clusters.items():
        groups[c].append(i)
    # 压力优先：大簇先进 test，避免"随机挑小簇"稀释分布偏移
    keys = sorted(groups, key=lambda k: (-len(groups[k]), k))
    target, test = max(1, int(len(records) * frac)), []
    for k in keys:
        if len(test) >= target:
            break
        test.extend(groups[k])
    test_set = set(test)
    return [i for i in range(len(records)) if i not in test_set], test


def split_time(records, *, frac=0.2):
    order = sorted(
        range(len(records)), key=lambda i: (str(records[i].get("year", "9999")), i)
    )
    n_test = max(1, int(len(order) * frac))
    test = order[-n_test:]
    test_set = set(test)
    return [i for i in order if i not in test_set], test


def evaluate_splits(records, *, pred_key="pred", frac=0.2, cluster_threshold=0.4):
    y = [int(r.get("label", 0)) for r in records]
    p = [int(r.get(pred_key, 0)) for r in records]
    out = {}
    for name, fn in (
        ("random", split_random),
        ("scaffold", split_scaffold),
        ("cluster", split_cluster),
        ("time", split_time),
    ):
        kwargs = {"frac": frac}
        if name == "cluster":
            kwargs["threshold"] = cluster_threshold
        _, test = fn(records, **kwargs)
        out[name] = {
            "n_test": len(test),
            "n_total": len(records),
            "mcc": round(mcc([y[i] for i in test], [p[i] for i in test]), 6),
            "positive_rate": round(sum(y[i] for i in test) / max(1, len(test)), 4),
        }
    return out


def split_sensitivity_gate(split_metrics, *, max_gap=0.15, min_random_mcc=0.40):
    """红线：聚类/时间分割相对随机分割的 MCC 下降不得超过 max_gap。"""
    rand = split_metrics["random"]["mcc"]
    gaps = {
        k: round(rand - split_metrics[k]["mcc"], 6)
        for k in ("scaffold", "cluster", "time")
    }
    reasons = []
    if rand < min_random_mcc:
        reasons.append("随机分割 MCC %.3f < 最低可用 %.3f" % (rand, min_random_mcc))
    for k in ("cluster", "time"):
        if gaps[k] > max_gap:
            reasons.append("%s 分割下降 %.3f > 红线 %.3f" % (k, gaps[k], max_gap))
    worst = max(gaps.values()) if gaps else 0.0
    return {
        "ok": not reasons,
        "reasons": reasons,
        "random_mcc": rand,
        "gaps": gaps,
        "worst_gap": worst,
        "verdict": "OPTIMISTIC" if reasons else "STABLE",
        "note": "只证明该预测在这些分割上的稳健性；不证明模型科学正确",
    }


def build_report(records, *, max_gap=0.15, cluster_threshold=0.4):
    metrics = evaluate_splits(records, cluster_threshold=cluster_threshold)
    gate = split_sensitivity_gate(metrics, max_gap=max_gap)
    return {
        "metrics": metrics,
        "gate": gate,
        "split_semantics": ["random", "scaffold", "cluster", "time"],
        "cluster_threshold": cluster_threshold,
    }
