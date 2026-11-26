# -*- coding: utf-8 -*-
"""黑榜三项的可执行闭环：C9（统一分数口径）/ A1（权重方案裁决）/ A4（基线强度外推）。

三项共用 run_evidence_export.py 导出的同一批分子级概率，避免各自训练导致口径漂移。

C9  把 S1–S4 压到**同一个分数**（|p_cal−0.5|）与**同一个预测**（p_cal≥0.5），
    于是策略之间只剩"弃权规则"这一个差异；每个策略的实际运行点与
    "同 coverage 下纯置信度能到的 risk"比较，给出 efficiency_gap。
    —— 这是对评审"换口径绕过原问题"的直接回答：不再换口径，而是统一口径。

A1  等权 / 收缩 / BMA 代理 / 多样性折扣 四种源级权重，在 cal 上估、test 上打分，
    配对（同种子）比较 log-loss / Brier / AUC / acc。

A4  把三源里最弱的 ridge 换成 HistGradientBoosting 强基线，策略与代价完全不变，
    只改"基线强度"，看 S4−S1 的效用差是否翻转。

用法：python run_blacklist_analysis.py --dir out_blacklist
"""
import argparse
import io
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from adt import selective as SEL          # noqa: E402
from adt import weights as W              # noqa: E402
from adt import independence as IND       # noqa: E402
import run_keystone as K                  # noqa: E402

AD_THRESHOLD = K.AD_THRESHOLD
SPREAD_MAX = 0.30
WEAK = [0, 1, 2]        # rf_morgan / ridge_desc / rf_maccs
STRONG_SWAP = [0, 3, 2]  # 用 strong_hgb 取代 ridge_desc


def arms(name):
    return K.COSTS[name]


def _thr_margin(mean_pc_cal, y_cal, costs, target_risk=0.15):
    """在 cal 上选 p 阈值，转成"距 0.5 的 margin"阈值（统一口径用）。"""
    t = K.pick_threshold(mean_pc_cal, y_cal, target_risk, costs)
    return float(abs(t - 0.5)), float(t)


def _boot_ci(d, n=2000, seed=0):
    """bootstrap 95%CI。**统计量必须与汇报的点估计一致**。

    第一版用 np.mean 做 bootstrap 但汇报 np.median，导致出现
    「median=−0.0004 而 CI=[+0.004,+0.014]」这种自相矛盾的输出（BBB 的 S4 gap）。
    均值受少数极端种子拉动，中位数不受；两者不能混用。
    """
    rng = np.random.default_rng(seed)
    d = np.asarray(d, dtype=float)
    b = np.array([np.median(rng.choice(d, len(d), replace=True)) for _ in range(n)])
    lo, hi = np.percentile(b, [2.5, 97.5])
    return round(float(lo), 4), round(float(hi), 4)


