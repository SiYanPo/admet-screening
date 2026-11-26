# -*- coding: utf-8 -*-
"""方向A：准入层消融实验（把"准入先于组合"从架构主张变成组件级贡献）。

外部评审（2026-10-30 第三次核对）的原话：
  "论文的核心主张是'准入先于组合'，这要求你证明准入层本身有独立贡献，而不是
   '整个框架作为一个黑箱产生了合理输出'。"

本模块在**同一批多源长表 + 同一真值**上定义四个条件：
  (a) all_sources_majority        不做任何准入，全部源直接多数投票
  (b) unit_guard_only             只做单位可投射守卫 + 类别投射；不做域外 block、不做独立性分组
  (c) full_admission              完整准入层：域外 block + 独立方法组票数 + 源间分歧守卫
  (d) admission_plus_conformal    (c) + 保形区间宽度作为辅助弃权（宽→弃权）

对每个条件报告：coverage / decided_accuracy / minority_class_error_rate；
并在**同 coverage**（各条件按自身置信分数降序截到与 (c) 相同覆盖数）下再比一次，
回答"87.9% 是孤立数字还是真胜出"（工作包 D 的缺口）。

诚实边界（必须随产物一起报告）：
  1. 多源若由"1 个实测源 + N 个模型基线"组成，条件 (a)(b) 会因实测源而在真值上
     虚高——这是"实测源已经进场"的场景，不是"多源预测裁决"场景。产物必须写
     `panel_mix`。
  2. 若在真实基线预测上再**受控注入**域外/单位异构/版本漂移（`--corrupt`），
     产物标 `panel=controlled_corruption`，结论只能读作"准入规则对已知失效的
     拦截能力"，不能读作真实 web 服务的绝对性能。
  3. (d) 需要 `--conformal`（含 width 列）；缺失时如实写 `skipped`，不臆造。
  4. PASS/FAIL 阈值是分析选择（见 external_rules.yaml 的 threshold_source），
     不是监管阈值。
"""

import csv
import io
import os
import random

IN_DOMAIN = {"predicted", "measured", "saturated"}
UNIT_PROB = {"probability", "fraction"}
UNIT_CLASS = {"class", "class_0_1", "binary"}
# 注意："risk_score" 只接受**0–1 归一分**。external.write_baseline 产出的
# `*_risk.csv` 里 value 是"方向对齐后的原始量"（shape=up 时为 −v，可到 −54），
# **不是** 0–1 分数——不能直接喂给本模块（否则 0.5 阈值与 phys_range 双双误判）。
# 正确做法：传原始预测（measurements_baseline_*.csv）+ `--rules`，由规则判 PASS/FAIL。
PROJ_UNITS = UNIT_PROB | UNIT_CLASS | {"risk_score"}


def _f(v):
    try:
        x = float(v)
        return x if x == x and abs(x) != float("inf") else None
    except (TypeError, ValueError):
        return None


def _class_of(row, naive=False, rules=None):
    """把一行投影成 0(PASS/阴性) / 1(FAIL/阳性)；不可投射返回 None。

    投影顺序：
      1) 单位本身已是 class/probability（或 0–1 risk_score）→ 0.5 阈值；
      2) naive=True → **忽略单位**、直接按 0.5 切两半（条件 (a)"不做任何准入"的真实行为，
         会把 logD=2.5、CLint=56 之类原样当概率投票）；
      3) 给了 rules（且单位是真实量纲）→ 用端点 pass/fail 阈值判定（正确口径）。
    """
    v = _f(row.get("value"))
    if v is None:
        return None
    u = (row.get("unit") or "").strip().lower()
    if u in PROJ_UNITS:
        return 1 if v >= 0.5 else 0
    if naive:
        return 1 if v >= 0.5 else 0
    if rules:
        try:
            from .reliability import _judge, _match_rule

            rule = _match_rule(row.get("endpoint", ""), rules) or {}
            vd = _judge(v, rule)
            if vd == "FAIL":
                return 1
            if vd == "PASS":
                return 0
        except Exception:  # pragma: no cover
            return None
    return None


