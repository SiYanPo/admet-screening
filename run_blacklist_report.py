# -*- coding: utf-8 -*-
"""把 out_blacklist/results.json 渲染成 markdown 表（供 BLACKLIST_CLOSEOUT.md 引用）。

只做排版，不做任何数值加工：所有数字都来自 results.json，避免手工抄写出错。
"""
import argparse
import io
import json
import os


def _f(v, p="%.4f"):
    return "—" if v is None else (p % v)


def render(d):
    L = []
    eps = list(d.get("endpoints", {}).keys())
    L.append("### 表 1 · C9 统一分数口径（同 pred、同 score，只差弃权规则）\n")
    L.append("| 端点 | 策略 | coverage | risk_decided | 同覆盖率前沿 risk | efficiency_gap | 95%CI | utility |")
    L.append("|---|---|---|---|---|---|---|---|")
    for ep in eps:
        c9 = d["endpoints"][ep]["C9"]
        for s, v in c9["summary"].items():
            ci = v.get("efficiency_gap_ci95")
            L.append("| %s | %s | %.3f | %s | %s | %s | %s | %s |" % (
                ep, s, v["coverage_median"], _f(v["risk_decided_median"], "%.3f"),
                _f(v["frontier_risk_median"], "%.3f"),
                _f(v["efficiency_gap_median"], "%+.3f"),
                ("[%+.3f, %+.3f]" % (ci[0], ci[1])) if ci else "—",
                _f(v["utility_median"], "%.3f")))
    L.append("")
    L.append("统一口径 AURC（越低越好）与域内/域外错误率：\n")
    L.append("| 端点 | AURC | 域内 risk | 域外 risk | 域外样本数 |")
    L.append("|---|---|---|---|---|")
    for ep in eps:
        c9 = d["endpoints"][ep]["C9"]
        L.append("| %s | %.4f | %s | %s | %s |" % (
            ep, c9["kurc_median"], _f(c9["risk_in_domain_median"], "%.3f"),
            _f(c9["risk_out_of_domain_median"], "%.3f"),
            c9.get("n_out_median")))
    L.append("")

    L.append("### 表 2 · A1 四种权重方案（cal 上估权重，test 上打分）\n")
    L.append("| 端点 | 方案 | log-loss | Brier | AUC | acc@0.5 | 权重（中位数） |")
    L.append("|---|---|---|---|---|---|---|")
    for ep in eps:
        for k, v in d["endpoints"][ep]["A1"]["schemes"].items():
            L.append("| %s | %s | %.4f | %.4f | %s | %.4f | %s |" % (
                ep, k, v["log_loss_median"], v["brier_median"],
                _f(v["auc_median"], "%.4f"), v["acc_median"],
                "[" + ", ".join("%.3f" % x for x in v["weights_median"]) + "]"))
    L.append("")
    L.append("配对差（同种子，vs equal）：\n")
    L.append("| 端点 | 比较 | Δlog-loss | 95%CI | 显著 | 方向 |")
    L.append("|---|---|---|---|---|---|")
    for ep in eps:
        for p in d["endpoints"][ep]["A1"]["paired_vs_equal"]:
            L.append("| %s | %s | %+.5f | [%+.5f, %+.5f] | %s | %s |" % (
                ep, p["compare"], p["delta_logloss_median"],
                p["boot_ci95"][0], p["boot_ci95"][1],
                "是" if p["significant"] else "否", p["direction"]))
    L.append("")

    L.append("### 表 3 · A4 基线强度外推（只把最弱的 ridge 换成 HGB，其余不变）\n")
    L.append("| 端点 | 变体 | U(S1) | U(S4) | Δutility(S4−S1) | 95%CI | 显著 | 方向 |")
    L.append("|---|---|---|---|---|---|---|---|")
    for ep in eps:
        a4 = d["endpoints"][ep]["A4"]
        for tag in ("weak3", "strong_swap"):
            pv = a4["per_variant"][tag]
            dd = a4["delta_S4_minus_S1"][tag]
            L.append("| %s | %s | %.4f | %.4f | %+.4f | [%+.4f, %+.4f] | %s | %s |" % (
                ep, tag, pv["U_S1_median"], pv["U_S4_median"], dd["delta_median"],
                dd["boot_ci95"][0], dd["boot_ci95"][1],
                "是" if dd["significant"] else "否", dd["direction"]))
    L.append("")
    L.append("| 端点 | 结论翻转（weak3 与 strong_swap 方向相反） | 单源校准 AUC |")
    L.append("|---|---|---|")
    for ep in eps:
        r = d["endpoints"][ep]
        aucs = ", ".join("%s=%.3f" % (k, v) for k, v in
                         r["source_auc_calibrated"].items() if v is not None)
        L.append("| %s | %s | %s |" % (ep, "是" if r["A4"]["flipped"] else "否", aucs))
    L.append("")

    L.append("### 表 4 · C6 误差方差分解（成因的行为层代理）\n")
    L.append("| 端点 | 源对 | 总相关 corr(p_i,p_j) | 误差相关 r_e | 共享误差占比 | 判定 |")
    L.append("|---|---|---|---|---|---|")
    for ep in eps:
        c6 = d["endpoints"][ep].get("C6", {})
        for key, v in (c6.get("pairs") or {}).items():
            if v.get("verdict") == "undetermined":
                continue
            L.append("| %s | %s | %+.4f | %+.4f | %.3f | %s |" % (
                ep, key, v["total_corr_median"], v["r_error_median"],
                v["shared_share_median"], v["verdict"]))
    L.append("")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="out_blacklist")
    a = ap.parse_args()
    p = os.path.join(a.dir, "results.json")
    d = json.load(io.open(p, encoding="utf-8"))
    md = render(d)
    out = os.path.join(a.dir, "tables.md")
    with io.open(out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(md + "\n")
    print(md)
    print("\n[report] -> %s" % out)


if __name__ == "__main__":
    main()
