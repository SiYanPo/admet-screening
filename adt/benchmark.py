# -*- coding: utf-8 -*-
"""独立分类基准协议（移植自 reverse-molecular-docking E8，按 ADMET 分类域改造）。

为什么需要它
------------
本 skill 一直承认"没有金标准，一切裁决正确性都是自述"。`examples/benchmark_vs_truth.py`
只做**逐行一致率**（框架 vs 均值投票），回答不了三个审稿人必问的问题：

  1) 判别力到底多少？（需要 AUROC/AUPRC，不是一致率）
  2) 这个数稳不稳？（需要**按化学簇聚类 bootstrap**，不能把 pair 当独立样本）
  3) 每个模块改善了什么？（需要**消融**：中位数共识 vs 均值投票，主终点变化）

与原 E8 的差异（**这是改造，不是照搬**）
----------------------------------------
反向 skill 的主终点是 hit@k / MRR / 库外拒答（检索任务）；ADMET 是**分类**任务，
真值是"实测 PASS/FAIL"，因此主终点改为 **AUROC / AUPRC**（正类 = FAIL/有毒），
"拒答"改为**真阳性覆盖率**（多少真阳性拿到了域内预测）。

真值要求（硬性）
----------------
truth.csv 必须是**实测**（domain_flag=measured 语义）。没有湿实验/文献实测时，
用 `--demo` 生成**合成真值**，只为验证指标代码与消融机制；输出打 DEMO 横幅，
**不得作为任何科学结论**。
"""

import csv
import io
import math
import os
import random

try:
    from .reliability import _f, _median, _judge
    from . import calibration as calib
except ImportError:  # 允许直接脚本运行
    from reliability import _f, _median, _judge  # type: ignore
    import calibration as calib  # type: ignore

PRED_FLAGS = {"predicted", "measured", "manual", "saturated"}

CAL_COLS = [
    "unit",
    "cal_n",
    "cal_n_pos",
    "brier",
    "brier_skill",
    "oe",
    "cal_slope",
    "cal_intercept",
    "ece",
    "cal_flag",
    "cal_note",
]


def _risk_score(v, rule):
    """把端点数值转成"越大越坏"的风险分数，并说明用了哪种定向。

    2026-11-19（真值驱动实跑暴露）：本函数此前**不存在**——`per[ep]` 直接把
    `_median(vals)` 当分数喂给 `_auroc`，等于假定所有端点都是"数值越大越坏"。
    在 OpenADMET 9 个端点上的后果（真实数据，n=2 282）：

        endpoint              shape    原报 AUROC   定向后
        openadmet_mppb        down     0.082        0.918
        openadmet_ksol        up       0.177        0.823
        openadmet_mbpb        down     0.176        0.824
        openadmet_mgmb        down     0.198        0.858
        openadmet_caco2_papp  up       0.356        0.644

    也就是说，按文档跑出的一张表里 5 个端点显示"模型比随机还差"，
    而真实原因是分数方向翻转了。任何人据此写"模型无效"都是被工具误导。
    window 型（如 logD 0–4）更严重：非单调，不存在单调分数，AUROC 结构性无定义，
    原实现照样给一个数（0.579），等于给出一个没有解释力的数字。
    """
    if not rule:
        return v, "raw_assumed_higher_is_risk"
    # 命名陷阱（2026-11-19 实测踩过一次）：规则里的 up/down 指**好坏方向**，
    # 不是数值方向。`_judge` 的实现是：
    #     shape=up   → PASS if value >= pass  → 越大越好 → 风险 = -value
    #     shape=down → PASS if value <= pass  → 越小越好 → 风险 = +value
    # 若按"数值方向"理解（up=数值大→风险大），会把 9 个端点里的 5 个整体翻反，
    # 例如 caco2_efflux 从 0.706 掉到 0.294、ksol 从 0.823 掉到 0.177。
    shape = (rule.get("shape") or "").strip().lower()
    if shape == "down":
        return v, "raw(shape=down: smaller_is_better)"
    if shape == "up":
        return -v, "negated(shape=up: larger_is_better)"
    if shape == "window":
        w = rule.get("window") or []
        if len(w) == 2:
            lo, hi = float(w[0]), float(w[1])
            # 窗口外越远越坏；窗口内风险 0（非单调 -> 只用"出窗距离"，须在产物里注明）
            return max(lo - v, v - hi, 0.0), "distance_outside_window"
        return v, "raw(window_without_bounds)"
    return v, "raw_assumed_higher_is_risk"