def load_panel(specs):
    """specs: [(path, source_label, source_group)] -> list[dict]（长表行）。"""
    rows = []
    for path, label, group in specs:
        with io.open(path, encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                rr = dict(r)
                rr["source"] = label
                rr["_group"] = group or label
                rows.append(rr)
    return rows


def load_truth(path):
    """truth.csv -> {(cid, ep): 'PASS'|'FAIL'}（只保留可判两态）。"""
    out = {}
    with io.open(path, encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            cls = (r.get("truth_class") or "").strip().upper()
            if cls in ("PASS", "FAIL"):
                out[(r.get("compound_id", ""), r.get("endpoint", ""))] = cls
    return out


def _votes(rows, naive=False, rules=None):
    """按 (cid, ep) 聚合，返回 {(cid,ep): [(class, score, row)]}。"""
    g = {}
    for r in rows:
        c = _class_of(r, naive=naive, rules=rules)
        if c is None:
            continue
        key = (r.get("compound_id", ""), r.get("endpoint", ""))
        g.setdefault(key, []).append((c, _f(r.get("value")) or 0.0, r))
    return g


def _majority(vals):
    n1 = sum(1 for c, _, _ in vals if c == 1)
    n0 = len(vals) - n1
    if n1 == n0:
        return "UNDETERMINED", 0.0
    margin = abs(n1 - n0) / float(len(vals))
    return ("FAIL" if n1 > n0 else "PASS"), margin


# ---------------------------------------------------------------- 四个条件
def policy_all_sources(rows, min_n=1, rules=None, naive=True, **kw):
    """(a) 全源多数投票，无任何准入（默认忽略单位，naive）。"""
    out = {}
    for key, vals in _votes(rows, naive=naive, rules=rules).items():
        if len(vals) < min_n:
            out[key] = ("UNDETERMINED", 0.0)
            continue
        v, m = _majority(vals)
        out[key] = (v, m)
    return out


def policy_unit_guard(rows, min_n=1, rules=None, **kw):
    """(b) 单位守卫：只保留**可投射**的行（naive=False；真实量纲走 rules），其余同 (a)。"""
    kept = [r for r in rows if _class_of(r, naive=False, rules=rules) is not None]
    return policy_all_sources(kept, min_n=min_n, rules=rules, naive=False)


def policy_admission(rows, min_groups=2, spread_max=0.30, min_n=1, rules=None, **kw):
    """(c) 完整准入：域外 block + 独立方法组 + 源间分歧守卫。"""
    in_dom = [r for r in rows if (r.get("domain_flag") or "") in IN_DOMAIN]
    out = {}
    # 先把所有出现过的键填成 UNDETERMINED，保证与 (a)(b) 键集一致
    all_keys = set(_votes(rows, rules=rules).keys())
    for key in all_keys:
        out[key] = ("UNDETERMINED", 0.0)
    for key, vals in _votes(in_dom, rules=rules).items():
        if len(vals) < min_n:
            continue
        # 每个独立组一票（组内先多数）
        by_group = {}
        for c, s, r in vals:
            by_group.setdefault(r.get("_group") or r.get("source"), []).append(c)
        group_votes = []
        for _, cs in by_group.items():
            n1 = sum(cs)
            group_votes.append(
                1 if n1 * 2 > len(cs) else (0 if n1 * 2 < len(cs) else None)
            )
        group_votes = [v for v in group_votes if v is not None]
        if len(group_votes) < min_groups:
            continue  # 独立方法组不够 → 弃权
        n1 = sum(group_votes)
        n0 = len(group_votes) - n1
        if n1 == n0:
            continue  # 组间平票 → 弃权
        scores = [s for _, s, _ in vals]
        if scores and (max(scores) - min(scores)) > spread_max:
            continue  # 源间分歧过大 → 弃权
        out[key] = (
            "FAIL" if n1 > n0 else "PASS",
            abs(n1 - n0) / float(len(group_votes)),
        )
    return out


def policy_admission_plus_conformal(
    rows, conformal=None, width_q=None, rules=None, **kw
):
    """(d) (c) + 保形宽度辅助弃权。conformal: {(cid,ep): width}。"""
    base = policy_admission(rows, rules=rules, **kw)
    if not conformal or width_q is None:
        return base, "skipped(no_conformal)"
    out = dict(base)
    for key, val in list(out.items()):
        if val[0] == "UNDETERMINED":
            continue
        w = conformal.get(key)
        if w is not None and w > width_q:
            out[key] = ("UNDETERMINED", 0.0)
    return out, "applied"


# ---------------------------------------------------------------- 评估
def _quantile(vals, q):
    if not vals:
        return None
    s = sorted(vals)
    i = min(len(s) - 1, max(0, int(round(q * (len(s) - 1)))))
    return s[i]


def load_conformal(path):
    """读 conformal.csv（含 compound_id/endpoint/width），返回 ({key: width}, q90)。"""
    if not path or not os.path.exists(path):
        return {}, None
    wmap = {}
    with io.open(path, encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            w = _f(r.get("width"))
            if w is not None:
                wmap[(r.get("compound_id", ""), r.get("endpoint", ""))] = w
    return wmap, _quantile(list(wmap.values()), 0.90)


def evaluate(verdicts, truth):
    """返回 per_endpoint + overall 指标。"""
    per = {}
    for key, cls in truth.items():
        if key not in verdicts:
            continue
        v = verdicts[key][0]
        d = per.setdefault(
            key[1],
            dict(n=0, n_decided=0, n_correct=0, n_pos=0, n_neg=0, pos_err=0, neg_err=0),
        )
        d["n"] += 1
        d["n_pos" if cls == "FAIL" else "n_neg"] += 1
        if v in ("PASS", "FAIL"):
            d["n_decided"] += 1
            ok = v == cls
            d["n_correct"] += 1 if ok else 0
            if not ok:
                d["pos_err" if cls == "FAIL" else "neg_err"] += 1
    rows = []
    for ep, d in sorted(per.items()):
        minority = "FAIL" if d["n_pos"] <= d["n_neg"] else "PASS"
        m_n = d["n_pos"] if minority == "FAIL" else d["n_neg"]
        m_err = d["pos_err"] if minority == "FAIL" else d["neg_err"]
        rows.append(
            dict(
                endpoint=ep,
                n=d["n"],
                n_decided=d["n_decided"],
                coverage=round(d["n_decided"] / float(d["n"]), 4) if d["n"] else None,
                decided_accuracy=(
                    round(d["n_correct"] / float(d["n_decided"]), 4)
                    if d["n_decided"]
                    else None
                ),
                minority_class=minority,
                minority_n=m_n,
                minority_error_rate=round(m_err / float(m_n), 4) if m_n else None,
            )
        )
    tot = dict(n=sum(r["n"] for r in rows), n_decided=sum(r["n_decided"] for r in rows))
    tot["coverage"] = round(tot["n_decided"] / float(tot["n"]), 4) if tot["n"] else None
    corr = sum(d["n_correct"] for d in per.values())
    tot["decided_accuracy"] = (
        round(corr / float(tot["n_decided"]), 4) if tot["n_decided"] else None
    )
    err = sum(d["pos_err"] + d["neg_err"] for d in per.values())
    tot["overall_error_rate"] = (
        round(err / float(tot["n_decided"]), 4) if tot["n_decided"] else None
    )
    return dict(per_endpoint=rows, overall=tot)


def matched_coverage(verdicts, truth, target_n):
    """把某条件按自身置信分数降序截到 target_n 个已裁决，算准确率。"""
    decided = []
    for key, cls in truth.items():
        if key not in verdicts:
            continue
        v, s = verdicts[key]
        if v in ("PASS", "FAIL"):
            decided.append((s, 1 if v == cls else 0))
    decided.sort(key=lambda t: -t[0])
    take = decided[: max(0, target_n)]
    if not take:
        return dict(n=0, accuracy=None)
    return dict(
        n=len(take), accuracy=round(sum(t[1] for t in take) / float(len(take)), 4)
    )


# ---------------------------------------------------------------- 受控失效注入
def corrupt(rows, mode="domain", frac=0.30, seed=42):
    """在真实预测上受控注入一种已知失效（用于隔离准入规则的作用）。

    mode:
      domain   —— 随机 frac 的行 domain_flag 改成 out_of_domain（模拟某源在本化学类无资格）
      unit     —— 随机 frac 的行 unit 改成 'class'（0/1 口径），其余保留 risk_score（单位异构）
      version  —— 随机 frac 的行 source_version 改成 'v0-legacy'（版本漂移）
      pseudo   —— 复制一个源，换 source 名但保留同一 _group（伪独立 → 假共识）
    """
    rnd = random.Random(seed)
    out = []
    for r in rows:
        rr = dict(r)
        if rnd.random() < frac:
            if mode == "domain":
                rr["domain_flag"] = "out_of_domain"
            elif mode == "unit":
                rr["unit"] = "class"
                v = _f(rr.get("value"))
                rr["value"] = round(1.0 if (v is not None and v >= 0.5) else 0.0, 6)
            elif mode == "version":
                rr["source_version"] = "v0-legacy"
        out.append(rr)
    if mode == "pseudo":
        for r in rows:
            rr = dict(r)
            rr["source"] = (r.get("source") or "") + "_mirror"
            rr["source_version"] = (r.get("source_version") or "") + "-mirror"
            out.append(rr)
    return out


# ---------------------------------------------------------------- 写盘
def _write_csv(path, cols, rows):
    with io.open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def run(panel_rows, truth, panel_meta, conformal_path="", outdir="", rules=None):
    """执行四条件消融并写盘。返回 summary dict。"""
    wmap, wq = load_conformal(conformal_path)
    v_a = policy_all_sources(panel_rows, rules=rules)
    v_b = policy_unit_guard(panel_rows, rules=rules)
    v_c = policy_admission(panel_rows, rules=rules)
    v_d, d_status = policy_admission_plus_conformal(
        panel_rows, conformal=wmap, width_q=wq, rules=rules
    )

    conds = [
        ("a_all_sources", v_a),
        ("b_unit_guard", v_b),
        ("c_full_admission", v_c),
        ("d_admission_conformal", v_d),
    ]
    by_ep_rows, summary_rows = [], []
    for name, vv in conds:
        ev = evaluate(vv, truth)
        for r in ev["per_endpoint"]:
            r = dict(r)
            r["condition"] = name
            by_ep_rows.append(r)
        s = dict(condition=name, **ev["overall"])
        summary_rows.append(s)

    # 同 coverage 比较（以 (c) 的已裁决数为基准）
    n_c = evaluate(v_c, truth)["overall"]["n_decided"]
    matched = []
    for name, vv in conds:
        m = matched_coverage(vv, truth, n_c)
        matched.append(
            dict(
                condition=name,
                matched_n=m["n"],
                matched_accuracy=m["accuracy"],
                target_n=n_c,
            )
        )

    # 判定
    acc = {s["condition"]: s["decided_accuracy"] for s in summary_rows}
    cov = {s["condition"]: s["coverage"] for s in summary_rows}
    verdict = []
    if acc.get("c_full_admission") is not None:
        for base in ("a_all_sources", "b_unit_guard"):
            if acc.get(base) is not None and acc["c_full_admission"] > acc[base]:
                verdict.append(
                    "(c) 优于 %s（decided_accuracy %.4f > %.4f）"
                    % (base, acc["c_full_admission"], acc[base])
                )
            elif acc.get(base) is not None:
                verdict.append(
                    "⚠ (c) 未优于 %s（%.4f <= %.4f）——这是可定位的过度拦截失效，"
                    "须检查域外 block / 独立性分组在该端点是否误伤"
                    % (base, acc["c_full_admission"], acc[base])
                )
    macc = {m["condition"]: m["matched_accuracy"] for m in matched}
    if (
        macc.get("c_full_admission") is not None
        and macc.get("b_unit_guard") is not None
    ):
        verdict.append(
            "同 coverage(%d) 下 (c)=%.4f vs (b)=%.4f"
            % (n_c, macc["c_full_admission"], macc["b_unit_guard"])
        )

    if outdir:
        os.makedirs(outdir, exist_ok=True)
        _write_csv(
            os.path.join(outdir, "ablation_by_endpoint.csv"),
            [
                "condition",
                "endpoint",
                "n",
                "n_decided",
                "coverage",
                "decided_accuracy",
                "minority_class",
                "minority_n",
                "minority_error_rate",
            ],
            by_ep_rows,
        )
        _write_csv(
            os.path.join(outdir, "ablation_summary.csv"),
            [
                "condition",
                "n",
                "n_decided",
                "coverage",
                "decided_accuracy",
                "overall_error_rate",
            ],
            summary_rows,
        )
        _write_csv(
            os.path.join(outdir, "ablation_matched_coverage.csv"),
            ["condition", "target_n", "matched_n", "matched_accuracy"],
            matched,
        )
        lines = [
            "# 准入层消融（方向A / 工作包 D 缺口）",
            "",
            "panel_mix: %s" % panel_meta.get("panel_mix", ""),
            "panel: %s" % panel_meta.get("panel", ""),
            "n_truth_pairs: %d" % len(truth),
            "conformal: %s" % d_status,
            "",
        ]
        lines.append("| 条件 | coverage | decided_accuracy | 同coverage准确率 |")
        lines.append("|---|---|---|---|")
        for s in summary_rows:
            lines.append(
                "| %s | %s | %s | %s |"
                % (
                    s["condition"],
                    s["coverage"],
                    s["decided_accuracy"],
                    {m["condition"]: m["matched_accuracy"] for m in matched}.get(
                        s["condition"]
                    ),
                )
            )
        lines.append("")
        lines.append("**判定**")
        for v in verdict:
            lines.append("- " + v)
        if not verdict:
            lines.append("- 数据不足以判定（检查 truth 覆盖）")
        with io.open(
            os.path.join(outdir, "ablation_summary.md"), "w", encoding="utf-8"
        ) as fh:
            fh.write("\n".join(lines) + "\n")

    return dict(
        summary=summary_rows,
        matched=matched,
        verdict=verdict,
        conformal_status=d_status,
        panel_meta=panel_meta,
    )


# ---------------------------------------------------------------------------
# 同行评审 §4 分歧 1：源级 admission 是否独立贡献——可证伪对比卡（B3）
# ---------------------------------------------------------------------------
def source_admission_falsifiability_card(result):
    """把 ablate 结果转成"源级 vs 样本级"的可证伪卡（不是架构图箭头）。

    报告 §4 分歧 1 的评审意见："可作贡献，但必须给'源级 vs 样本级'可证伪对比，
    而不是架构图箭头。" 四条件消融提供这个对比：
      - b_unit_guard = 样本级（只按单位/数值是否已判弃权）
      - c_full_admission = 源级（整源在某化学类是否有准入资格）
    判据必须同时看 decided_accuracy 与同 coverage 下的 matched_accuracy——
    否则"增益"可能只是覆盖下降的假象（报告 §7 实跑明确点出这点）。
    返回 falsifiable=bool + 具体数据；不满足最小证据则 evidence='insufficient'。
    """
    summary = {r.get("condition"): r for r in result.get("summary", [])}
    matched = {r.get("condition"): r for r in result.get("matched", [])}
    b, c = summary.get("b_unit_guard"), summary.get("c_full_admission")
    mb, mc = matched.get("b_unit_guard"), matched.get("c_full_admission")
    card = {
        "sample_level": "b_unit_guard",
        "source_level": "c_full_admission",
        "sample_decided_accuracy": (b or {}).get("decided_accuracy"),
        "source_decided_accuracy": (c or {}).get("decided_accuracy"),
        "sample_coverage": (b or {}).get("coverage"),
        "source_coverage": (c or {}).get("coverage"),
        "sample_matched_accuracy": (mb or {}).get("matched_accuracy"),
        "source_matched_accuracy": (mc or {}).get("matched_accuracy"),
    }
    if not (b and c and mb and mc):
        card.update(
            falsifiable=False,
            evidence="insufficient",
            note="缺少 b/c 条件或同覆盖对比，无法判定源级独立贡献",
        )
        return card
    raw_gain = (c["decided_accuracy"] or 0) - (b["decided_accuracy"] or 0)
    matched_gain = (mc["matched_accuracy"] or 0) - (mb["matched_accuracy"] or 0)
    card["raw_gain"] = round(raw_gain, 4)
    card["matched_coverage_gain"] = round(matched_gain, 4)
    # 可证伪：同覆盖下源级不劣于样本级即支持"有独立贡献"；差则明确记为反证
    supported = matched_gain > 0
    card["falsifiable"] = True
    card["evidence"] = (
        "supported" if supported else "refuted_by_same_coverage_comparison"
    )
    card["note"] = (
        "同覆盖(n=%s)下源级 %.4f vs 样本级 %.4f；%s。原始 decided_accuracy 增益 %.4f "
        "不可单独作为证据（可能来自覆盖下降）。"
        % (
            mc.get("target_n"),
            mc.get("matched_accuracy"),
            mb.get("matched_accuracy"),
            "支持源级独立贡献" if supported else "源级未优于样本级，独立贡献主张被证伪",
            raw_gain,
        )
    )
    return card
