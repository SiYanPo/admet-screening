# -*- coding: utf-8 -*-
"""P2.4-d：门判别力三端点的多重比较台账。

**为什么需要这个脚本**

材料里有一句话："门在某些端点上有效。"一旦用了"某些"，检验就不再是单次检验，
而是"3 次里挑最好的一次报出来"——标准的 multiple comparisons。
只报 DILI 的 Fisher p=0.0267 而不说另外两次也测了，等于把"3 次机会"当"1 次机会"卖。
审稿人（尤其统计审稿人）第一刀就砍这里。

本脚本做三件事：

1. **Holm–Bonferroni 校正**：把三端点的 Fisher p 当同一族，给校正后 p。
2. **Bonferroni 校正区间**：把差值 CI 的置信水平从 95% 提到 1-0.05/3=98.3%，
   看"域外更差"这条在族错误率受控后是否仍站得住。
3. **如实区分两种叙事**：
   - 若主张是"**DILI 这个端点**上门有据"（端点已预先指定、单独一篇的具体问题）
     → 单次检验口径，不需要校正；
   - 若主张是"**门在多个端点上**有用/无用"（跨端点归纳）
     → 必须校正，且校正后很可能什么都不剩。

**这个脚本不替作者选叙事**，只把两套数并列摆出来。选哪套是科学判断，但必须写清楚。

用法：
    python run_gate_multiplicity.py
    python run_gate_multiplicity.py --alpha 0.05 --out out_ext/tdc/gate_multiplicity.json
"""
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ENDPOINTS = [
    ("hERG", "out_ext/tdc/gate_audit.json"),
    ("DILI", "out_ext/tdc/gate_audit_DILI.json"),
    ("BBB_Martins", "out_ext/tdc/gate_audit_BBB_Martins.json"),
]


def _load(path):
    if not os.path.exists(path):
        return None
    with io.open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _counts(forced):
    """从 acc/n 还原 2x2 计数。落盘时只存了比例，这里按四舍五入还原并回报误差。"""
    n_out, n_in = forced["n_out"], forced["n_in"]
    a_out, a_in = forced["acc_out_of_domain"], forced["acc_in_domain"]
    k_out = int(round(a_out * n_out))
    k_in = int(round(a_in * n_in))
    # 还原误差：若比例是 3 位小数，n=406 时最大误差 0.0005*406≈0.2 人
    err = max(abs(k_out / float(n_out) - a_out), abs(k_in / float(n_in) - a_in))
    return k_out, n_out, k_in, n_in, err


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--alpha", type=float, default=0.05)
    ap.add_argument("--out", default="out_ext/tdc/gate_multiplicity.json")
    a = ap.parse_args(argv)

    from adt.stats_ci import holm, newcombe_diff_ci

    rows, ps, missing = [], [], []
    for ep, path in ENDPOINTS:
        d = _load(path)
        if d is None:
            missing.append(ep)
            continue
        forced = d["forced_prediction_accuracy"]
        power = d["gate_power"]
        k_out, n_out, k_in, n_in, err = _counts(forced)
        ps.append(forced.get("fisher_p"))
        rows.append(dict(endpoint=ep, n_test=d.get("n_test"),
                         auc=power.get("auc"), auc_ci=power.get("auc_ci"),
                         verdict_ci=power.get("verdict_ci"),
                         k_out=k_out, n_out=n_out, k_in=k_in, n_in=n_in,
                         acc_out=forced.get("acc_out_of_domain"),
                         acc_in=forced.get("acc_in_domain"),
                         fisher_p=forced.get("fisher_p"),
                         count_reconstruction_error=round(err, 6)))

    if not rows:
        print("没有可读的 gate_audit 产物，先跑 run_gate_audit.py")
        return 1

    h = holm(ps, alpha=a.alpha)
    adj_by_ep = {}
    for it in h["family"]:
        adj_by_ep[rows[it["idx"]]["endpoint"]] = it

    m = len(rows)
    alpha_adj = a.alpha / m
    for r in rows:
        k_out, n_out, k_in, n_in = (r["k_out"], r["n_out"], r["k_in"], r["n_in"])
        r["diff_ci_95"] = newcombe_diff_ci(k_out, n_out, k_in, n_in, alpha=a.alpha)
        r["diff_ci_familywise"] = newcombe_diff_ci(k_out, n_out, k_in, n_in,
                                                   alpha=alpha_adj)
        r["diff_ci_familywise"]["level"] = round(1 - alpha_adj, 6)
        it = adj_by_ep.get(r["endpoint"])
        r["p_holm"] = it["adj"] if it else None
        r["reject_holm"] = it["reject"] if it else False

        ci95_excludes_0 = (r["diff_ci_95"]["lo"] is not None
                           and (r["diff_ci_95"]["lo"] > 0 or r["diff_ci_95"]["hi"] < 0))
        cifw_excludes_0 = (r["diff_ci_familywise"]["lo"] is not None
                           and (r["diff_ci_familywise"]["lo"] > 0
                                or r["diff_ci_familywise"]["hi"] < 0))
        r["claim_ok_single"] = bool(ci95_excludes_0)
        r["claim_ok_family"] = bool(cifw_excludes_0)

    payload = dict(
        alpha=a.alpha, m=m, missing=missing,
        familywise_alpha=round(alpha_adj, 6),
        holm=h,
        rows=rows,
        interpretation=(
            "**两套口径必须分开写，且必须声明用的是哪一套。**\n"
            "① 单端点口径（端点事先指定、只对这一个端点下结论）：用 95%%CI / 原始 p；\n"
            "② 跨端点口径（说\"门在某些端点上有效/无效\"）：必须用 Holm 校正后的 p 与\n"
            "   %0.1f%% CI，否则就是在 3 次机会里挑最好的一次报。\n"
            "本族 m=%d，familywise alpha=%.4f。"
            % (100 * (1 - alpha_adj), m, alpha_adj)),
        caveat=("计数由 acc×n 四舍五入还原（产物只存比例），"
                "还原误差已逐行记录在 count_reconstruction_error；"
                "若要严格复算，请从 gate_scores_*.csv 逐分子重算，不要用还原值。"),
    )

    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with io.open(a.out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)

    print("端点           n   AUC[95%CI]              Fisher p  Holm p   差值 95%CI            是否排除0（95% / 族内）")
    for r in rows:
        ci = r["auc_ci"] or {}
        print("%-13s %4s  %.3f [%.3f, %.3f]  %8.4f  %7s  %+.3f [%+.3f, %+.3f]   %s"
              % (r["endpoint"], r["n_test"],
                 r["auc"] or 0, ci.get("lo") or 0, ci.get("hi") or 0,
                 r["fisher_p"] if r["fisher_p"] is not None else -1,
                 ("%.4f" % r["p_holm"]) if r["p_holm"] is not None else "—",
                 r["diff_ci_95"]["diff"], r["diff_ci_95"]["lo"], r["diff_ci_95"]["hi"],
                 "95%%:%s / 族:%s" % ("是" if r["claim_ok_single"] else "否",
                                     "是" if r["claim_ok_family"] else "否")))
    print("")
    print(h["sentence"])
    if missing:
        print("缺产物（未参与校正）：%s" % ", ".join(missing))
    print("-> %s" % a.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
