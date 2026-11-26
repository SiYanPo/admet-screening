# -*- coding: utf-8 -*-
"""监管治理评估层（v3.0.0）：QAF 四原则 + 三层适用域 + 偏倚风险。

三层文献锚点
------------
1. **OECD (Q)SAR Assessment Framework**（Series on Testing and Assessment No.386,
   2023, DOI: 10.1787/d96118f6-en）提出**预测四原则**：
     ① 输入定义正确（端点、算法、单位明确）
     ② 物质在适用域内
     ③ 预测可靠（拟合/验证/不确定度）
     ④ 结果适配监管目的（fit for purpose）
   并且专门给出**多预测合并**的评估清单——这正是本 skill `reliability` 的
   依赖分组与 `tier` 的结论封顶在做的事，此前只是"工程约定"，现在有官方对照。

2. **Hanser et al. 2016**（SAR QSAR Environ Res 27:865-881, DOI:
   10.1080/1062936X.2016.1250229）把适用域拆成**模型级 / 预测级 / 决策级**
   三个子域，分别回答"模型可信吗 / 这条预测可信吗 / 能否用于此决策"。
   本 skill 的三层恰好同构：`coverage`（模型级）→ `reliability`（预测级）→
   `tier`（决策级）。本模块把这种对应关系显式输出，而不是留在文档里。

3. **PROBAST**（Wolff et al. Ann Intern Med 2019;170:51-58, DOI:
   10.7326/M18-1376）的四域偏倚风险评估（参与者/预测因子/结局/分析），
   用来给整批证据打一个 `risk_of_bias`，并与 `tier` 联动：
   **高风险不得升 T3**（发表级结论要求偏倚风险低/中）。

设计纪律：所有判定只输出 `satisfied / partial / not_met / not_assessable`
与**证据指针**，不输出"合规"字样——是否合规由监管方判定，不由本工具自封。
"""

QAF_PRINCIPLES = [
    (
        "P1",
        "端点与算法定义明确",
        "被测端点、单位、判定阈值、源版本是否可追溯（QAF Principle 1 / Assessment Element 1）",
    ),
    (
        "P2",
        "物质在适用域内",
        "是否给出适用域判定，并把域外预测显式标出而非当作阴性（Principle 2）",
    ),
    (
        "P3",
        "预测可靠（拟合与验证）",
        "是否有独立真值验证、判别力与校准、以及不确定度陈述（Principle 3）",
    ),
    (
        "P4",
        "适配监管目的（fit for purpose）",
        "证据档位是否与声称的用途匹配（Principle 4）",
    ),
]

_STATUS_ORDER = {"not_assessable": 0, "not_met": 1, "partial": 2, "satisfied": 3}
_SEV = {"low": 0, "medium": 1, "high": 2}


def _worse(a, b):
    """取**更严重**的档位（偏倚风险：high > medium > low）。"""
    return a if _SEV.get(a, 0) >= _SEV.get(b, 0) else b


# ---------------------------------------------------------------------------
# 1) 三层适用域（Hanser 2016）
# ---------------------------------------------------------------------------
def ad_levels(reliability_rows, coverage_rows=None, tier_row=None):
    """输出三层 AD 表：model / prediction / decision。

    每行 dict(level, scope, id, status, value, evidence, note)。
    """
    out = []

    # --- 模型级：每个源在本批的可用端点比例 ---
    for src, d in sorted(_by_source(coverage_rows or {}).items()):
        n_ep = d["n_endpoints"]
        usable = d["n_usable"]
        rate = usable / n_ep if n_ep else 0.0
        if n_ep and usable == 0:
            status, note = "out_of_domain", "该源在本批所有端点均无可判值"
        elif rate < 0.30:
            status, note = "limited", "整源覆盖率 %.2f<0.30（G6：降为背景）" % rate
        else:
            status, note = "in_domain", "整源覆盖 %.2f" % rate
        out.append(
            dict(
                level="model",
                scope="source",
                id=src,
                status=status,
                value=round(rate, 3),
                evidence="coverage_matrix %d 端点" % n_ep,
                note=note,
            )
        )

    # --- 预测级：每个分子的可判 / 未判比例 ---
    per = {}
    for r in reliability_rows or []:
        cid = r.get("compound_id")
        d = per.setdefault(cid, dict(dec=0, und=0, pt=0))
        v = r.get("verdict")
        if v in ("PASS", "FAIL"):
            d["dec"] += 1
        elif v == "UNDETERMINED":
            d["und"] += 1
        elif v == "PASSTHRU":
            d["pt"] += 1
    for cid in sorted(per):
        d = per[cid]
        tot = d["dec"] + d["und"]
        rate = d["dec"] / tot if tot else 0.0
        if d["dec"] == 0:
            status = "out_of_domain"
        elif d["und"] > d["dec"]:
            status = "limited"
        else:
            status = "in_domain"
        out.append(
            dict(
                level="prediction",
                scope="compound",
                id=cid,
                status=status,
                value=round(rate, 3),
                evidence="可判 %d / 未判 %d / 参照 %d" % (d["dec"], d["und"], d["pt"]),
                note=(
                    "本分子无任何可判端点"
                    if d["dec"] == 0
                    else (
                        "未判多于可判：结论只能逐条看，不能汇总"
                        if d["und"] > d["dec"]
                        else ""
                    )
                ),
            )
        )

    # --- 决策级：整批证据档位 ---
    if tier_row:
        tier = tier_row.get("tier", "")
        maxc = tier_row.get("max_conclusion", "")
        status = {"T1": "not_met", "T2": "partial", "T3": "satisfied"}.get(
            tier, "not_assessable"
        )
        out.append(
            dict(
                level="decision",
                scope="project",
                id=tier or "-",
                status=status,
                value=tier or "",
                evidence="tier=%s → max_conclusion=%s" % (tier, maxc),
                note=(
                    "仅支持探索性表述"
                    if tier == "T1"
                    else (
                        "支持项目决策，不支持论文结论"
                        if tier == "T2"
                        else "支持发表级结论" if tier == "T3" else ""
                    )
                ),
            )
        )
    return out


