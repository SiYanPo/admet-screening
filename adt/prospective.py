# -*- coding: utf-8 -*-
"""工作包 G：**时间留出（temporal holdout）裁决** —— 不是前瞻盲测。

2026-11-04 / C08 + v1.md R-B：原称 "prospective adjudication" 违反仓库自身
`TEMPORAL_HOLDOUT_DISCIPLINE.md:16/26/60` 的唯一判据（设计评测方案的人在
设计时是否已知道测试数据存在）。OpenADMET-ExpansionRx 官方固定 test split
是**数据集设计时切分**，作者在写评测方案时已知其存在与编号范围，故属
**temporal holdout / retrospective external validation**，不得写「前瞻」。
v4.0 标签授予条件 ② 仍**未满足**：需要 T0 冻结 SAP 之后才产生/解封的新数据，
且由未接触该批数据者执行（见 references/TIME_ARROW.md、SAP_FROZEN.yaml）。

用词纪律（机器强制）：`design_type=temporal_holdout`、
`not_preregistered=true`；任何产物禁止出现 prospective/blind 类措辞
（禁用词表见 TEMPORAL_HOLDOUT_DISCIPLINE.md，`cmd_prospect.meta.wording_ban` 落盘）。

（以下为原始背景说明，保留供审计）

### 为什么这次能真做（2026-10-30 核实）

此前 v3.4/v3.5 都写成"协议已给、缺早期-晚期配对"。核实后发现**不需要额外配对数据**：
OpenADMET-ExpansionRx 的 train/test split **本身就是时序切分**。官方文档两处明确：

> "This data has been obtained during late-stage optimization and has **time-ordering
> information** — IDs in the 'Molecule name' column reflect **measurement order**."
> "ExpansionRx-OpenADMET challenge provides **time (chronological) split**, based on the
> experiment order during late-stage ADMET optimization. 70/30 train/test split."

本机实测（`expansion_data_train.csv` / `_test.csv`）：
train 编号 **1321–20100**（5,326 分子），test 编号 **20101–27239**（2,282 分子），
**零重叠、test 全部大于 train**。即 test = 晚期分子，train = 早期证据。

所以本模块做的是官方设计的原始任务：**只用早期数据训练的模型，去裁决晚期分子**。

### 与"benchmark"的区别（评审 G 的核心批评）

`benchmark` 报的是 AUROC/AUPRC（模型排序能力）；本模块报的是**决策后果**：
- **PASS 组实测失败率**：裁决为 PASS 的分子×端点里，实测其实 FAIL 的比例
  —— 这是"你敢不敢据此推进"的直接数字；
- **FAIL 组虚警率**：裁决为 FAIL 但实测 PASS 的比例（决定会不会错杀）；
- coverage / decided_accuracy / UNDETERMINED 占比。

### 诚实边界

1. 本模块的"源"是**模型预测**（如两个 Ridge 基线），不是真实 web 服务；
   它检验的是"准入层在时序外推场景下的决策后果"，不是某商业服务的性能。
2. PASS 组失败率是**条件于已裁决**的量：coverage 低时它天然好看，必须与 coverage 同时报。
3. 未做早期内部的模拟前瞻（那需要再切一刀并重训）；本模块只用官方时序 split，
   不额外造数据。
"""

import csv
import io
import os


def _f(v):
    try:
        x = float(v)
        return x if x == x and abs(x) != float("inf") else None
    except (TypeError, ValueError):
        return None