def analyze_endpoint(ep, z):
    y = z["y"].astype(int)
    y_cal = z["y_cal"].astype(int)
    ad = z["ad_sim"].astype(float)
    P_raw, P_cal = z["P_raw"].astype(float), z["P_cal"].astype(float)
    C_raw, C_cal = z["C_raw"].astype(float), z["C_cal"].astype(float)
    SRC = [str(s) for s in z["SRC"]]
    n_seeds = P_cal.shape[0]
    costs = arms(ep)

    # ---------- 单源强度（A4 的前置事实） ----------
    src_power = {}
    for j, nm in enumerate(SRC):
        aucs = []
        for s in range(n_seeds):
            p = P_cal[s, :, j]
            if len(set(y.tolist())) < 2:
                continue
            from sklearn.metrics import roc_auc_score
            aucs.append(roc_auc_score(y, p))
        src_power[nm] = round(float(np.median(aucs)), 4) if aucs else None

    res = {"endpoint": ep, "n_te": int(len(y)), "n_cal": int(len(y_cal)),
           "costs": list(costs), "source_auc_calibrated": src_power,
           "C9": {}, "A1": {}, "A4": {}}

    # ================= C9：统一分数口径 =================
    curves, rows = [], []
    for s in range(n_seeds):
        Pw = P_cal[s][:, WEAK]
        mean_pc = Pw.mean(axis=1)
        mean_pc_cal = C_cal[s][:, WEAK].mean(axis=1)
        thr_m, thr_p = _thr_margin(mean_pc_cal, y_cal, costs)
        pred = (mean_pc >= 0.5).astype(int)
        score = SEL.unified_confidence(mean_pc)
        in_ad = ad >= AD_THRESHOLD
        spread = P_raw[s][:, WEAK].max(axis=1) - P_raw[s][:, WEAK].min(axis=1)
        masks = {
            "S1_naive_majority": np.ones(len(y), dtype=bool),
            "S2_ad_guard": in_ad,
            "S3_calibrated_conformal": score >= thr_m,
            "S4_full_admission": (score >= thr_m) & in_ad & (spread <= SPREAD_MAX),
        }
        curve = SEL.unified_risk_coverage(y, pred, score)
        curves.append(curve)
        for sname, m in masks.items():
            op = SEL.operating_point(y, pred, m, score)
            op.update(seed=s, strategy=sname,
                      utility=round(K.utility(y, pred, m, costs), 4),
                      thr_p=round(thr_p, 3), thr_margin=round(thr_m, 3))
            rows.append(op)
        # 统计"域外"的真实错误率，用于解释 gap 来源
        if in_ad.sum() and (~in_ad).sum():
            rows.append({"strategy": "_domain_diag", "seed": s,
                         "risk_in_ad": round(float(np.mean(pred[in_ad] != y[in_ad])), 4),
                         "risk_out_ad": round(float(np.mean(pred[~in_ad] != y[~in_ad])), 4),
                         "n_out": int((~in_ad).sum())})

    strat_rows = [r for r in rows if not r["strategy"].startswith("_")]
    summary = {}
    for sname in ("S1_naive_majority", "S2_ad_guard", "S3_calibrated_conformal",
                  "S4_full_admission"):
        sub = [r for r in strat_rows if r["strategy"] == sname]
        summary[sname] = {
            "coverage_median": round(float(np.median([r["coverage"] for r in sub])), 4),
            "risk_decided_median": round(float(np.median(
                [r["risk_decided"] for r in sub if r["risk_decided"] is not None])), 4)
            if any(r["risk_decided"] is not None for r in sub) else None,
            "frontier_risk_median": round(float(np.median(
                [r["frontier_risk_at_coverage"] for r in sub
                 if r["frontier_risk_at_coverage"] is not None])), 4),
            "efficiency_gap_median": round(float(np.median(
                [r["efficiency_gap"] for r in sub if r["efficiency_gap"] is not None])), 4)
            if any(r["efficiency_gap"] is not None for r in sub) else None,
            "efficiency_gap_ci95": _boot_ci(np.array(
                [r["efficiency_gap"] for r in sub if r["efficiency_gap"] is not None]))
            if any(r["efficiency_gap"] is not None for r in sub) else None,
            "utility_median": round(float(np.median([r["utility"] for r in sub])), 4),
            "n_seeds": len(sub),
        }
    diag = [r for r in rows if r["strategy"] == "_domain_diag"]
    res["C9"] = {
        "score_kind": "calibrated_absmargin",
        "note": ("统一 pred=(mean_pc≥0.5)、统一 score=|mean_pc−0.5|；"
                 "策略间只剩弃权规则不同。efficiency_gap>0 = 比同 coverage 的纯置信度弃权更差"),
        "summary": summary,
        "kurc_median": round(float(np.median([c["aurc"] for c in curves])), 4),
        "risk_out_of_domain_median": round(float(np.median(
            [d["risk_out_ad"] for d in diag])), 4) if diag else None,
        "risk_in_domain_median": round(float(np.median(
            [d["risk_in_ad"] for d in diag])), 4) if diag else None,
        "n_out_median": int(np.median([d["n_out"] for d in diag])) if diag else None,
        "sample_curve": curves[0]["curve"] if curves else [],
        "per_seed": strat_rows,
    }

    # ================= C6：误差方差分解（成因拆解的行为层代理） =================
    names3 = [SRC[i] for i in WEAK]
    c6 = {}
    for i in range(len(names3)):
        for j in range(i + 1, len(names3)):
            key = "%s|%s" % (names3[i], names3[j])
            tot, re_, sh = [], [], []
            for s in range(n_seeds):
                d = IND.decompose_error_variance(
                    P_cal[s][:, WEAK[i]], P_cal[s][:, WEAK[j]], y)
                if d["r_error"] is None:
                    continue
                tot.append(d["total_corr"])
                re_.append(d["r_error"])
                sh.append(d["shared_share"])
            if not re_:
                c6[key] = dict(verdict="undetermined")
                continue
            med_r = float(np.median(re_))
            c6[key] = {
                "total_corr_median": round(float(np.median(tot)), 4),
                "r_error_median": round(med_r, 4),
                "r_error_iqr": [round(float(np.percentile(re_, 25)), 4),
                                round(float(np.percentile(re_, 75)), 4)],
                "shared_share_median": round(float(np.median(sh)), 4),
                "verdict": ("shared_errors" if med_r >= 0.5 else
                            "independent_errors" if med_r <= 0.2 else "mixed"),
            }
    res["C6"] = {
        "pairs": c6,
        "note": ("share_signal+share_error=var_err_mean 恒等；判定只用 r_error；"
                 "这是行为层代理，不能区分共享数据与同源方法（TDATA 仍 pending）"),
    }

    # ================= A1：权重方案裁决 =================
    scheme_rows = {k: [] for k in W.SCHEMES}
    for s in range(n_seeds):
        Pc_cal, Pc_te = C_cal[s][:, WEAK], P_cal[s][:, WEAK]
        out = W.compare(Pc_cal, y_cal, Pc_te, y)
        for k, m in out.items():
            m2 = dict(m)
            m2["seed"] = s
            scheme_rows[k].append(m2)
    a1 = {}
    for k, sub in scheme_rows.items():
        a1[k] = {
            "log_loss_median": round(float(np.median([r["log_loss"] for r in sub])), 4),
            "brier_median": round(float(np.median([r["brier"] for r in sub])), 4),
            "auc_median": round(float(np.median([r["auc"] for r in sub])), 4)
            if all(r["auc"] is not None for r in sub) else None,
            "acc_median": round(float(np.median([r["acc_at_0.5"] for r in sub])), 4),
            "weights_median": [round(float(x), 4) for x in
                               np.median([r["weights"] for r in sub], axis=0)],
        }
    # 配对：每个方案 vs equal（同种子），看 log-loss 差
    base = {r["seed"]: r["log_loss"] for r in scheme_rows["equal"]}
    a1_paired = []
    for k, sub in scheme_rows.items():
        if k == "equal":
            continue
        d = np.array([r["log_loss"] - base[r["seed"]] for r in sub])
        lo, hi = _boot_ci(d)
        a1_paired.append({
            "compare": "%s - equal" % k, "delta_logloss_median": round(float(np.median(d)), 4),
            "boot_ci95": [lo, hi], "significant": bool(lo > 0 or hi < 0),
            "direction": "worse" if np.median(d) > 0 else "better"})
    res["A1"] = {"schemes": a1, "paired_vs_equal": a1_paired,
                 "note": ("bma 为 Dawid–Skene 源级似然代理（strict=False），"
                          "非严格模型边际似然；权重在 cal 上估、test 上评")}

    # ================= A4：基线强度外推 =================
    a4_rows = []
    for s in range(n_seeds):
        for tag, cols in (("weak3", WEAK), ("strong_swap", STRONG_SWAP)):
            Pw = P_cal[s][:, cols]
            mean_pc = Pw.mean(axis=1)
            mean_pc_cal = C_cal[s][:, cols].mean(axis=1)
            thr_m, _ = _thr_margin(mean_pc_cal, y_cal, costs)
            score = SEL.unified_confidence(mean_pc)
            pred = (mean_pc >= 0.5).astype(int)
            in_ad = ad >= AD_THRESHOLD
            spread = P_raw[s][:, cols].max(axis=1) - P_raw[s][:, cols].min(axis=1)
            m1 = np.ones(len(y), dtype=bool)
            m4 = (score >= thr_m) & in_ad & (spread <= SPREAD_MAX)
            a4_rows.append({"seed": s, "variant": tag, "strategy": "S1",
                            "utility": K.utility(y, pred, m1, costs),
                            "coverage": 1.0})
            a4_rows.append({"seed": s, "variant": tag, "strategy": "S4",
                            "utility": K.utility(y, pred, m4, costs),
                            "coverage": float(m4.mean())})
    a4 = {"per_variant": {}, "delta_S4_minus_S1": {}}
    for tag in ("weak3", "strong_swap"):
        u1 = {r["seed"]: r["utility"] for r in a4_rows
              if r["variant"] == tag and r["strategy"] == "S1"}
        u4 = {r["seed"]: r["utility"] for r in a4_rows
              if r["variant"] == tag and r["strategy"] == "S4"}
        cov4 = np.array([r["coverage"] for r in a4_rows
                         if r["variant"] == tag and r["strategy"] == "S4"])
        d = np.array([u4[k] - u1[k] for k in sorted(u1)])
        lo, hi = _boot_ci(d)
        a4["per_variant"][tag] = {
            "U_S1_median": round(float(np.median(list(u1.values()))), 4),
            "U_S4_median": round(float(np.median(list(u4.values()))), 4),
            "coverage_S4_median": round(float(np.median(cov4)), 4)}
        a4["delta_S4_minus_S1"][tag] = {
            "delta_median": round(float(np.median(d)), 4),
            "boot_ci95": [lo, hi], "significant": bool(lo > 0 or hi < 0),
            "direction": "better" if np.median(d) > 0 else "worse"}
    a4["flipped"] = bool(
        (a4["delta_S4_minus_S1"]["weak3"]["delta_median"] > 0)
        != (a4["delta_S4_minus_S1"]["strong_swap"]["delta_median"] > 0))
    res["A4"] = a4
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="out_blacklist")
    a = ap.parse_args()
    out = {"endpoints": {}}
    for fn in sorted(os.listdir(a.dir)):
        if not fn.startswith("export_") or not fn.endswith(".npz"):
            continue
        ep = fn[len("export_"):-len(".npz")]
        with np.load(os.path.join(a.dir, fn)) as z:
            print("[analysis] %s ..." % ep, flush=True)
            out["endpoints"][ep] = analyze_endpoint(ep, z)
    p = os.path.join(a.dir, "results.json")
    with io.open(p, "w", encoding="utf-8") as f:
        f.write(json.dumps(out, ensure_ascii=False, indent=2))
    print("[analysis] -> %s" % p)
    for ep, r in out["endpoints"].items():
        print("\n=== %s (n_te=%d) 单源校准AUC: %s"
              % (ep, r["n_te"],
                 ", ".join("%s=%.3f" % (k, v) for k, v in
                           r["source_auc_calibrated"].items() if v)))
        print("  [C9] 统一口径 AURC=%.4f  域内risk=%.3f 域外risk=%.3f"
              % (r["C9"]["kurc_median"], r["C9"]["risk_in_domain_median"] or -1,
                 r["C9"]["risk_out_of_domain_median"] or -1))
        for s, v in r["C9"]["summary"].items():
            print("    %-26s cov=%.3f risk=%s frontier=%s gap=%s %s"
                  % (s, v["coverage_median"], v["risk_decided_median"],
                     v["frontier_risk_median"], v["efficiency_gap_median"],
                     "" if not v["efficiency_gap_ci95"] else
                     "CI[%+.3f,%+.3f]" % v["efficiency_gap_ci95"]))
        print("  [A1] " + " | ".join("%s LL=%.4f" % (k, v["log_loss_median"])
                                     for k, v in r["A1"]["schemes"].items()))
        for d in r["A1"]["paired_vs_equal"]:
            print("       %-18s ΔLL=%+.4f CI[%+.4f,%+.4f] %s"
                  % (d["compare"], d["delta_logloss_median"], d["boot_ci95"][0],
                     d["boot_ci95"][1], "SIG" if d["significant"] else "ns"))
        print("  [A4] weak3 Δ=%+.4f %s | strong_swap Δ=%+.4f %s | flipped=%s"
              % (r["A4"]["delta_S4_minus_S1"]["weak3"]["delta_median"],
                 r["A4"]["delta_S4_minus_S1"]["weak3"]["boot_ci95"],
                 r["A4"]["delta_S4_minus_S1"]["strong_swap"]["delta_median"],
                 r["A4"]["delta_S4_minus_S1"]["strong_swap"]["boot_ci95"],
                 r["A4"]["flipped"]))


if __name__ == "__main__":
    main()