def command_execution_binding(ledger, required_commands, *, claimed_tier=None):
    """同行评审 §5 输出缺口：证据等级必须与"命令是否真的执行"机器绑定。

    ledger: [{command, status}]，status ∈ ok | refused | skip | not_run | error。
    required_commands: 支撑某证据等级所必须跑过的命令名列表。
    只有 status=ok 才算"已执行"；REFUSED/SKIP/NOT_RUN/ERROR 一律不计入覆盖，
    更不得被写成证据。claimed_tier 非空时，若绑定不成立则给出拒绝裁定。

    返回 dict(executed/refused/skipped/missing/refused_or_skipped_not_coverage, bound, verdict)。
    """
    status_by_cmd = {}
    for r in ledger or []:
        cmd = r.get("command")
        st = (r.get("status") or "not_run").lower()
        # 同一命令多次执行：ok 优先（有一次成功即算执行过，但要保留失败记录）
        if cmd not in status_by_cmd or st == "ok":
            status_by_cmd[cmd] = st
    executed = [c for c in required_commands if status_by_cmd.get(c) == "ok"]
    refused = [c for c in required_commands if status_by_cmd.get(c) == "refused"]
    skipped = [
        c
        for c in required_commands
        if status_by_cmd.get(c) in ("skip", "not_run", "error")
    ]
    missing = [c for c in required_commands if c not in status_by_cmd]
    not_coverage = refused + skipped + missing
    bound = not not_coverage  # 所有必需命令都 ok
    verdict = "BOUND"
    if not bound:
        verdict = "UNBOUND"
        if claimed_tier in ("T2", "T3"):
            verdict = "REFUSED"  # 高证据等级不得建立在未执行/弃权命令上
    return dict(
        executed=executed,
        refused=refused,
        skipped=skipped,
        missing=missing,
        refused_or_skipped_not_coverage=not_coverage,
        bound=bound,
        verdict=verdict,
        note=(
            "必需命令全部实际执行，可支撑所声明等级"
            if bound
            else "以下必需命令未实际执行(%s)，不得计入覆盖或写成证据；"
            "claimed_tier=%s → %s"
            % (",".join(not_coverage), claimed_tier or "-", verdict)
        ),
    )


def _by_source(coverage_rows):
    agg = {}
    for r in coverage_rows:
        src = r.get("source", "")
        d = agg.setdefault(src, dict(n_endpoints=0, n_usable=0, n_zero=0))
        d["n_endpoints"] += 1
        if r.get("flag") == "usable":
            d["n_usable"] += 1
        if r.get("flag") == "no_prediction":
            d["n_zero"] += 1
    return agg