def load_truth(path):
    """truth.csv -> {(cid, ep): 'PASS'|'FAIL'}（只保留可判两态）。"""
    out = {}
    if not path or not os.path.exists(path):
        return out
    with io.open(path, encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            cls = (r.get("truth_class") or "").strip().upper()
            if cls in ("PASS", "FAIL"):
                out[(r.get("compound_id", ""), r.get("endpoint", ""))] = cls
    return out


def summarize(verdicts, truth, label="admission"):
    """verdicts: {(cid,ep): (verdict, score)}；truth: {(cid,ep): 'PASS'|'FAIL'}。

    返回决策后果指标（PASS 组失败率 / FAIL 组虚警率 / coverage / accuracy）。
    """
    n = 0
    n_dec = 0
    n_ok = 0
    n_pass = n_pass_bad = 0
    n_fail = n_fail_bad = 0
    n_und = 0
    per_ep = {}
    for key, cls in truth.items():
        if key not in verdicts:
            continue
        v = (verdicts[key][0] or "").upper()
        n += 1
        d = per_ep.setdefault(
            key[1],
            dict(
                n=0, n_decided=0, n_ok=0, n_pass=0, n_pass_bad=0, n_fail=0, n_fail_bad=0
            ),
        )
        d["n"] += 1
        if v == "UNDETERMINED":
            n_und += 1
            continue
        if v not in ("PASS", "FAIL"):
            n_und += 1
            continue
        n_dec += 1
        d["n_decided"] += 1
        ok = v == cls
        n_ok += 1 if ok else 0
        d["n_ok"] += 1 if ok else 0
        if v == "PASS":
            n_pass += 1
            d["n_pass"] += 1
            if cls == "FAIL":
                n_pass_bad += 1
                d["n_pass_bad"] += 1
        else:
            n_fail += 1
            d["n_fail"] += 1
            if cls == "PASS":
                n_fail_bad += 1
                d["n_fail_bad"] += 1

    rows = []
    for ep, d in sorted(per_ep.items()):
        rows.append(
            dict(
                endpoint=ep,
                n=d["n"],
                n_decided=d["n_decided"],
                coverage=round(d["n_decided"] / float(d["n"]), 4) if d["n"] else None,
                decided_accuracy=(
                    round(d["n_ok"] / float(d["n_decided"]), 4)
                    if d["n_decided"]
                    else None
                ),
                pass_n=d["n_pass"],
                pass_failure_rate=(
                    round(d["n_pass_bad"] / float(d["n_pass"]), 4)
                    if d["n_pass"]
                    else None
                ),
                fail_n=d["n_fail"],
                fail_false_alarm_rate=(
                    round(d["n_fail_bad"] / float(d["n_fail"]), 4)
                    if d["n_fail"]
                    else None
                ),
            )
        )

    overall = dict(
        label=label,
        n_pairs=n,
        n_decided=n_dec,
        n_undetermined=n_und,
        coverage=round(n_dec / float(n), 4) if n else None,
        decided_accuracy=round(n_ok / float(n_dec), 4) if n_dec else None,
        pass_n=n_pass,
        pass_failure_rate=round(n_pass_bad / float(n_pass), 4) if n_pass else None,
        fail_n=n_fail,
        fail_false_alarm_rate=round(n_fail_bad / float(n_fail), 4) if n_fail else None,
    )
    return dict(overall=overall, per_endpoint=rows)


def write(outdir, results, meta):
    """results: [(label, summary_dict)]；meta: dict（数据来源/时序说明）。"""
    os.makedirs(outdir, exist_ok=True)
    p1 = os.path.join(outdir, "prospective_summary.csv")
    cols = [
        "label",
        "n_pairs",
        "n_decided",
        "n_undetermined",
        "coverage",
        "decided_accuracy",
        "pass_n",
        "pass_failure_rate",
        "fail_n",
        "fail_false_alarm_rate",
    ]
    with io.open(p1, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for _, s in results:
            w.writerow(s["overall"])
    p2 = os.path.join(outdir, "prospective_by_endpoint.csv")
    cols2 = [
        "label",
        "endpoint",
        "n",
        "n_decided",
        "coverage",
        "decided_accuracy",
        "pass_n",
        "pass_failure_rate",
        "fail_n",
        "fail_false_alarm_rate",
    ]
    with io.open(p2, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols2, extrasaction="ignore")
        w.writeheader()
        for label, s in results:
            for r in s["per_endpoint"]:
                row = dict(r)
                row["label"] = label
                w.writerow(row)
    p3 = os.path.join(outdir, "prospective_note.md")
    L = [
        "# 时间留出（temporal holdout）裁决（工作包 G）",
        "",
        "> 非预注册前瞻：官方固定 test split 是数据集设计时的切分，"
        "设计评测方案时已知其存在。见 TEMPORAL_HOLDOUT_DISCIPLINE.md。",
        "",
    ]
    for k, v in meta.items():
        L.append("- %s: %s" % (k, v))
    L += [
        "",
        "| 策略 | coverage | decided_acc | PASS 组失败率 | FAIL 组虚警率 |",
        "|---|---|---|---|---|",
    ]
    for label, s in results:
        o = s["overall"]
        L.append(
            "| %s | %s | %s | %s | %s |"
            % (
                label,
                o["coverage"],
                o["decided_accuracy"],
                o["pass_failure_rate"],
                o["fail_false_alarm_rate"],
            )
        )
    L += [
        "",
        "**怎么读**",
        "",
        "- PASS 组失败率 = 裁决为 PASS 的分子×端点中实测 FAIL 的比例（越低越好，",
        "  但必须与 coverage 同看：coverage 低时它天然好看）。",
        "- FAIL 组虚警率 = 裁决为 FAIL 但实测 PASS 的比例（决定会不会错杀）。",
        '- 本表的"源"是模型预测而非真实 web 服务；检验的是准入层在**时序外推**下的',
        "  决策后果，不是商业服务性能。",
    ]
    with io.open(p3, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    return p1, p2, p3


def run(
    measurements,
    truth,
    rules=None,
    groups=None,
    chemical_class="",
    baseline_policy=None,
    outdir="",
    meta=None,
):
    """执行前瞻裁决：主策略=完整准入层；可选对照=无准入多数投票。"""
    from . import reliability as REL

    recs = REL.evaluate(
        measurements or [], rules=rules or {}, source_groups=groups or {}
    )
    verdicts = {
        (r.get("compound_id", ""), r.get("endpoint", "")): (
            (r.get("verdict") or "").upper(),
            0.0,
        )
        for r in recs
    }
    results = [("admission_layer", summarize(verdicts, truth, "admission_layer"))]
    if baseline_policy in ("majority", "both"):
        from . import ablation as AB

        bv = AB.policy_all_sources(measurements, rules=rules)
        results.append(
            ("no_admission_majority", summarize(bv, truth, "no_admission_majority"))
        )
    if baseline_policy in ("unit_guard", "both"):
        from . import ablation as AB

        uv = AB.policy_unit_guard(measurements, rules=rules)
        results.append(("unit_guard_only", summarize(uv, truth, "unit_guard_only")))
    meta = dict(meta or {})
    meta.setdefault("n_measurements", len(measurements or []))
    meta.setdefault("n_truth", len(truth or {}))
    meta.setdefault("chemical_class", chemical_class or "(none)")
    if outdir:
        write(outdir, results, meta)
    return dict(results=results, meta=meta, recs=recs)


def paired_mcnemar(
    verdicts_a,
    verdicts_b,
    truth,
    endpoint=None,
    a_name="A",
    b_name="B",
    set_name=None,
    alternative="two-sided",
    alpha=0.05,
):
    """P4 / R09：配对 McNemar 检验——**检验对象必须写死，不许含糊**。

    评审 R1-4 原话："McNemar 检验对象不明确——哪两个分类器？在哪个集合上？
    单侧还是双侧？"本函数把这三件事全部变成显式字段，并回写在返回值里。

    对象定义（缺一不可）
    --------------------
    · **分类器 A**：`a_name`。本框架约定：A = **含准入层的决策流**（域检查 → 可弃权），
      B = `b_name` = **无准入层/强制给判定的决策流**。两策略须能对同一
      (compound, endpoint) 各给出 PASS/FAIL；任一侧是 ABSTAIN 则**不入配对**。
    · **配对单元**：`(compound_id, endpoint)` 的一次判定。**不是**分子层面汇总，
      也**不是**端点层面汇总（后者会丢掉配对结构）。
    · **评价集合**：`set_name`（如 "external_test_v3"）。必须同一分子集、同一 truth 版本、
      同一数据快照；calibration split 一律不得混入（否则配对/可交换性假设不成立）。
    · **单/双侧**：`alternative ∈ {two-sided, greater, less}`。缺省 `two-sided`；
      **任何单侧都必须先在 prereg 里写死方向**，事后按结果挑方向即 p-hacking（红线 R34）。
    · **效应量**：`delta_acc_a_minus_b = (b − c) / n_paired`，正 = A 更准。只报 p 不报 Δ
      不构成"更好"的证据（大样本下微小 Δ 也能显著）。

    2×2 配对表
    ----------
    |            | B 正确 | B 错误 |
    | A 正确     | n11    | b      |
    | A 错误     | c      | n00    |

    精确检验：H0 下不一致对数 b+c 服从 Binomial(b+c, 0.5)。
    b+c == 0 时 p 记 1.0（这是"**无差异证据**"，**不等于"两策略等价"**），
    并置 `test_informative=False`——想主张等价必须另做 TOST（见 `adt/mmp.py`）。

    返回字段：object(a/b/set/unit/alternative/alpha)、n_paired、n_discordant、b、c、
              n_both_correct、n_both_wrong、delta_acc_a_minus_b、mcnemar_p、p_two_sided、
              significant、test_informative、definition、note。
    """
    from scipy import stats as _stats

    b = c = 0
    n11 = n00 = n_paired = 0
    for k in sorted(truth):
        if endpoint and k[1] != endpoint:
            continue
        va, vb = verdicts_a.get(k), verdicts_b.get(k)
        if not va or not vb:
            continue
        # 弃权 / 无判定：不进配对（分母必须与"配对"的定义一致，否则 Δ 不可解释）
        if str(va[0]).upper() not in ("PASS", "FAIL"):
            continue
        if str(vb[0]).upper() not in ("PASS", "FAIL"):
            continue
        ta = str(truth[k]).upper()
        ok_a = 1 if str(va[0]).upper() == ta else 0
        ok_b = 1 if str(vb[0]).upper() == ta else 0
        n_paired += 1
        if ok_a and ok_b:
            n11 += 1
        elif ok_a and not ok_b:
            b += 1
        elif not ok_a and ok_b:
            c += 1
        else:
            n00 += 1

    obj = dict(
        a=a_name,
        b=b_name,
        set=set_name or "(unspecified)",
        unit="(compound_id, endpoint)",
        alternative=alternative,
        alpha=float(alpha),
    )
    definition = (
        "配对单元=(compound,endpoint)；A=%s（含准入层，可弃权）；B=%s（无准入层，强制判定）；"
        "正确性=verdict==truth；ABSTAIN 不入配对；集合=%s；检验=%s α=%s"
        % (a_name, b_name, obj["set"], alternative, alpha)
    )

    if n_paired == 0:
        return dict(
            object=obj,
            n_paired=0,
            n_discordant=0,
            b=0,
            c=0,
            n_both_correct=0,
            n_both_wrong=0,
            delta_acc_a_minus_b=None,
            mcnemar_p=None,
            p_two_sided=None,
            significant=False,
            test_informative=False,
            definition=definition,
            note="无可配对单元（两策略须在同一集合上各有 PASS/FAIL，且 truth 已知）",
        )

    n_disc = b + c
    delta = (b - c) / float(n_paired)  # A − B，正 = A 更准

    def _p(side):
        if n_disc == 0:
            return 1.0
        m = min(b, c)
        try:
            return float(
                _stats.binomtest(n_disc - m, n_disc, 0.5, alternative=side).pvalue
            )
        except Exception:  # scipy < 1.7 兜底
            if side == "two-sided":
                return min(1.0, 2.0 * float(_stats.binom.cdf(m, n_disc, 0.5)))
            if side == "greater":
                return float(_stats.binom.sf(m - 1, n_disc, 0.5))
            return float(_stats.binom.cdf(m, n_disc, 0.5))

    p_two = _p("two-sided")
    p_used = p_two if alternative == "two-sided" else _p(alternative)
    return dict(
        object=obj,
        n_paired=n_paired,
        n_discordant=n_disc,
        b=b,
        c=c,
        n_both_correct=n11,
        n_both_wrong=n00,
        delta_acc_a_minus_b=round(delta, 4),
        diff_rate=round(delta, 4),  # 旧键保留（同义）；新代码请用 delta_acc_a_minus_b
        mcnemar_p=round(p_used, 6),
        p_two_sided=round(p_two, 6),
        significant=bool(p_used < alpha),
        test_informative=bool(n_disc > 0),
        definition=definition,
        note=(
            "配对 McNemar[%s vs %s | %s | %s]：n_paired=%d，不一致 %d（b=%d A对B错，"
            "c=%d A错B对），Δacc(A−B)=%+.4f，p=%s%s"
            % (
                a_name,
                b_name,
                obj["set"],
                alternative,
                n_paired,
                n_disc,
                b,
                c,
                delta,
                round(p_used, 4),
                "（无不一致对：只说明无差异证据，不等于等价）" if n_disc == 0 else "",
            )
        ),
    )
