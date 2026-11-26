# -*- coding: utf-8 -*-
"""P2.4-e：判别力之外的三个缺口——校准、类不平衡指标、决策曲线。

**为什么需要这个脚本（自查黑榜的可执行部分）**

AUC 只回答"排序对不对"。方法学审稿人一定会接着问三件事，而本包此前一件都没报：

1. **校准**：模型说 0.8，实际命中率是不是 0.8？（Brier + 校准斜率）
   AUC 高而校准差，等于"排序可用、概率不可用"——而本包的裁决层要吃概率阈值。
2. **类不平衡下的指标**：AP=0.894 看着漂亮，但基率 0.826，说明 AP 被基率撑着。
   需要 **MCC / lift** 这种对 prevalence 不敏感的量。
3. **决策曲线（DCA）**：域内外准确率差 −19pp 听起来大，但**在筛选决策里值多少**？
   DCA 用净收益（net benefit）回答"用这个门 vs 不用，在阈值概率 p_t 上谁更划算"，
   这是把统计差异翻译成决策价值的唯一标准工具。

**输入只读 per-sample CSV**（`run_gate_audit.py --dump-scores` 的产物），
不重新训练模型——因此任何人拿到同一份 CSV 都能复算，这本身就是可复现性。

用法：
    python run_gate_metrics.py
    python run_gate_metrics.py --csv out_ext/tdc/gate_scores_hERG.csv
"""
import csv
import io
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DEFAULT_CSVS = [
    ("hERG", "out_ext/tdc/gate_scores_hERG.csv"),
    ("DILI", "out_ext/tdc/gate_scores_DILI.csv"),
    ("BBB_Martins", "out_ext/tdc/gate_scores_BBB_Martins.csv"),
]