# ---------------------------------------------------------------------------
# 2) QAF 四原则逐条评估（OECD 2023）
# ---------------------------------------------------------------------------
def qaf_assess(
    n_endpoints=0,
    n_endpoints_with_unit=0,
    n_sources=0,
    n_sources_versioned=0,
    coverage_rows=None,
    reliability_rows=None,
    benchmark_rows=None,
    tier="T1",
    manifest_present=False,
    calibration_reported=False,
):
    """返回 [{principle, title, status, evidence, gap}]。"""
    rows = []

    # ---- P1 端点与算法定义 ----
    ev, gaps = [], []
    if n_endpoints <= 0:
        status = "not_assessable"
        ev.append("未加载端点规则表")
    else:
        if n_endpoints_with_unit >= n_endpoints:
            ev.append(
                "端点规则 %d 条全部声明单位（endpoints.unit_for 单一真源）"
                % n_endpoints
            )
        else:
            gaps.append(
                "%d/%d 个端点缺单位声明"
                % (n_endpoints - n_endpoints_with_unit, n_endpoints)
            )
        if n_sources and n_sources_versioned >= n_sources:
            ev.append("%d 个源全部登记版本号" % n_sources)
        elif n_sources:
            gaps.append(
                "%d/%d 个源缺版本号（无法复核预测来自哪一代模型）"
                % (n_sources - n_sources_versioned, n_sources)
            )
        if manifest_present:
            ev.append("run_manifest 已记录输入哈希（判据可追溯）")
        else:
            gaps.append("缺 run_manifest：阈值改动后无法证明结论出自哪版判据")
        status = "satisfied" if not gaps else "partial"
    rows.append(
        dict(
            principle="P1",
            title=QAF_PRINCIPLES[0][1],
            status=status,
            evidence="；".join(ev) or "-",
            gap="；".join(gaps) or "-",
        )
    )

    # ---- P2 适用域 ----
    ev, gaps = [], []
    if not coverage_rows:
        status = "not_met"
        gaps.append("未生成覆盖矩阵（无法说明哪些 源×端点 有可判值）")
    else:
        zero = sum(1 for r in coverage_rows if r.get("flag") == "no_prediction")
        ood = sum(
            1
            for r in coverage_rows
            if r.get("flag") in ("no_prediction", "insufficient_coverage")
        )
        ev.append(
            "覆盖矩阵 %d 个 源×端点；全零端点组合 %d 个" % (len(coverage_rows), zero)
        )
        und = sum(
            1 for r in (reliability_rows or []) if r.get("verdict") == "UNDETERMINED"
        )
        if und:
            ev.append("%d 个 分子×端点 判 UNDETERMINED（域外/单组均不投票）" % und)
        if ood and not und:
            gaps.append("存在覆盖不足组合但无 UNDETERMINED 记录：域外可能被当成阴性")
        status = "satisfied" if ev and not gaps else "partial"
    rows.append(
        dict(
            principle="P2",
            title=QAF_PRINCIPLES[1][1],
            status=status,
            evidence="；".join(ev) or "-",
            gap="；".join(gaps) or "-",
        )
    )

    # ---- P3 可靠性 ----
    ev, gaps = [], []
    bm = benchmark_rows or []
    real = [
        r
        for r in bm
        if r.get("auroc") not in ("", None) and "DEMO" not in (r.get("note") or "")
    ]
    demo = [r for r in bm if "DEMO" in (r.get("note") or "")]
    if demo and not real:
        ev.append("仅有 DEMO 基准（合成真值，不可作验证）")
        gaps.append("需要实测真值的独立基准")
        status = "not_met"
    elif not bm:
        gaps.append("无独立基准：判别力未知")
        status = "not_met"
    else:
        ev.append("%d 个端点有非 DEMO 的 AUROC" % len(real))
        if calibration_reported:
            ev.append("已报校准（Brier/斜率/ECE）")
        else:
            gaps.append("未报校准：概率端点无法判断是否过自信")
        status = "satisfied" if not gaps else "partial"
    rows.append(
        dict(
            principle="P3",
            title=QAF_PRINCIPLES[2][1],
            status=status,
            evidence="；".join(ev) or "-",
            gap="；".join(gaps) or "-",
        )
    )

    # ---- P4 适配目的 ----
    ev, gaps = [], []
    ev.append("证据档位 %s" % tier)
    if tier == "T3":
        status = "satisfied"
        ev.append("支持发表级结论")
    elif tier == "T2":
        status = "partial"
        gaps.append("仅支持内部决策；写成论文结论即越级（见 tiers.MAX_CONCLUSION）")
    else:
        status = "not_met"
        gaps.append("仅探索性：不得进结论表/摘要")
    rows.append(
        dict(
            principle="P4",
            title=QAF_PRINCIPLES[3][1],
            status=status,
            evidence="；".join(ev) or "-",
            gap="；".join(gaps) or "-",
        )
    )
    return rows


