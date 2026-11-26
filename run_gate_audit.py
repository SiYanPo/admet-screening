# -*- coding: utf-8 -*-
"""R19/R20 真实数据：gate 审计（hERG held-out）。

回答评审 C8 的竞争性解释：58% PASSTHRU 到底是"域外诚实"还是"gate 太粗糙"。
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

from adt import gate_audit                                        # noqa: E402

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
    # P2.4-b（2026-11-03 评审）：落盘 per-sample 分数，否则 AUC 的 95% CI 永远算不出来。
    # 没有逐分子 (y_true, score) 就只能给点估计，而红线 7 现在要求 CI。
    ap.add_argument("--dump-scores", default="", dest="dump_scores",
                   help="把逐分子 (y_true, score, gate_passed, sim, in_domain) 写成 CSV；"
                        "给了才可能算 AUC 的 95%% CI（注意 argparse 会用 %% 做格式化，"
                        "这里必须写双百分号，否则 --help 直接崩）")
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
    prob = clf.predict_proba(to_np(mols_te))[:, 1]
    pred = (prob >= 0.5).astype(int)

    ref_fps = [fp(m) for m in mols_tr]
    sims = [max(DataStructs.BulkTanimotoSimilarity(fp(m), ref_fps)) for m in mols_te]

    rows = gate_audit.sweep(sims, y_te, pred)
    curve = gate_audit.roc_pr(sims, y_te, pred)

    # ---- P2.4-b：逐分子分数落盘 + AUC 的 95% CI ----
    # ⚠ 三个 AUC 名字不同、**回答的问题不同**，绝不可互相顶替。
    # 2026-11-03 我在这里犯过两次错（一次贴到 model 精度上，一次把基线当成门的能力），
    # 故把口径写死在代码里，靠命名强制区分：
    #
    #   gate_as_predictability : label = (模型这一条是否预测正确) , score = sims
    #       → "门能不能判出模型这一条会不会错"。
    #         这就是材料里 0.58 的那一格，等同 gate_audit.roc_pr 的
    #         auc_gate_as_predictability，只是换了更稳的估计量并补了 CI。
    #   sim_as_label_baseline  : label = (真值) , score = sims
    #       → "最近邻相似度本身能不能分类"。这是**基线**（nearest-neighbour），
    #         不是门的能力。我曾用真值当 label 算出 0.6857 并误标成 gate 的 AUC，
    #         错误在于：门判的是"模型可不可信"，不是"标签是阳性还是阴性"。
    #   model_auc              : label = (真值) , score = prob
    #       → "模型本身准不准"（≈0.79）。与门无关，仅供对照。
    correct = (np.asarray(y_te) == np.asarray(pred)).astype(int)
    auc_ci = None
    try:
        from adt.stats_ci import auc_bootstrap_ci
        auc_ci = dict(
            gate_as_predictability=auc_bootstrap_ci(
                correct.tolist(), [float(x) for x in sims], n_boot=2000),
            sim_as_label_baseline=auc_bootstrap_ci(
                y_te.tolist(), [float(x) for x in sims], n_boot=2000),
            model_auc=auc_bootstrap_ci(
                y_te.tolist(), prob.tolist(), n_boot=2000),
        )
        # 估计量交叉核对：同一格 gate_as_predictability，roc_pr 用梯形积分
        # （未合并相似度平局、缺 (0,0) 起点），这里用 Mann-Whitney 秩和（平局记 0.5）。
        # 两数不相等是**正常的**；差值即梯形估计的离散化偏差。两个都写进产物，
        # 不许只报好看的那个——这正是"不许伪造精度"的具体落地。
        auc_ci["estimator_check"] = dict(
            trapezoid_roc_pr=curve.get("auc_gate_as_predictability"),
            mann_whitney=auc_ci["gate_as_predictability"]["auc"],
            note="同一格两种估计量。若二者在 4 位小数内一致 → 该 AUC 不是 ROC 离散化/"
                 "平局处理造成的伪影；若明显不一致 → 以 Mann-Whitney 为准并排查 roc_pr",
        )
    except Exception as exc:                      # 不阻断主流程，但要留痕
        auc_ci = dict(error=type(exc).__name__, detail=str(exc)[:200])

    # 统一四舍五入到 4 位小数：一是 G10 主张登记表要按字面量 token 核验
    # （"0.4561" 能匹配、"0.4560846560846561" 只会在换 seed 后失效）；
    # 二是 bootstrap 的第 5 位以后没有科学含义，多写就是伪造精度。
    if auc_ci and "error" not in auc_ci:
        for _k, _v in list(auc_ci.items()):
            if isinstance(_v, dict) and _v.get("auc") is not None:
                for _f in ("auc", "lo", "hi"):
                    if _v.get(_f) is not None:
                        _v[_f] = round(float(_v[_f]), 4)
        auc_ci["estimator_check"]["mann_whitney"] = round(
            float(auc_ci["estimator_check"]["mann_whitney"]), 4)

    # CI 必须先算出来，再交给 discriminative_power 判"有没有判别力"：
    # 只比点估计会让人把"0.580 < 0.65"读成"已证明无判别力"，而 0.580 的 CI
    # [0.456, 0.701] 上界越过了 0.65 —— 那句话是过头的（详见 gate_audit 文档串）。
    power = gate_audit.discriminative_power(
        sims, y_te, pred, auc_ci=(auc_ci or {}).get("gate_as_predictability"))
    summ = gate_audit.actionability_summary(rows, 0.35, power=power)

    # 给材料作者一句可直接抄的句子：省得每篇各写各的、抄错口径。
    # ⚠ 这句话必须由 verdict_ci 驱动，**不能**写死"点估计低于 0.65、只能说未证明"：
    # 2026-11-03 我第一版把它写死了，结果 DILI（AUC 0.668 > 0.65，属
    # informative_unconfirmed）被机器生成成"点估计低于工作点"——工具自己造谣。
    if auc_ci and "error" not in auc_ci:
        _g = auc_ci["gate_as_predictability"]
        auc_ci["sentence_zh"] = (
            "%s 上，门作为'可预测性分类器'的 AUC %.4f，95%%CI [%.4f, %.4f]"
            "（percentile bootstrap %d 次重抽，固定种子）；n=%d（预测正确 %d / 错误 %d）。"
            "判定（CI 口径 `%s`）：%s"
            % (ep, _g["auc"], _g["lo"], _g["hi"], _g.get("n_boot") or 0, _g["n"],
               _g["n_pos"], _g["n_neg"], power["verdict_ci"], power["interpretation"]))

    # 关键判读：域外分子的"强制预测"准确率 vs 域内（Fisher 精确检验）
    sims_a = np.asarray(sims)
    out = sims_a < 0.35
    forced = gate_audit.forced_prediction_test(y_te, pred, out)
    if a.dump_scores:
        import csv as _csv
        os.makedirs(os.path.dirname(a.dump_scores) or ".", exist_ok=True)
        # 列名即契约。此前把头写成 gate_passed 却写的是模型预测（prob>=0.5），
        # 而真正的门是 sim>=0.35——列名撒谎会让下游把"模型预测"当"门判决"，
        # 于是"门的判别力"里混进模型自己的准确率。改正：model_pred / gate_passed 分列。
        with io.open(a.dump_scores, "w", encoding="utf-8-sig", newline="") as fh:
            w = _csv.writer(fh)
            w.writerow(["idx", "y_true", "model_prob", "model_pred",
                        "model_correct", "sim", "gate_passed"])
            for i, (yt, p_, pr, sm, ok) in enumerate(
                    zip(y_te.tolist(), prob.tolist(), pred.tolist(), sims, correct.tolist())):
                w.writerow([i, int(yt), float(p_), int(pr), int(ok),
                            float(sm), int(float(sm) >= 0.35)])
        print("[gate] per-sample 分数 -> %s（可复算三个 AUC）" % a.dump_scores)

    payload = {
        "endpoint": ep, "n_test": int(len(y_te)),
        "ad_threshold_ref": 0.35,
        "sweep": rows, "roc_pr": curve, "actionability": summ,
        "gate_power": power,
        "forced_prediction_accuracy": forced,
        "auc_ci": auc_ci,
    }
    os.makedirs("out_ext/tdc", exist_ok=True)
    io.open("out_ext/tdc/gate_audit_%s.json" % ep, "w", encoding="utf-8").write(
        json.dumps(payload, ensure_ascii=False, indent=2))
    if ep == "hERG":                       # 保持旧路径可引用
        io.open("out_ext/tdc/gate_audit.json", "w", encoding="utf-8").write(
            json.dumps(payload, ensure_ascii=False, indent=2))
    print(json.dumps(payload["roc_pr"], ensure_ascii=False, indent=2))
    print(json.dumps(payload["gate_power"], ensure_ascii=False, indent=2))
    print(json.dumps(payload["forced_prediction_accuracy"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
