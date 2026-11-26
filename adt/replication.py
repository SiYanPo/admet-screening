# -*- coding: utf-8 -*-
"""R29 / R30：复现挑战包（replication challenge pack）。

### 评审原话（B6 / R3-3）

> "复现包若把中间产物一并给出，就退化成'把答案抄一遍'；容差若拍脑袋定，
> 要么宽到错误方法也能过，要么窄到诚实复现也过不了。"

### 本模块的两条硬约束

1. **只给三样东西**：指标定义（到公式）+ 容差 + 数据快照指纹。**不给**预测概率、
   每种子明细、中间产物。第二实现者必须自己把流程跑出来，而不是对齐我们的输出。
2. **容差由种子方差反推**：`tol = k × sd_seed`（缺省 k=2，≈覆盖 95% 的种子波动）。
   含义是"**同一方法换随机种子时会漂这么多**"，因此诚实复现必然落在容差内，
   而方法不对则会被显著不同的点估计暴露。
   - `sd_seed = 0`（确定性指标）时**不允许**把容差定为 0（否则等于要求逐位相等）：
     退化为 `TOL_FLOOR_ABS` 并置 `degenerate=True`，材料中须说明"该指标容差非
     由种子方差导出"。

### 反游戏化检查（R30 附带）

`score()` 除逐项判定外，还会检查"所有指标都落在容差 5% 以内"这种**过于完美**的提交，
标记 `suspicious_identical`——真正独立的实现不可能把噪声级波动也复现到 5% 精度，
出现该标记应先怀疑直接抄了 `expected.json`。
"""

from __future__ import annotations

import io
import json
import os

DEFAULT_SEED_K = 2.0
TOL_FLOOR_ABS = 1e-4
SUSPICION_FRAC = 0.05  # |Δ| < 5% 容差 → 疑似照抄
PACK_SCHEMA = "replication-pack/1"

METRIC_DEFS = {
    "utility": (
        "cost-weighted utility = −(1/N)·Σ cost_i，"
        "cost = c_abstain（弃权）/ c_false_PASS（真 FAIL 判 PASS）/ "
        "c_false_FAIL（真 PASS 判 FAIL）/ 0（判对）。y=1 表示 FAIL。"
    ),
    "coverage": "coverage = (给出 PASS/FAIL 的样本数) / N（弃权不进分子）",
    "risk_decided": "risk_decided = 在已判定样本中的错误率 = 错判数 / 已判定数",
    "auc": "AUC-ROC，以 FAIL=1 为正类，用该策略实际使用的分数（校准后概率或原始概率）",
    "delta_utility": "Δutility = utility(A) − utility(B)，逐种子配对后取中位数",
}