def _auroc(scores, labels):
    """Mann-Whitney AUROC（秩和法，处理并列）。labels: 1=正类(FAIL/有毒)。"""
    n_p = sum(1 for y in labels if y == 1)
    n_n = len(labels) - n_p
    if n_p == 0 or n_n == 0:
        return None
    order = sorted(range(len(scores)), key=lambda i: scores[i])
    ranks = [0.0] * len(scores)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and scores[order[j + 1]] == scores[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    r_pos = sum(r for r, y in zip(ranks, labels) if y == 1)
    return (r_pos - n_p * (n_p + 1) / 2.0) / (n_p * n_n)


def _auprc(scores, labels):
    """平均精度（average precision），正类=1。"""
    pairs = sorted(zip(scores, labels), key=lambda t: -t[0])
    total_pos = sum(y for _, y in pairs)
    if total_pos == 0:
        return None
    tp = fp = 0
    prev_rec = 0.0
    ap = 0.0
    for _, y in pairs:
        if y == 1:
            tp += 1
        else:
            fp += 1
        rec = tp / total_pos
        prec = tp / (tp + fp)
        ap += (rec - prev_rec) * prec
        prev_rec = rec
    return ap


def _mcc_youden(scores, labels):
    """在 Youden-J 最优阈值上算 MCC。分数越大越坏（正类=FAIL）。

    同行评审 §4 分歧 2：主表要同时给 MCC/PR-AUC/ECE/Brier，但 MCC 在不平衡下
    方差大（分歧 2 的反对意见）。因此这里显式采用**评估集上选阈值**的 Youden-J
    口径，并在 note 里标注"阈值评估集上选、偏乐观、不作主指标"——避免读者把
    一个挑过阈值的 MCC 当成无偏性能。主指标仍是 PR-AUC/AUROC + 校准。
    """
    n_p = sum(1 for y in labels if y == 1)
    n_n = len(labels) - n_p
    if n_p == 0 or n_n == 0:
        return None
    # 降序扫描：阈值从"全判负"逐步下移；同分样本必须同一阈值（整组一起累积），
    # 否则并列分数会被拆成多个虚假操作点，Youden-J 虚高。
    pairs = sorted(zip(scores, labels), key=lambda t: -t[0])
    best_j, best_tp, best_fp = -1.0, None, None  # 起点：全判负 J=0，但下面单独处理
    tp = fp = 0
    i = 0
    while i < len(pairs):
        j = i
        while j + 1 < len(pairs) and pairs[j + 1][0] == pairs[i][0]:
            j += 1
        for _, y in pairs[i : j + 1]:
            if y == 1:
                tp += 1
            else:
                fp += 1
        youden = tp / n_p - fp / n_n
        if youden > best_j or (youden == best_j and tp - fp > best_tp - best_fp):
            best_j, best_tp, best_fp = youden, tp, fp
        i = j + 1
    # Youden-J ≤ 0 表示"任何阈值的 TPR 增益都不超过 FPR 增益"——模型无正向判别力，
    # 此时只能退化为全判负/全判正，MCC 分母为 0 无定义。诚实返回 None，不报误导性的 0。
    if best_j <= 0 or best_tp is None:
        return None
    tn = n_n - best_fp
    fn = n_p - best_tp
    den = math.sqrt((best_tp + best_fp) * (best_tp + fn) * (tn + best_fp) * (tn + fn))
    return 0.0 if den == 0 else (best_tp * tn - best_fp * fn) / den


def _bootstrap(clusters, scores, labels, B, seed):
    """按化学簇重采样（整簇有放回），返回 AUROC 的 (p05, p95, n_clusters)。"""
    by_c = {}
    for c, s, y in zip(clusters, scores, labels):
        by_c.setdefault(c, []).append((s, y))
    keys = list(by_c)
    if len(keys) < 2:
        return None, None, len(keys)
    rng = random.Random(seed)
    vals = []
    for _ in range(B):
        ss, yy = [], []
        for _ in range(len(keys)):
            k = rng.choice(keys)
            for s, y in by_c[k]:
                ss.append(s)
                yy.append(y)
        a = _auroc(ss, yy)
        if a is not None:
            vals.append(a)
    if not vals:
        return None, None, len(keys)
    vals.sort()
    lo = vals[int(0.05 * (len(vals) - 1))]
    hi = vals[int(0.95 * (len(vals) - 1))]
    return lo, hi, len(keys)


def build(
    pred_rows,
    truth_rows,
    rules,
    clusters=None,
    B=1000,
    seed=42,
    demo=False,
    return_tables=False,
):
    """返回 (per_endpoint_rows, summary)；return_tables=True 时多返回校准分箱表 dict。

    pred_rows: 长表（多源）；对每个 (compound, endpoint) 取域内源的
               **中位数**（共识）与**均值**（朴素投票）作为两个打分器。
    truth_rows: [{compound_id, endpoint, truth_value, truth_class?, cluster?}]
    """
    tables = {}
    cluster_of = {
        c.get("compound_id"): (c.get("cluster") or c.get("compound_id"))
        for c in (clusters or [])
    }

    truth_map = {}
    truth_count = {}
    for t in truth_rows:
        cid, ep = t.get("compound_id"), t.get("endpoint")
        try:
            tv = float(t.get("truth_value"))
        except (TypeError, ValueError):
            continue
        tc = (t.get("truth_class") or "").strip().upper()
        if tc in ("PASS", "FAIL"):
            label = 1 if tc == "FAIL" else 0
        else:
            vd = _judge(tv, rules.get(ep))
            if vd is None:
                continue
            label = 1 if vd == "FAIL" else 0
        truth_map[(cid, ep)] = dict(
            label=label, value=tv, cluster=t.get("cluster") or cluster_of.get(cid)
        )
        truth_count[ep] = truth_count.get(ep, 0) + 1

    # 按 (compound, endpoint) 聚合域内源；同时记单位（校准门控要用）
    agg = {}
    for r in pred_rows:
        if r.get("domain_flag") not in PRED_FLAGS:
            continue
        v = _f(r.get("value"))
        if v is None:
            continue
        d = agg.setdefault(
            (r.get("compound_id"), r.get("endpoint")), dict(vals=[], units=[])
        )
        d["vals"].append(v)
        d["units"].append((r.get("unit") or "").strip().lower())

    per = {}
    for (cid, ep), d0 in agg.items():
        t = truth_map.get((cid, ep))
        if t is None:
            continue
        rule_ep = rules.get(ep)
        vals, orients = [], set()
        for _v in d0["vals"]:
            _s, _o = _risk_score(_v, rule_ep)
            vals.append(_s)
            orients.add(_o)
        d = per.setdefault(
            ep,
            dict(
                median=[], mean=[], labels=[], clusters=[], tp=0, units=[], orient=set()
            ),
        )
        d["orient"] |= orients
        d["median"].append(_median(vals))
        d["mean"].append(sum(vals) / len(vals))
        d["labels"].append(t["label"])
        d["clusters"].append(t["cluster"] or cid)
        d["units"].extend([u for u in d0["units"] if u])
        if t["label"] == 1:
            d["tp"] += 1

    out = []
    for ep in sorted(per):
        d = per[ep]
        cov = len(d["labels"]) / truth_count.get(ep, len(d["labels"]))
        unit = _mode_unit(d["units"])
        if len(set(d["labels"])) < 2:
            out.append(
                dict(
                    endpoint=ep,
                    n_pairs=len(d["labels"]),
                    n_pos=d["tp"],
                    coverage=round(cov, 3),
                    auroc="",
                    auroc_p05="",
                    auroc_p95="",
                    auprc="",
                    mcc="",
                    mean_vote_auroc="",
                    delta_median_vs_mean="",
                    cluster_n="",
                    unit=unit,
                    cal_n="",
                    cal_n_pos="",
                    brier="",
                    brier_skill="",
                    oe="",
                    cal_slope="",
                    cal_intercept="",
                    ece="",
                    cal_flag="not_applicable",
                    cal_note="单一类别：判别力与校准均无定义",
                    score_orient=";".join(sorted(d.get("orient") or [])),
                    note="单一类别，无法算 AUROC",
                )
            )
            continue
        a = _auroc(d["median"], d["labels"])
        pr = _auprc(d["median"], d["labels"])
        mcc = _mcc_youden(d["median"], d["labels"])
        lo, hi, ncl = _bootstrap(d["clusters"], d["median"], d["labels"], B, seed)
        am = _auroc(d["mean"], d["labels"])
        delta = (a - am) if (a is not None and am is not None) else None
        c = calib.assess(d["median"], d["labels"], unit=unit)
        if c["flag"] in ("acceptable", "poor"):
            tables[ep] = calib.table(d["median"], d["labels"])
        notes = []
        if demo:
            notes.append("DEMO(合成真值)")
        if ncl and ncl < 10:
            notes.append("聚类数 %d<10，CI 宽" % ncl)
        if cov < 0.8:
            notes.append("真阳性覆盖率 %.0f%%<80%%（域外/缺失多）" % (cov * 100))
        if c["flag"] == "poor":
            notes.append("校准：" + c["note"][:40])
        if "distance_outside_window" in (d.get("orient") or ()):
            notes.append(
                "窗口型端点：AUROC 基于出窗距离（非单调端点的合法单调化），"
                "不可与方向型端点的 AUROC 直接比大小"
            )
        if "raw_assumed_higher_is_risk" in (d.get("orient") or ()):
            notes.append(
                "未提供端点规则：按'数值越大越坏'打分，方向可能反了"
                "（--rules 可修正）"
            )
        if mcc is not None:
            notes.append(
                "MCC 用 Youden-J 阈值（评估集上选，偏乐观，不作主指标；"
                "主指标 PR-AUC/AUROC+校准）"
            )
        out.append(
            dict(
                endpoint=ep,
                n_pairs=len(d["labels"]),
                n_pos=d["tp"],
                coverage=round(cov, 3),
                auroc=round(a, 3) if a is not None else "",
                auroc_p05=round(lo, 3) if lo is not None else "",
                auroc_p95=round(hi, 3) if hi is not None else "",
                auprc=round(pr, 3) if pr is not None else "",
                mcc=round(mcc, 3) if mcc is not None else "",
                mean_vote_auroc=round(am, 3) if am is not None else "",
                delta_median_vs_mean=round(delta, 3) if delta is not None else "",
                cluster_n=ncl,
                unit=unit,
                cal_n=c["n"],
                cal_n_pos=c["n_pos"],
                brier=c["brier"],
                brier_skill=c["brier_skill"],
                oe=c["oe"],
                cal_slope=c["cal_slope"],
                cal_intercept=c["cal_intercept"],
                ece=c["ece"],
                cal_flag=c["flag"],
                cal_note=c["note"],
                score_orient=";".join(sorted(d.get("orient") or [])),
                note="；".join(notes),
            )
        )
    aucs = [r["auroc"] for r in out if isinstance(r["auroc"], float)]
    n_cal = sum(1 for r in out if r.get("cal_flag") in ("acceptable", "poor"))
    summary = dict(
        n_endpoints=len(out),
        n_auroc=len(aucs),
        mean_auroc=round(sum(aucs) / len(aucs), 3) if aucs else None,
        n_pairs=sum(r["n_pairs"] for r in out),
        demo=demo,
        n_calibrated=n_cal,
        n_cal_poor=sum(1 for r in out if r.get("cal_flag") == "poor"),
    )
    if return_tables:
        return out, summary, tables
    return out, summary


def _mode_unit(units):
    """取出现最多的单位（多源同端点可能单位不同；校准按众数单位门控）。"""
    if not units:
        return ""
    counts = {}
    for u in units:
        counts[u] = counts.get(u, 0) + 1
    return max(counts, key=counts.get)


def write_calibration_tables(path, tables):
    cols = ["endpoint", "bin", "n", "mean_pred", "obs_rate", "ci_low", "ci_high", "gap"]
    n = 0
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with io.open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for ep in sorted(tables):
            for r in tables[ep]:
                w.writerow(dict(endpoint=ep, **r))
                n += 1
    return n


def write(path, rows):
    cols = (
        [
            "endpoint",
            "n_pairs",
            "n_pos",
            "coverage",
            "auroc",
            "auroc_p05",
            "auroc_p95",
            "auprc",
            "mcc",
            "mean_vote_auroc",
            "delta_median_vs_mean",
            "cluster_n",
            "score_orient",
        ]
        + CAL_COLS
        + ["note"]
    )
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with io.open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return len(rows)


# ---------------------------------------------------------------------------
# 金标准与标准切分（TDC 2021, NeurIPS Datasets & Benchmarks, arXiv:2102.09548）
# ---------------------------------------------------------------------------
# 为什么必须用 scaffold split：随机切分会让同一骨架的类似物同时出现在训练/测试，
# 造成"记住骨架=猜对标签"的泄漏，AUROC 虚高 0.1–0.3。TDC/MoleculeNet 的标准做法
# 是按 Bemis-Murcko 骨架整簇切分。skill 之前只有"按化合物 id 切"，等于随机切分。
ACYCLIC = "ACYCLIC"


def scaffold_clusters(compounds, smiles_col=None):
    """Bemis-Murcko 骨架聚类（整簇不可分）。

    compounds: [{compound_id, smiles|calc_smiles, ...}]
    返回 [{compound_id, cluster, smiles}]；无环分子统一归入 ACYCLIC 桶
    （与 MoleculeNet/TDC 一致；这类分子没有可分的骨架，单独成簇会虚增簇数）。
    """
    from rdkit import Chem, RDLogger
    from rdkit.Chem.Scaffolds import MurckoScaffold

    RDLogger.DisableLog("rdApp.*")
    out = []
    for c in compounds:
        smi = (
            c.get("calc_smiles")
            or c.get("smiles")
            or (c.get(smiles_col) if smiles_col else "")
            or ""
        )
        m = Chem.MolFromSmiles(smi) if smi else None
        scaf = ""
        if m is not None:
            try:
                scaf = MurckoScaffold.MurckoScaffoldSmiles(
                    mol=m, includeChirality=False
                )
            except Exception:  # noqa: BLE001  骨架化失败不该拖垮整批
                scaf = ""
        out.append(
            dict(compound_id=c["compound_id"], cluster=(scaf or ACYCLIC), smiles=smi)
        )
    return out


def scaffold_split(clusters, frac_train=0.8, frac_val=0.1):
    """按骨架**整簇**分配到 train/val/test（大簇优先，容量约束）。

    两个返回：``(rows, info)``；rows = [{compound_id, cluster, split}]。
    info 里给 ``degenerate`` 标记——**骨架簇太少时无法切分**（例如整个系列只有
    2 个骨架），此时会退化成一两个集合；这必须显式告知，不能假装切开了。

    与 MoleculeNet 的 `scaffold_split` 语义一致：同一骨架绝不跨集。
    """
    by = {}
    for r in clusters:
        by.setdefault(r["cluster"], []).append(r["compound_id"])
    total = sum(len(v) for v in by.values())
    # 大簇先分（更难满足比例），ACYCLIC 通常最大 → 自然先占满 train
    order = sorted(by.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    n_train = int(frac_train * total)
    n_val = int(frac_val * total)
    n_test = total - n_train - n_val
    cap = dict(train=n_train, val=n_val, test=n_test)
    sets = dict(train=[], val=[], test=[])
    for _scaf, ids in order:
        target = None
        for k in ("train", "val", "test"):
            if len(sets[k]) + len(ids) <= cap[k]:
                target = k
                break
        if target is None:  # 放不下的簇进 train（保住整簇不跨集）
            target = "train"
        sets[target].extend(ids)
    # 簇"块大"时容量约束可能让 val/test 全空。若簇数≥3，把 train 里**最小的整簇**
    # 移入空集（整簇迁移，不破坏不跨集性质）；迁移行为写进 info，不静默。
    relocated = []
    if len(by) >= 3:
        for k in ("val", "test"):
            if sets[k]:
                continue
            cand = sorted(
                [c for c in by if set(by[c]) <= set(sets["train"])],
                key=lambda c: (len(by[c]), c),
            )
            if cand:
                c = cand[0]
                keep = set(by[c])
                sets["train"] = [x for x in sets["train"] if x not in keep]
                sets[k] = list(by[c])
                relocated.append(dict(cluster=c, to=k, n=len(by[c])))
    out = []
    cid2scaf = {cid: scaf for scaf, ids in by.items() for cid in ids}
    for k, ids in sets.items():
        for cid in ids:
            out.append(dict(compound_id=cid, cluster=cid2scaf.get(cid, ""), split=k))
    out.sort(key=lambda r: r["compound_id"])
    empty = [k for k in ("train", "val", "test") if not sets[k]]
    info = dict(
        n_clusters=len(by),
        n=total,
        sizes={k: len(v) for k, v in sets.items()},
        degenerate=bool(empty),
        empty_splits=empty,
        relocated=relocated,
        note=(
            ("骨架簇仅 %d 个：无法做三集切分（同系类似物系列必然泄漏）" % len(by))
            if empty
            else (
                "为保证三集非空，已将 %d 个最小簇整簇迁入空集" % len(relocated)
                if relocated
                else ""
            )
        ),
    )
    return out, info


# TDC 单任务文件的常见列名（Drug_ID / Y 是官方 Dataloader 的默认名）
TDC_ID_CANDIDATES = ("Drug_ID", "drug_id", "compound_id", "SMILES", "smiles", "Drug")
TDC_Y_CANDIDATES = ("Y", "y", "label", "Label", "target", "value")
TDC_SPLIT_CANDIDATES = ("split", "Split", "scaffold_split", "group")


def load_tdc_truth(path, endpoint, id_col=None, y_col=None, class_threshold=None):
    """读 TDC 格式的真值文件（离线，需事先从 TDC 下载）。

    返回 (truth_rows, meta)。truth_rows 的字段与 native truth 一致：
      compound_id / endpoint / truth_value / truth_class / source / provenance_url
    分类任务（Y∈{0,1}）直接给 truth_class=PASS/FAIL；
    回归任务给 truth_value，由规则表阈值判 PASS/FAIL（不猜类别）。
    """
    rows = list(csv.DictReader(io.open(path, encoding="utf-8-sig")))
    if not rows:
        return [], dict(n=0, note="空文件")
    cols = list(rows[0].keys())
    idc = id_col or next((c for c in TDC_ID_CANDIDATES if c in cols), None)
    yc = y_col or next((c for c in TDC_Y_CANDIDATES if c in cols), None)
    if not idc or not yc:
        raise ValueError("TDC 真值缺少可识别的 id / label 列；现有列=%s" % cols)
    out = []
    for r in rows:
        cid = (r.get(idc) or "").strip()
        try:
            v = float(r.get(yc))
        except (TypeError, ValueError):
            continue
        if not cid:
            continue
        cls = ""
        if class_threshold is None and v in (0.0, 1.0):
            cls = "FAIL" if v == 1 else "PASS"
        elif class_threshold is not None:
            cls = "FAIL" if v >= class_threshold else "PASS"
        out.append(
            dict(
                compound_id=cid,
                endpoint=endpoint,
                truth_value=v,
                truth_class=cls,
                source="TDC",
                assay="TDC curated dataset",
                provenance_url="https://tdcommons.ai/",
            )
        )
    return out, dict(n=len(out), id_col=idc, y_col=yc, n_cols=len(cols))


def demo_data(n_compounds=60, endpoints=("DILI", "Ames", "hERG"), seed=42):
    """合成真值 + 3 个不同噪声源（仅验证指标与消融代码；不是科学结果）。"""
    rng = random.Random(seed)
    pred, truth, clusters = [], [], []
    sigmas = (0.15, 0.25, 0.35)
    for i in range(n_compounds):
        cid = "C%03d" % i
        clusters.append(dict(compound_id=cid, cluster="cl%02d" % (i % 12)))
        for ep in endpoints:
            latent = 1 if rng.random() < 0.5 else 0
            truth.append(
                dict(
                    compound_id=cid,
                    endpoint=ep,
                    truth_value=latent,
                    truth_class=("FAIL" if latent else "PASS"),
                )
            )
            for k, sd in enumerate(sigmas, 1):
                val = max(0.0, min(1.0, latent * 0.6 + 0.4 + rng.gauss(0, sd)))
                pred.append(
                    dict(
                        compound_id=cid,
                        endpoint=ep,
                        value=round(val, 4),
                        unit="probability",
                        domain_flag="predicted",
                        source="src%d" % k,
                    )
                )
    return pred, truth, clusters