def _read(path):
    rows = []
    with io.open(path, encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            rows.append(dict(y=int(float(r["y_true"])),
                             p=float(r["model_prob"]),
                             pred=int(float(r["model_pred"])),
                             sim=float(r["sim"]),
                             gate=int(float(r["gate_passed"]))))
    return rows


def _auc(labels, scores):
    """Mann-Whitney 秩和（平局记 0.5），与 stats_ci 一致。"""
    pos = [s for s, y in zip(scores, labels) if y == 1]
    neg = [s for s, y in zip(scores, labels) if y == 0]
    if not pos or not neg:
        return None
    w = 0.0
    for a in pos:
        for b in neg:
            w += 1.0 if a > b else (0.5 if a == b else 0.0)
    return w / (len(pos) * len(neg))


def _ap(labels, scores):
    """平均精度（PR 曲线下面积，阶梯式），与 11 点插值不同——这里用标准定义。"""
    order = sorted(range(len(scores)), key=lambda i: -scores[i])
    lab = [labels[i] for i in order]
    tp = fp = 0
    prev = 0.0
    ap = 0.0
    for y in lab:
        if y == 1:
            tp += 1
        else:
            fp += 1
        rec = tp / float(sum(lab))
        prec = tp / float(tp + fp)
        ap += prec * (rec - prev)
        prev = rec
    return ap


def _mcc(tp, tn, fp, fn):
    den = (tp + fp) * (tp + fn) * (tn + fp) * (tn + fn)
    if den <= 0:
        return 0.0
    return (tp * tn - fp * fn) / math.sqrt(den)


def _brier(labels, probs):
    return sum((p - y) ** 2 for p, y in zip(probs, labels)) / float(len(labels))


def _ef(labels, scores, frac):
    """富集因子 EF@frac = 前 frac 比例里的命中率 / 全体基率。

    虚拟筛选真正被阅读的是 top-1%/5%，不是全局 AUC。两者可以背离：
    AUC 0.8 的模型在 top-1% 可能是 1.0 倍 EF（等于没富集）。
    **这里只对"全体分子按分数排序"这一标准口径计算**；"先过门再排序"是另一个
    口径（分母换了人群），不能与它混报，需单独定义并声明。
    """
    n = len(labels)
    k = max(1, int(round(n * frac)))
    order = sorted(range(n), key=lambda i: -scores[i])[:k]
    if not order:
        return None
    hits = sum(labels[i] for i in order)
    prev = sum(labels) / float(n)
    if prev <= 0:
        return None
    return round((hits / float(k)) / prev, 3)


def _calibration_slope(labels, probs):
    """校准斜率：把 logit(p) 当唯一自变量做 logistic 回归，理想值 1.0。

    不用 sklearn（避免为一个数引入依赖）：用 Newton-Raphson 两参数拟合，
    y ~ sigmoid(a + b*logit(p))，b 即斜率，a 即校准截距。
    完全分离时退化为 None，此时只能说"无法估计"，不能报 1.0。
    """
    xs, ys = [], []
    for p, y in zip(probs, labels):
        pc = min(max(p, 1e-6), 1 - 1e-6)
        xs.append(math.log(pc / (1 - pc)))
        ys.append(y)
    a, b = 0.0, 1.0
    for _ in range(100):
        ga = gb = 0.0
        haa = hab = hbb = 0.0
        for x, y in zip(xs, ys):
            z = a + b * x
            p = 1.0 / (1.0 + math.exp(-z))
            w = p * (1 - p)
            ga += y - p
            gb += (y - p) * x
            haa += -w
            hab += -w * x
            hbb += -w * x * x
        det = haa * hbb - hab * hab
        if abs(det) < 1e-12:
            return None
        da = (-ga * hbb + gb * hab) / det
        db = (-gb * haa + ga * hab) / det
        a += da
        b += db
        if abs(da) < 1e-9 and abs(db) < 1e-9:
            break
    return dict(intercept=round(a, 4), slope=round(b, 4))


def _net_benefit(tp, fp, n, pt):
    """决策曲线的净收益：NB = TPR - FPR * pt/(1-pt)。弃权者不计入 TP/FP 也不计入 n。"""
    if n == 0 or pt >= 1:
        return 0.0
    tpr = tp / float(n)
    fpr = fp / float(n)
    return tpr - fpr * (pt / (1 - pt))


def _dca(rows, thresholds):
    """两种策略：A=全部预测（模型单独用）；B=只在域内预测，域外弃权。

    基线 C=全判阳性，NB = prevalence - (1-prevalence)*pt/(1-pt)。
    判读：B 在 B>A 的阈值区间内才叫"门有价值"；若 B≈A 全程，门只是白丢覆盖率。
    """
    n = len(rows)
    out = []
    for pt in thresholds:
        # A：全部预测，阳性 = model_prob >= pt
        tpA = sum(1 for r in rows if r["y"] == 1 and r["p"] >= pt)
        fpA = sum(1 for r in rows if r["y"] == 0 and r["p"] >= pt)
        nbA = _net_benefit(tpA, fpA, n, pt)

        # B：域外弃权（既不算阳性也不算阴性），域内按模型判
        ind = [r for r in rows if r["gate"] == 1]
        tpB = sum(1 for r in ind if r["y"] == 1 and r["p"] >= pt)
        fpB = sum(1 for r in ind if r["y"] == 0 and r["p"] >= pt)
        nbB = _net_benefit(tpB, fpB, n, pt)

        prev = sum(r["y"] for r in rows) / float(n)
        nbC = prev - (1 - prev) * (pt / (1 - pt))
        out.append(dict(pt=round(pt, 3),
                        nb_model_all=round(nbA, 4),
                        nb_gated=round(nbB, 4),
                        nb_treat_all=round(nbC, 4),
                        coverage=round(len(ind) / float(n), 3)))
    wins = [d["pt"] for d in out if d["nb_gated"] > d["nb_model_all"] + 1e-9]
    return dict(curve=out, thresholds_where_gate_helps=wins,
                gate_helps_anywhere=bool(wins))


def analyze(rows):
    labels = [r["y"] for r in rows]
    probs = [r["p"] for r in rows]
    n = len(rows)
    n_pos = sum(labels)
    prev = n_pos / float(n)

    # --- 模型层 ---------------------------------------------------------
    preds = [r["pred"] for r in rows]
    tp = sum(1 for y, p in zip(labels, preds) if y == 1 and p == 1)
    tn = sum(1 for y, p in zip(labels, preds) if y == 0 and p == 0)
    fp = sum(1 for y, p in zip(labels, preds) if y == 0 and p == 1)
    fn = sum(1 for y, p in zip(labels, preds) if y == 1 and p == 0)
    model = dict(
        auc=round(_auc(labels, probs), 4),
        ap=round(_ap(labels, probs), 4),
        prevalence=round(prev, 4),
        # lift = AP / 基率：AP 被基率撑高了多少倍。1.0 表示"没有任何富集"。
        ap_lift_over_prevalence=round(_ap(labels, probs) / prev, 3) if prev else None,
        mcc=round(_mcc(tp, tn, fp, fn), 4),
        brier=round(_brier(labels, probs), 4),
        brier_baseline_prev=round(_brier(labels, [prev] * n), 4),
        # 富集因子（B6）：虚拟筛选读的是 top-k，不是全局 AUC
        ef_at=dict((("%g%%" % (100 * f)), _ef(labels, probs, f))
                   for f in (0.01, 0.05, 0.10)),
        # 饱和警戒：EF@1% 在 n=132 时只有 1 个分子（k=max(1,round(1.32))）。
        # 1 个分子的"富集倍数"就是 1/基率 或 0，**不具备解释力**。
        # 上限 = 1/基率：达到上限即说明"top-k 全是阳性"，这是饱和而非优秀。
        ef_k=dict((("%g%%" % (100 * f)), max(1, int(round(n * f))))
                  for f in (0.01, 0.05, 0.10)),
        ef_ceiling=round(1.0 / prev, 3) if prev else None,
        calibration=_calibration_slope(labels, probs),
        confusion=dict(tp=tp, tn=tn, fp=fp, fn=fn),
    )

    # --- 门层：把"模型是否会做对"当标签，sim 当分数 ---------------
    correct = [1 if y == p else 0 for y, p in zip(labels, preds)]
    sims = [r["sim"] for r in rows]
    gateflag = [r["gate"] for r in rows]          # 门的判决（sim>=0.35），不是 sim 本身
    # ⚠ 2026-11-03 自查抓到的 bug：这里第一版把 `sims` 当门判决去比 `== 1`，
    # 于是 tp/tn/fp/fn 全近似 0，MCC 恒等于 0.000 —— 看起来像"门毫无关联"，
    # 实际是"我在拿连续相似度当二值标签用"。已改为单独的 gateflag。
    gtp = sum(1 for c, g in zip(correct, gateflag) if c == 1 and g == 1)
    gtn = sum(1 for c, g in zip(correct, gateflag) if c == 0 and g == 0)
    gfp = sum(1 for c, g in zip(correct, gateflag) if c == 0 and g == 1)
    gfn = sum(1 for c, g in zip(correct, gateflag) if c == 1 and g == 0)
    gate = dict(
        auc_as_predictability=round(_auc(correct, sims), 4),
        ap_as_predictability=round(_ap(correct, sims), 4),
        base_correct_rate=round(sum(correct) / float(n), 4),
        mcc=round(_mcc(gtp, gtn, gfp, gfn), 4),
        confusion=dict(tp=gtp, tn=gtn, fp=gfp, fn=gfn),
        n_correct=sum(correct), n_wrong=n - sum(correct),
    )
    return dict(n=n, model=model, gate=gate)


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="", help="只分析单个 CSV；默认分析三端点")
    ap.add_argument("--out", default="out_ext/tdc/gate_metrics.json")
    ap.add_argument("--pt-grid", default="0.2,0.3,0.4,0.5,0.6,0.7",
                    help="决策曲线的阈值概率网格")
    a = ap.parse_args(argv)
    grid = [float(x) for x in a.pt_grid.split(",") if x.strip()]

    targets = ([("custom", a.csv)] if a.csv else DEFAULT_CSVS)
    payload, missing = {}, []
    for name, path in targets:
        if not os.path.exists(path):
            missing.append(path)
            continue
        rows = _read(path)
        res = analyze(rows)
        res["dca"] = _dca(rows, grid)
        payload[name] = res

    if not payload:
        print("没有可读的 per-sample CSV；先跑 "
              "run_gate_audit.py --endpoint <ep> --dump-scores <csv>")
        return 1

    payload["_interpretation"] = (
        "① 校准：calibration.slope 理想为 1.0、intercept 理想为 0；"
        "slope<1 表示预测过于极端（过拟合式自信），slope>1 表示过于保守。"
        "Brier 必须与 brier_baseline_prev（全判基率）对比，只看绝对值无意义。\n"
        "② 类不平衡：AP 会被基率撑高，故给出 ap_lift_over_prevalence = AP/基率；"
        "1.0=无富集。MCC 对 prevalence 不敏感，是这里更该看的单数。\n"
        "④ 富集因子 EF@k = 前 k 比例命中率/基率；1.0 表示与随机挑一样。"
        "它常与全局 AUC 背离，虚拟筛选场景必须单报。\n"
        "③ 决策曲线：nb_gated > nb_model_all 的阈值区间才是门真正值钱的区间；"
        "若全程不成立，则门只是白丢覆盖率。nb_treat_all 是全判阳性的基线。")

    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with io.open(a.out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)

    for name, r in payload.items():
        if name.startswith("_"):
            continue
        m, g, d = r["model"], r["gate"], r["dca"]
        cal = m["calibration"] or {}
        print("[%s] n=%d  基率=%.3f" % (name, r["n"], m["prevalence"]))
        print("   模型  AUC %.4f | AP %.4f | AP/基率 %.2f | MCC %.3f | Brier %.4f（全判基率 %.4f）"
              % (m["auc"], m["ap"], m["ap_lift_over_prevalence"] or 0, m["mcc"],
                 m["brier"], m["brier_baseline_prev"]))
        print("   校准  斜率 %s  截距 %s" % (cal.get("slope", "无法估计"),
                                        cal.get("intercept", "无法估计")))
        ef = m.get("ef_at") or {}
        efk = m.get("ef_k") or {}
        print("   富集  EF@1%% %s (k=%s) | EF@5%% %s (k=%s) | EF@10%% %s (k=%s) | 上限 %s"
              % (ef.get("1%"), efk.get("1%"), ef.get("5%"), efk.get("5%"),
                 ef.get("10%"), efk.get("10%"), m.get("ef_ceiling")))
        print("   门    AUC(as predictability) %.4f | MCC %.3f | 正确 %d / 错误 %d"
              % (g["auc_as_predictability"], g["mcc"], g["n_correct"], g["n_wrong"]))
        print("   DCA   门优于全预测的阈值：%s"
              % (", ".join("%.2f" % t for t in d["thresholds_where_gate_helps"]) or "无"))
    if missing:
        print("缺 CSV：%s" % ", ".join(missing))
    print("-> %s" % a.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