# ---------------------------------------------------------------- 统计量
def seed_stats(values):
    """n / mean / sd(样本, ddof=1) / median / iqr。空序列返回 n=0。"""
    v = sorted(float(x) for x in values)
    n = len(v)
    if n == 0:
        return dict(n_seeds=0, mean=None, sd=None, median=None, iqr=None)
    mean = sum(v) / n
    sd = 0.0
    if n > 1:
        sd = (sum((x - mean) ** 2 for x in v) / (n - 1)) ** 0.5
    if n % 2:
        med = v[n // 2]
    else:
        med = (v[n // 2 - 1] + v[n // 2]) / 2.0

    def _q(p):
        if n == 1:
            return v[0]
        pos = p * (n - 1)
        lo = int(pos)
        hi = min(lo + 1, n - 1)
        return v[lo] + (v[hi] - v[lo]) * (pos - lo)

    return dict(
        n_seeds=n,
        mean=round(mean, 6),
        sd=round(sd, 6),
        median=round(med, 6),
        iqr=[round(_q(0.25), 6), round(_q(0.75), 6)],
    )


def tolerance_from_seeds(values, k=DEFAULT_SEED_K):
    """R30：容差 = k × 种子标准差；sd=0 时退化为绝对值下限并显式标注。"""
    st = seed_stats(values)
    if st["n_seeds"] == 0:
        return dict(
            st,
            tol=None,
            k=k,
            degenerate=True,
            method="no_seeds",
            note="无种子数据，无法反推容差（不得默认给容差）",
        )
    tol = k * float(st["sd"] or 0.0)
    degenerate = tol <= 0.0
    if degenerate:
        tol = TOL_FLOOR_ABS
    st.update(
        tol=round(tol, 6),
        k=k,
        degenerate=bool(degenerate),
        method="k*sd_seed" if not degenerate else "floor(abs)",
        note=(
            (
                "该指标对随机种子完全确定（sd=0）：容差不能由种子方差反推，"
                "改用绝对值下限 %g；材料中须声明这一点" % TOL_FLOOR_ABS
            )
            if degenerate
            else "tol = %g × sd_seed（覆盖约 95%% 的种子波动）" % k
        ),
    )
    return st


# ---------------------------------------------------------------- 打包
def _w(path, text):
    d = os.path.dirname(os.path.abspath(path))
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)
    with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


_SCORE_PY = '''# -*- coding: utf-8 -*-
"""挑战包自评脚本（无第三方依赖）。用法：python score.py submission.json

判定规则与 adt/replication.score 一致：只有 expected.json 里 `counted=true`
的指标参与 all_pass；`counted=false` 的指标容差已接近量级，只打印 INFO。
"""
import io, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))


def main(sub_path):
    exp = json.load(io.open(os.path.join(HERE, "expected.json"), encoding="utf-8"))
    sub = json.load(io.open(sub_path, encoding="utf-8"))
    got = sub.get("metrics") or {}
    rows, n_pass, near, n_counted = [], 0, 0, 0
    for m in exp["metrics"]:
        counted = m.get("counted", True)
        n_counted += 1 if counted else 0
        raw = got.get(m["name"])
        val = raw.get("value") if isinstance(raw, dict) else raw
        if val is None:
            rows.append(dict(name=m["name"], status="MISSING" if counted else "INFO",
                             expected=m["value"], tol=m["tol"], got=None, delta=None,
                             counted=counted))
            continue
        delta = float(val) - float(m["value"])
        ok = abs(delta) <= float(m["tol"]) + 1e-12
        if counted:
            n_pass += 1 if ok else 0
            near += 1 if abs(delta) < 0.05 * float(m["tol"]) else 0
        rows.append(dict(name=m["name"],
                         status=("PASS" if ok else "FAIL") if counted else "INFO",
                         expected=m["value"], tol=m["tol"], got=float(val),
                         delta=round(delta, 6), counted=counted))
    total = n_counted
    # 2026-11-19：README 要求"交实现+环境指纹"，评分器必须真的查——否则文档与代码不一致
    env = sub.get("environment") or {}
    env_missing = [k for k in ("python", "rdkit", "numpy")
                   if not str(env.get(k) or "").strip()]
    impl = sub.get("implementation")
    if isinstance(impl, str):
        has_impl = bool(impl.strip())
    elif isinstance(impl, dict):
        files = impl.get("files")
        has_impl = bool(str(impl.get("code") or "").strip()
                        or str(impl.get("repo") or "").strip()
                        or (isinstance(files, list)
                            and [f for f in files if str(f or "").strip()])
                        or str(files or "").strip())
    else:
        has_impl = False
    prov_missing = ([] if has_impl else ["implementation"])
    prov_missing += ["environment." + k for k in env_missing]
    all_pass = (n_pass == total and total > 0)
    suspicious = bool(all_pass and near == total)
    verdict = ("pass_with_manual_review" if (all_pass and suspicious)
               else "pass" if all_pass else "fail")
    if all_pass and prov_missing:
        verdict = "numbers_only"
    out = dict(pack=exp.get("pack_id"), n_total=total, n_pass=n_pass,
               pass_rate=round(n_pass / float(total), 4) if total else 0.0,
               all_pass=all_pass, suspicious_identical=suspicious,
               verdict=verdict,
               verdict_note=("零偏差不等于造假：规范完全确定时零偏差是必然结果；"
                             "但也不等于独立复现成功——须人审实现代码后另行确认。"
                             "numbers_only = 数字对上但缺实现/环境指纹，不构成复现"),
               provenance=dict(implementation_present=has_impl,
                               environment_missing=env_missing,
                               missing=prov_missing,
                               complete=not prov_missing),
               rows=rows)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    if verdict in ("pass", "pass_with_manual_review"):
        return 0
    return 2 if verdict == "numbers_only" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "submission.json"))
'''


# 独立复现所必需的最小实验设置。缺任何一项，包就退化成"只能看数字、无法重跑"。
REQUIRED_SPEC = (
    "data",
    "sources",
    "calibration",
    "domain",
    "threshold_rule",
    "strategies",
    "utility",
    "seeds",
)

_SPEC_TITLES = {
    "data": "1. 数据与切分",
    "sources": "2. 预测源（逐一实现，不得替换）",
    "calibration": "3. 校准",
    "domain": "4. 适用域判据",
    "threshold_rule": "5. 阈值规则（在 calibration 上选，应用到 test）",
    "strategies": "6. 四个策略的精确定义",
    "utility": "7. 代价与效用",
    "seeds": "8. 随机种子",
    "environment": "9. 环境指纹",
    "n_seeds": None,
}


def _render_spec(spec):
    """把 spec 渲染成 README 里可照做的步骤（不是"见某脚本"）。"""
    out = []
    for k, v in (spec or {}).items():
        title = _SPEC_TITLES.get(k, k)
        if title is None:
            continue
        out += ["", "### %s" % title, ""]
        if isinstance(v, dict):
            for kk, vv in v.items():
                if isinstance(vv, dict):
                    out.append("- **%s**：" % kk)
                    for k3, v3 in vv.items():
                        out.append("  - `%s`: %s" % (k3, v3))
                elif isinstance(vv, list):
                    out.append("- **%s**：" % kk)
                    for it in vv:
                        if isinstance(it, dict):
                            out.append(
                                "  - "
                                + "；".join(
                                    "%s=%s"
                                    % (
                                        a,
                                        (
                                            json.dumps(b, ensure_ascii=False)
                                            if isinstance(b, (dict, list))
                                            else b
                                        ),
                                    )
                                    for a, b in it.items()
                                )
                            )
                        else:
                            out.append("  - %s" % it)
                else:
                    out.append("- **%s**：%s" % (kk, vv))
        elif isinstance(v, list):
            for it in v:
                if isinstance(it, dict):
                    out.append(
                        "- "
                        + "；".join(
                            "%s=%s"
                            % (
                                a,
                                (
                                    json.dumps(b, ensure_ascii=False)
                                    if isinstance(b, (dict, list))
                                    else b
                                ),
                            )
                            for a, b in it.items()
                        )
                    )
                else:
                    out.append("- %s" % it)
        else:
            out.append("- %s" % v)
    return out


def _pyrefs_of(text):
    """抽出文本里出现的 .py 文件名（用于检测"挑战包指向源码"的循环依赖）。"""
    import re as _re

    return sorted(set(_re.findall(r"[A-Za-z0-9_\-]+\.py\b", text or "")))


def build_pack(
    outdir, metrics, spec=None, snapshots=None, pack_id=None, strict_spec=False
):
    """写出挑战包。

    metrics: [dict(name, value, tol, kind, seed_sd, n_seeds, definition, note)]
    spec:    实验设置（数据源/切分/随机种子列表/命令），会原样写进 expected.json
    snapshots: [dict(snapshot_id, sha256, bytes, source)]（R01 快照指纹）
    """
    if not metrics:
        raise ValueError("metrics 不能为空：挑战包至少要有 1 个可比对的数字")
    # 反"循环依赖"闸门：spec 里不得出现 .py 文件名（score.py 除外）。
    # 理由：包内不提供实现代码。若 spec 写"切分见 run_keystone.py"，
    # 第二实现者只能去读原实现——那是照抄，不是独立复现。
    # （这条是 2026-10-31 自查发现的：旧 spec 正是这么写的，等于包不可独立执行。）
    _spec_txt = json.dumps(spec or {}, ensure_ascii=False)
    _pyrefs = [t for t in _pyrefs_of(_spec_txt) if t != "score.py"]
    if _pyrefs:
        raise ValueError(
            "spec 引用了实现脚本 %s：挑战包不提供该文件，第二实现者无法据此复现。"
            "请把实验设置写成可直接执行的描述（数据切分规则 / 模型与超参 / 校准方式 /"
            "域判据 / 阈值规则 / 代价），而不是指向源码。" % _pyrefs
        )
    spec_missing = [k for k in REQUIRED_SPEC if k not in (spec or {})]
    if strict_spec and spec_missing:
        raise ValueError(
            "spec 缺少独立复现所必需的字段 %s。缺任一项，第二实现者都必须去猜，"
            "猜错的包无法判别是方法错还是规范错。" % spec_missing
        )
    for m in metrics:
        if m.get("tol") is None:
            raise ValueError(
                "指标 %r 缺 tol：容差必须由种子方差反推，不得省略" % m.get("name")
            )
    pack_id = pack_id or ("pack-" + (os.path.basename(os.path.abspath(outdir)) or "x"))
    outdir = os.path.abspath(outdir)
    norm = []
    for m in metrics:
        item = dict(
            name=m["name"],
            value=m["value"],
            tol=m["tol"],
            kind=m.get("kind", "point"),
            seed_sd=m.get("seed_sd"),
            n_seeds=m.get("n_seeds"),
            definition=m.get("definition") or METRIC_DEFS.get(m.get("kind"), ""),
            note=m.get("note", ""),
        )
        # 容差若达到量级的一半，该指标就几乎无法区分"方法对"与"方法错"——
        # 诚实做法是把它降为参考项（INFO），不计入 all_pass，而不是假装它在把关。
        ratio = float(item["tol"]) / max(abs(float(item["value"])), 1e-9)
        item["tol_value_ratio"] = round(ratio, 4)
        item["weak_discrimination"] = bool(ratio >= 0.5)
        item["counted"] = not item["weak_discrimination"]
        if item["weak_discrimination"]:
            item["note"] = (
                item["note"] + "；⚠ 容差/量级=%.2f≥0.5，"
                "该指标判别力不足，仅作参考、不计入 all_pass" % ratio
            ).strip("；")
        norm.append(item)
    if not any(m["counted"] for m in norm):
        raise ValueError(
            "全部指标的容差都超过量级的一半：挑战包无法判别对错，"
            "请补更稳定的指标（更多种子 / 更确定的统计量）"
        )
    exp = dict(
        schema=PACK_SCHEMA,
        pack_id=pack_id,
        metrics=norm,
        n_counted=sum(1 for m in norm if m["counted"]),
        spec=spec or {},
        snapshots=snapshots or [],
        spec_complete=not spec_missing,
        spec_missing=spec_missing,
    )
    _w(
        os.path.join(outdir, "expected.json"),
        json.dumps(exp, ensure_ascii=False, indent=2) + "\n",
    )

    lines = [
        "# 复现挑战包 %s" % pack_id,
        "",
        "本包**只给**：指标定义（到公式）、容差、数据快照指纹、实验设置。",
        "本包**不给**：预测概率、每种子明细、任何中间产物——第二实现者必须自己跑出流程。",
        "**通过判据**：`counted=true` 的指标全部落在容差内（共 %d 项）；"
        "`counted=false` 的指标容差已接近其量级，判别力不足，只作参考、不参与判定。"
        % exp["n_counted"],
        "",
        "## 指标与容差（容差 = k × 种子标准差）",
        "",
        "| 指标 | 期望值 | 容差 | 种子 sd | n_seeds | 类型 | 计入判定 |",
        "|---|---|---|---|---|---|---|",
    ]
    for m in exp["metrics"]:
        lines.append(
            "| `%s` | %s | ±%s | %s | %s | %s | %s |"
            % (
                m["name"],
                m["value"],
                m["tol"],
                m["seed_sd"],
                m["n_seeds"],
                m["kind"],
                "是" if m["counted"] else "否（判别力不足）",
            )
        )
    lines += ["", "## 指标定义", ""]
    for m in exp["metrics"]:
        lines.append("- `%s`：%s" % (m["name"], m["definition"]))
        if m.get("note"):
            lines.append("  - 注：%s" % m["note"])
    if exp["snapshots"]:
        lines += [
            "",
            "## 数据快照（必须用同一快照，否则数字不可比）",
            "",
            "| source | snapshot_id | sha256 | bytes |",
            "|---|---|---|---|",
        ]
        for s in exp["snapshots"]:
            lines.append(
                "| %s | `%s` | `%s` | %s |"
                % (
                    s.get("source"),
                    s.get("snapshot_id"),
                    (s.get("sha256") or "")[:16],
                    s.get("bytes"),
                )
            )
    lines += ["", "## 实验设置（必须照此实现，不得替换组件）", ""]
    if not spec:
        lines += [
            "> ⚠ **本包未提供实验设置**：只能得到数字，无法独立复现。"
            "请把 spec 补全后重新出包。"
        ]
    else:
        if spec_missing:
            lines += [
                "> ⚠ **实验设置不完整**：缺 `%s`。缺项只能靠猜，"
                "猜错时无法区分是方法错还是规范错。" % "`, `".join(spec_missing),
                "",
            ]
        lines += _render_spec(spec)
    lines += [
        "",
        "## 怎么交",
        "",
        "1. 按 `SUBMISSION_TEMPLATE.json` 填 `metrics.<name>.value`（数字）。",
        "2. 填 `implementation`（code / repo / files 至少一项）与 `environment`"
        "（python / rdkit / numpy）——**只交数字不算复现**。",
        "3. 跑 `python score.py submission.json` 自评：`verdict=pass` 才算复现成功；"
        "`numbers_only` 表示数字对上了但缺实现/环境，退回补交。",
        "",
    ]
    _w(os.path.join(outdir, "README.md"), "\n".join(lines) + "\n")

    _w(os.path.join(outdir, "score.py"), _SCORE_PY)
    _w(
        os.path.join(outdir, "SUBMISSION_TEMPLATE.json"),
        json.dumps(
            dict(
                pack_id=pack_id,
                metrics={m["name"]: dict(value=None) for m in exp["metrics"]},
                implementation=dict(code=None, repo=None, files=[]),
                environment=dict(python=None, rdkit=None, numpy=None),
                submitted_by=None,
                submitted_at=None,
            ),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
    )
    return exp


_PROV_ENV_KEYS = ("python", "rdkit", "numpy")


def provenance(sub):
    """检查提交是否带"实现 + 环境指纹"（2026-11-19 修复文档与评分器不一致）。

    背景：README 写"只交数字不算复现"，但旧 `score()` 只比对数字，纯数字提交照样
    `verdict=pass`。这是**文档承诺与代码行为不一致**——比功能缺失更危险，因为
    外部审阅者会按 README 相信"已要求代码"，实际没有。

    判定（保守，不猜）：
      * implementation：接受 dict(code=/repo=/files=[...]) 或非空字符串；
      * environment：python / rdkit / numpy 三项都非空（缺项按缺失处理，不补默认值）。
    """
    sub = sub or {}
    env = sub.get("environment") or {}
    env_missing = [k for k in _PROV_ENV_KEYS if not str(env.get(k) or "").strip()]
    impl = sub.get("implementation")
    if isinstance(impl, str):
        has_impl = bool(impl.strip())
    elif isinstance(impl, dict):
        files = impl.get("files")
        has_impl = bool(
            str(impl.get("code") or "").strip()
            or str(impl.get("repo") or "").strip()
            or (isinstance(files, list) and [f for f in files if str(f or "").strip()])
            or str(files or "").strip()
        )
    else:
        has_impl = False
    missing = [] if has_impl else ["implementation"]
    missing += ["environment." + k for k in env_missing]
    return {
        "implementation_present": has_impl,
        "environment_present": not env_missing,
        "environment_missing": env_missing,
        "missing": missing,
        "complete": has_impl and not env_missing,
    }


def score(pack_dir, submission):
    """按 expected.json 判定提交是否复现成功；含反游戏化检查。

    submission 可以是路径，也可以是已解析的 dict。
    """
    exp = json.load(io.open(os.path.join(pack_dir, "expected.json"), encoding="utf-8"))
    sub = submission
    if isinstance(submission, str):
        sub = json.load(io.open(submission, encoding="utf-8"))
    got = (sub or {}).get("metrics") or {}
    rows, n_pass, near, n_counted = [], 0, 0, 0
    for m in exp["metrics"]:
        counted = m.get("counted", True)
        n_counted += 1 if counted else 0
        raw = got.get(m["name"])
        val = raw.get("value") if isinstance(raw, dict) else raw
        if val is None:
            rows.append(
                dict(
                    name=m["name"],
                    status="MISSING" if counted else "INFO",
                    expected=m["value"],
                    tol=m["tol"],
                    got=None,
                    delta=None,
                    counted=counted,
                )
            )
            continue
        delta = float(val) - float(m["value"])
        ok = abs(delta) <= float(m["tol"]) + 1e-12
        if counted:
            n_pass += 1 if ok else 0
            near += 1 if abs(delta) < SUSPICION_FRAC * float(m["tol"]) else 0
        rows.append(
            dict(
                name=m["name"],
                status=("PASS" if ok else "FAIL") if counted else "INFO",
                expected=m["value"],
                tol=m["tol"],
                got=float(val),
                delta=round(delta, 6),
                counted=counted,
            )
        )
    total = n_counted
    all_pass = n_pass == total and total > 0
    suspicious = bool(all_pass and near == total)
    prov = provenance(sub)
    verdict = (
        "pass_with_manual_review"
        if (all_pass and suspicious)
        else "pass" if all_pass else "fail"
    )
    # 2026-11-19：数字全过但没有实现/环境指纹 → 不是复现，只是抄到了数字
    if all_pass and not prov["complete"]:
        verdict = "numbers_only"
    # 2026-10-31 实测发现：本框架自己的第二实现在 6/6 PASS 的同时触发了
    # suspicious_identical（delta 全为 0）。原因是规范已把每个超参、阈值、判定规则
    # 都写死，同一数据 + 同一种子 + 确定性算法 → 数值必然一致。
    # 也就是说：「数值差异小」不能区分「照抄答案」与「规范完全确定」。
    # 因此本检查只能标记**需人工核查**，不得据此判定造假，也不得据此判定复现成功。
    note = {
        "pass": "通过：全部 counted 指标落在容差内，且未触发照抄嫌疑",
        "pass_with_manual_review": (
            "通过数值判定，但所有 counted 指标几乎零偏差 → 触发照抄嫌疑。"
            "注意：当规范已完全确定（同一数据/种子/算法）时，零偏差是**必然结果**，"
            "不能据此判定造假。必须提交实现代码与环境指纹由人审，"
            "在核查完成前不得对外宣称「已被独立复现」。"
        ),
        "numbers_only": (
            "数字全部落在容差内，但提交缺实现代码或环境指纹 → **不构成复现**。"
            "规范完全确定时抄到数字是必然结果，不能据此声称「已被独立复现」。"
        ),
        "fail": "未通过：至少一个 counted 指标超出容差",
    }[verdict]
    return dict(
        pack=exp.get("pack_id"),
        n_total=total,
        n_counted=total,
        n_pass=n_pass,
        pass_rate=round(n_pass / float(total), 4) if total else 0.0,
        all_pass=all_pass,
        suspicious_identical=suspicious,
        verdict=verdict,
        verdict_note=note,
        provenance=prov,
        rows=rows,
    )