# ---------------------------------------------------------------------------
# 3) PROBAST 四域偏倚风险（Wolff 2019）
# ---------------------------------------------------------------------------
def risk_of_bias(
    n_compounds=0,
    n_scaffolds=None,
    n_sources=0,
    n_judged_indep2=0,
    n_measured=0,
    has_benchmark=False,
    benchmark_ok=False,
    calibration_reported=False,
    dependency_handled=True,
    provenance_ok=True,
    n_judged=None,
):
    """返回 dict(overall, domains=[...])。

    四域（参与者/预测因子/结局/分析）全按 PROBAST 的语义映射到本 skill：
      参与者 = 化合物选择（同系类似物 → 外推性差 → 高风险）
      预测因子 = 预测源（单方法组投票 → 中等；无版本 → 高）
      结局    = 真值（无实测 → 高：等于没有 outcome 数据）
      分析    = 依赖分组/校准/多重比较
    """
    d = []

    # D1 参与者（化合物选择）
    sig = []
    if n_compounds < 10:
        j = "high"
        sig.append("化合物数 %d<10：任何亚组结论都会被单个分子主导" % n_compounds)
    elif n_compounds < 30:
        j = "medium"
        sig.append("化合物数 %d<30：统计量不稳" % n_compounds)
    else:
        j = "low"
        sig.append("化合物数 %d≥30" % n_compounds)
    if n_scaffolds is not None:
        if n_scaffolds <= 2:
            j = _worse(j, "high")
            sig.append("骨架簇仅 %d 个：同系类似物，跨化学类外推无依据" % n_scaffolds)
        elif n_scaffolds < 5:
            j = _worse(j, "medium")
            sig.append("骨架簇 %d<5：化学多样性有限" % n_scaffolds)
    d.append(
        dict(domain="D1 参与者（化合物选择）", judgement=j, rationale="；".join(sig))
    )

    # D2 预测因子（源）
    sig = []
    if n_judged_indep2 <= 0:
        j = "high"
        sig.append("无任何端点达到 2 个独立方法组：预测因子实质只有一组")
    elif n_sources < 3:
        j = "medium"
        sig.append("源数 %d<3" % n_sources)
    elif n_judged and n_judged_indep2 >= n_judged:
        j = "low"
        sig.append("%d 个可判端点全部达到 2 个独立方法组" % n_judged)
    else:
        j = "medium"
        sig.append(
            "仅 %d/%s 个可判端点达 2 独立组，其余单组"
            % (n_judged_indep2, n_judged if n_judged else "?")
        )
    if not provenance_ok:
        j = _worse(j, "high")
        sig.append("源版本/来源不可溯源")
    d.append(
        dict(domain="D2 预测因子（预测源）", judgement=j, rationale="；".join(sig))
    )

    # D3 结局（真值）
    sig = []
    if n_measured <= 0:
        j = "high"
        sig.append("无任何实测真值：等于没有 outcome 数据，判别力无法评估")
    elif n_measured < 10:
        j = "medium"
        sig.append("实测仅 %d 条：校准与 AUROC 的 CI 会很宽" % n_measured)
    else:
        j = "low"
        sig.append("实测 %d 条" % n_measured)
    d.append(dict(domain="D3 结局（真值定义）", judgement=j, rationale="；".join(sig)))

    # D4 分析
    sig = []
    if not has_benchmark and not calibration_reported:
        j = "high"
        sig.append("既无独立基准也无校准：性能完全未评估")
    elif has_benchmark and not benchmark_ok:
        j = "medium"
        sig.append("基准为 DEMO 或不可算 AUROC")
    elif benchmark_ok and not calibration_reported:
        j = "medium"
        sig.append("有判别力但无校准（概率端点决策需校准）")
    else:
        j = "low"
        sig.append("非 DEMO 基准 + 已报校准")
    if not dependency_handled:
        j = _worse(j, "high")
        sig.append("未处理源间依赖性：把相关源当独立投票会低估不确定度")
    d.append(dict(domain="D4 分析", judgement=j, rationale="；".join(sig)))

    overall = "low"
    for x in d:
        if _SEV[x["judgement"]] > _SEV[overall]:
            overall = x["judgement"]
    return dict(
        overall=overall,
        domains=d,
        note=(
            "整体偏倚风险 %s：%s"
            % (
                overall,
                (
                    "发表级结论要求低/中风险，当前只能作内部决策"
                    if overall == "high"
                    else "可用于对应档位的结论"
                ),
            )
        ),
    )
