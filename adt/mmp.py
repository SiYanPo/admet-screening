# -*- coding: utf-8 -*-
"""MMP 校准检验（R14 / A7 / B2）：把"结构扰动下是否稳定"从公理改成可检验命题。

评审 F4 原话：
  "正确零假设不是随机无关分子对（那是'结构差很多'的对照，任何模型都会显示大位移，
   检验近乎平凡），而是 ChEMBL 匹配分子对（MMP）中与扰动同型的结构变化所对应的经验
   Δactivity 分布……按当前设计，一个对活性悬崖完全无感（即'坏'）的模型会在这个检验中
   得到漂亮的 0.076 比值。检验的通过条件与科学上期望的行为可能反相关。"

本模块的做法（双管齐下，同时约束"过敏"与"迟钝"）：
  1. 从同一数据集内抽取**匹配分子对**（单切 MMP：共享 core，仅一个取代基不同）。
  2. 以 MMP 对的**实测标签变化率**作为经验基准（二分类端点下 Δlabel ∈ {−1,0,+1}）。
  3. 计算模型在同样 MMP 对上的**预测翻转率**。
  4. 判据：翻转率与经验变化率**等效**（TOST 双侧等效检验，等效界 ±δ），
     而不是"位移越小越好"。
  5. 负对照：把模型输出向 0.5 收缩（模拟"对活性悬崖无感"的坏模型），
     新检验必须**判它不通过**——否则检验本身没有辨别力。

局限（诚实声明）：
  - 二分类端点的 Δlabel 分辨率只有三档，等效检验的功效依赖 MMP 对数（见 power 字段）。
  - MMP 对来自同一数据集内部，可能隐含共线（同一骨架多对），已按 core 去重。
"""

from collections import defaultdict

from rdkit import Chem, RDLogger

RDLogger.DisableLog("rdApp.*")

try:
    from rdkit.Chem import rdMMPA
except Exception:  # pragma: no cover
    rdMMPA = None


def fragment_pairs(
    smiles_list, ids=None, max_cuts=1, min_core=6, min_frag=1, max_per_core=40
):
    """单切 MMP 抽取。

    RDKit 的 `FragmentMol(maxCuts=1)` 返回 (core='', chains='A.B')，即把分子切成两半；
    因此对每一条切分结果，两种"谁是 core"的解释都展开，再按 core 字符串分组配对。
    失败与空结果**不静默**：返回 (pairs, stats) 中的 stats 记录解析失败数。
    """
    if rdMMPA is None:
        raise RuntimeError("需要 RDKit rdMMPA（RDKit>=2020.09）")
    by_core = defaultdict(list)
    stats = {"n_mol": 0, "n_parse_fail": 0, "n_split": 0, "n_sides_kept": 0}
    for i, smi in enumerate(smiles_list):
        m = Chem.MolFromSmiles(smi) if isinstance(smi, str) else smi
        if m is None:
            stats["n_parse_fail"] += 1
            continue
        stats["n_mol"] += 1
        try:
            frags = rdMMPA.FragmentMol(m, maxCuts=max_cuts, resultsAsMols=False)
        except Exception:
            stats["n_parse_fail"] += 1
            continue
        for _core0, chains in frags:
            if not chains or chains.count(".") != 1:
                continue
            stats["n_split"] += 1
            a, b = chains.split(".")
            for core, sub in ((a, b), (b, a)):
                ha = sum(1 for ch in core if ch.isupper())
                hs = sum(1 for ch in sub if ch.isupper())
                if ha < min_core or hs < min_frag:
                    continue
                by_core[core].append((i, sub))
                stats["n_sides_kept"] += 1

    out = []
    for core, members in by_core.items():
        if len(members) < 2:
            continue
        members = members[:max_per_core]
        for a in range(len(members)):
            for b in range(a + 1, len(members)):
                ia, fa = members[a]
                ib, fb = members[b]
                if ia == ib or fa == fb:
                    continue
                out.append((core, ia, ib, fa, fb))
    return out, stats


def classify_change(frag_a, frag_b):
    """按"同型扰动"分层：stereo_only / same_heavy_atoms / plus_1 / plus_more。"""

    def heavy(s):
        return sum(1 for ch in s if ch.isupper())

    def strip_stereo(s):
        return s.replace("@", "").replace("/", "").replace("\\", "")

    ha, hb = heavy(frag_a), heavy(frag_b)
    if strip_stereo(frag_a) == strip_stereo(frag_b):
        return "stereo_only"
    if ha == hb:
        return "same_heavy_atoms"
    if abs(ha - hb) == 1:
        return "plus_1"
    return "plus_more"


def analyze(pairs, labels, probs, equiv_margin=0.10, alpha=0.05):
    """核心检验（**二值端点专用**）。

    pairs   : fragment_pairs 的输出
    labels  : 与 smiles 同序的真实标签（0/1）
    probs   : 与 smiles 同序的模型概率
    equiv_margin : TOST 等效界（翻转率与经验变化率之差 ≤ δ 视为等效）

    回归型端点（溶解度/渗透性/Caco2/MAE 类）**不得**调用本函数——
    连续标签下 ``abs(lb-la)>1e-9`` 会把每一对都判成"翻转"，结论完全失真。
    请改用 :func:`analyze_regression`。
    """
    import numpy as np

    _lab = np.asarray(labels, dtype=float)
    if _lab.size and not np.all(np.isin(np.unique(_lab), (0.0, 1.0))):
        raise ValueError(
            "mmp.analyze() 只接受 0/1 标签；检测到连续值 → 回归型端点请用 "
            "mmp.analyze_regression()（翻转率对连续标签无意义）"
        )

    rows = []
    for core, ia, ib, fa, fb in pairs:
        la, lb = float(labels[ia]), float(labels[ib])
        pa, pb = float(probs[ia]), float(probs[ib])
        rows.append(
            {
                "core": core,
                "i": ia,
                "j": ib,
                "kind": classify_change(fa, fb),
                "d_label": lb - la,
                "label_changed": int(abs(lb - la) > 1e-9),
                "d_prob": abs(pb - pa),
                "model_flip": int((pa >= 0.5) != (pb >= 0.5)),
            }
        )
    if not rows:
        return {"status": "no_mmp_pairs", "n_pairs": 0}

    def _prop_ci(k, n, alpha=0.05):
        """Wilson 区间（比 Wald 更适合接近 0/1 的比例）。"""
        if n == 0:
            return (0.0, 1.0)
        try:
            from scipy.stats import norm

            z = norm.ppf(1 - alpha / 2.0)
        except Exception:
            z = 1.96
        p = k / float(n)
        den = 1 + z * z / n
        c = (p + z * z / (2 * n)) / den
        h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / den
        return (max(0.0, c - h), min(1.0, c + h))

    def _tost(k1, n1, k2, n2, margin, alpha=0.05):
        """【LEGACY / C10，2026-11-04】两比例**独立样本** Wald TOST。

        ⚠ MMP 对是**配对**数据：本函数用独立两样本 SE 忽略配对协方差，
        方差错误，`equivalent` 不得作为推断结论（evidence_grade=non_evidence）。
        正确实现见 `adt/paired_stats.py::paired_tost`（逐 MMP 对差值 bootstrap）。
        保留本函数仅为向后兼容与对照；正式结论必须改用 paired_tost 或
        仓库自有的 `prospective.paired_mcnemar`（该项原已实现却未在此使用）。
        返回 (d, ci_lo, ci_hi, equivalent)；调用方须给产物打 non_evidence 标记。
        """
        import math

        try:
            from scipy.stats import norm

            z = norm.ppf(1 - alpha)
        except Exception:
            z = 1.645
        p1, p2 = k1 / float(n1) if n1 else 0.0, k2 / float(n2) if n2 else 0.0
        d = p1 - p2
        se = math.sqrt(max(p1 * (1 - p1) / n1, 1e-12) + max(p2 * (1 - p2) / n2, 1e-12))
        lo, hi = d - z * se, d + z * se
        # 等效：差的双侧 90%CI 完全落在 (−margin, +margin)
        return d, lo, hi, (lo > -margin and hi < margin)

    by_kind = defaultdict(list)
    for r in rows:
        by_kind[r["kind"]].append(r)

    out_kinds = []
    for kind, rs in sorted(by_kind.items()):
        n = len(rs)
        k_lab = sum(r["label_changed"] for r in rs)
        k_flip = sum(r["model_flip"] for r in rs)
        lo_lab, hi_lab = _prop_ci(k_lab, n)
        lo_fl, hi_fl = _prop_ci(k_flip, n)
        d, dlo, dhi, equiv = _tost(k_flip, n, k_lab, n, equiv_margin, alpha)
        out_kinds.append(
            {
                "kind": kind,
                "n_pairs": n,
                "label_change_rate": round(k_lab / float(n), 3),
                "label_ci95": [round(lo_lab, 3), round(hi_lab, 3)],
                "model_flip_rate": round(k_flip / float(n), 3),
                "flip_ci95": [round(lo_fl, 3), round(hi_fl, 3)],
                "diff_flip_minus_label": round(d, 3),
                "diff_ci90": [round(dlo, 3), round(dhi, 3)],
                "tost_equivalent": bool(equiv),
                "verdict": (
                    "equivalent"
                    if equiv
                    else (
                        "insensitive"
                        if d < -equiv_margin
                        else "oversensitive" if d > equiv_margin else "inconclusive"
                    )
                ),
            }
        )

    n_all = len(rows)
    k_lab_all = sum(r["label_changed"] for r in rows)
    k_flip_all = sum(r["model_flip"] for r in rows)

    # ---- 黑4：把单一"翻转率"拆成召回与特异度（评审 B2 的验收问法）----
    # 单一翻转率读不出召回：模型"完全不动"会同时贡献 0 个真阳和全部真阴，
    # 混在一个率里既看不出漏掉多少悬崖，也看不出误报多少。
    n_changed = int(k_lab_all)
    n_unchanged = int(n_all - k_lab_all)
    hit = sum(1 for r in rows if r["label_changed"] and r["model_flip"])
    false_alarm = sum(1 for r in rows if (not r["label_changed"]) and r["model_flip"])
    sensitivity = (hit / float(n_changed)) if n_changed else None  # 悬崖召回
    specificity = (
        ((n_unchanged - false_alarm) / float(n_unchanged)) if n_unchanged else None
    )  # 未变对的守静能力
    false_alarm_rate = (false_alarm / float(n_unchanged)) if n_unchanged else None
    d_all, lo_all, hi_all, eq_all = _tost(
        k_flip_all, n_all, k_lab_all, n_all, equiv_margin, alpha
    )
    mean_dp = float(np.mean([r["d_prob"] for r in rows]))
    _p = _power_block(n_all, k_lab_all / float(n_all), equiv_margin, alpha)
    return {
        "n_pairs": n_all,
        "n_cores": len({r["core"] for r in rows}),
        "overall": {
            "label_change_rate": round(k_lab_all / float(n_all), 3),
            "model_flip_rate": round(k_flip_all / float(n_all), 3),
            "diff": round(d_all, 3),
            "diff_ci90": [round(lo_all, 3), round(hi_all, 3)],
            "tost_equivalent": bool(eq_all),
            "equiv_margin": equiv_margin,
            "mean_abs_dprob": round(mean_dp, 4),
            "cliff_recall": (
                round(sensitivity, 3) if sensitivity is not None else None
            ),
            "cliff_recall_n": n_changed,
            "flat_specificity": (
                round(specificity, 3) if specificity is not None else None
            ),
            "flat_false_alarm_rate": (
                round(false_alarm_rate, 3) if false_alarm_rate is not None else None
            ),
            "flat_n": n_unchanged,
        },
        "by_kind": out_kinds,
        "power": _p,
        "status": _overall_status(d_all, eq_all, equiv_margin, _p),
        "direction": (
            "insufficient_power"
            if not _p["adequate"]
            else (
                "equivalent"
                if eq_all
                else (
                    "insensitive"
                    if d_all < -equiv_margin
                    else "oversensitive" if d_all > equiv_margin else "inconclusive"
                )
            )
        ),
        "interpretation": _overall_interpretation(d_all, eq_all, equiv_margin, _p),
        "note": "判据是'与 MMP 经验等效'，不是'位移越小越好'（评审 F4）",
    }


def min_pairs_for_power(label_rate, margin=0.10, alpha=0.05):
    """TOST 在该等效界下**能通过一个完美模型**所需的最小对数。

    最有利情形：模型翻转率恰等于标签翻转率（d=0），此时
        se = sqrt(2·p(1−p)/n)，需 z·se < margin
    ⇒   n > 2·p(1−p)·(z/margin)²

    DILI 实测（n=31，p=0.129）会落到阈值以下：oracle-like 正对照翻转率 0.129
    完全正确，却因 CI 过宽被判"不等效"——**这说明是样本量不足，不是模型有病**。
    """
    import math

    try:
        from scipy.stats import norm

        z = norm.ppf(1 - alpha)
    except Exception:
        z = 1.645
    p = min(max(float(label_rate), 0.02), 0.5)
    n = 2.0 * p * (1.0 - p) * (z / margin) ** 2
    return int(math.ceil(n))


def _power_block(n_pairs, label_rate, margin, alpha):
    n_min = min_pairs_for_power(label_rate, margin, alpha)
    ok = n_pairs >= n_min
    return {
        "n_pairs": int(n_pairs),
        "min_pairs_required": int(n_min),
        "adequate": bool(ok),
        "note": (
            "样本量足以判定"
            if ok
            else "样本量不足：本检验在此 n 下**连完美模型也判不了等效**，"
            "任何'不等效'结论都不可采信"
        ),
    }


def _overall_status(d, equivalent, margin, power=None):
    """状态码。**必须区分方向**：位移过小 = 对活性悬崖迟钝（坏），
    位移过大 = 过敏（也可能坏）。旧版只写"NOT_equivalent"，方向丢失。"""
    if power is not None and not power["adequate"]:
        return (
            "INSUFFICIENT_POWER（n_pairs=%d < 需 %d；该样本量下完美模型也判不了等效，"
            "结论无效）" % (power["n_pairs"], power["min_pairs_required"])
        )
    if equivalent:
        return "equivalent"
    if d < -margin:
        return "NOT_equivalent:insensitive（模型翻转率显著低于 MMP 真实标签翻转率——对活性悬崖迟钝）"
    if d > margin:
        return "NOT_equivalent:oversensitive（模型翻转率显著高于 MMP 真实标签翻转率——对微小结构变化过敏）"
    return "inconclusive（差值 CI 跨出等效界但点估计落在界内）"


def _overall_interpretation(d, equivalent, margin, power=None):
    if power is not None and not power["adequate"]:
        return (
            "检验功效不足（%d 对 < 需 %d 对），**不得**据此判定模型迟钝或过敏。"
            "处置：扩充 MMP 对，或按扰动类型分层报告，或改用等效界更宽的预设并预注册。"
            % (power["n_pairs"], power["min_pairs_required"])
        )
    if equivalent:
        return (
            "模型的结构敏感度与匹配分子对的经验标签变化率等效（TOST），"
            "可认为'该敏感的敏感、不该敏感的不敏感'。"
        )
    if d < -margin:
        return (
            "模型在真实会发生标签翻转的 MMP 对上几乎不翻转 → 结构扰动检验**不通过**。"
            "注意：这不等于'模型稳定'，恰恰相反，是模型缺失结构-活性悬崖信息。"
            "**禁止**把本结果表述为'对合法结构变体稳定'。"
        )
    if d > margin:
        return (
            "模型在标签未变的 MMP 对上仍大幅翻转 → 过度敏感，会把同系物误判为不同活性。"
        )
    return "证据不足，不下结论。"


def analyze_regression(
    pairs, y_values, preds, ratio_margin=0.5, alpha=0.05, n_boot=4000, seed=0
):
    """回归型端点（溶解度 / 渗透性 / Caco2 / 任何连续 Δ）的 MMP 检验。

    翻转率对连续标签无意义（每对都"变"了），所以改用**位移幅度比**：
        R = median(|Δpred|) / median(|Δlabel|)
    R = 1 表示模型对结构变化的幅度感与真实一致；R ≪ 1 表示迟钝；R ≫ 1 表示过敏。

    判据（TOST 风格，配对 bootstrap）：
      · R 的 95%CI 完全落在 (1−ratio_margin, 1+ratio_margin) 内 → equivalent；
      · CI 上界 < 1−ratio_margin → insensitive；
      · CI 下界 > 1+ratio_margin → oversensitive；
      · 其余 → inconclusive。
    ratio_margin 默认 0.5（可接受 0.5–1.5 倍），是**约定**，须在选择后预注册。
    """
    import numpy as np

    rows = []
    for core, ia, ib, fa, fb in pairs:
        dy = abs(float(y_values[ib]) - float(y_values[ia]))
        dp = abs(float(preds[ib]) - float(preds[ia]))
        rows.append(
            {"core": core, "kind": classify_change(fa, fb), "d_label": dy, "d_pred": dp}
        )
    if not rows:
        return {"status": "no_mmp_pairs", "n_pairs": 0}

    dy = np.array([r["d_label"] for r in rows], dtype=float)
    dp = np.array([r["d_pred"] for r in rows], dtype=float)
    med_y, med_p = float(np.median(dy)), float(np.median(dp))
    if med_y <= 0:
        return {
            "status": "degenerate（MMP 对标签无变化，比值无定义）",
            "n_pairs": len(rows),
        }

    rng = np.random.default_rng(seed)
    n = len(rows)
    rat = np.empty(n_boot)
    for b in range(n_boot):
        idx = rng.integers(0, n, n)
        my, mp = np.median(dy[idx]), np.median(dp[idx])
        rat[b] = (mp / my) if my > 0 else np.nan
    rat = rat[~np.isnan(rat)]
    lo, hi = float(np.percentile(rat, 2.5)), float(np.percentile(rat, 97.5))
    R = med_p / med_y
    lo_ok, hi_ok = 1.0 - ratio_margin, 1.0 + ratio_margin

    if hi < lo_ok:
        direction, verdict = "insensitive", "NOT_equivalent:insensitive"
    elif lo > hi_ok:
        direction, verdict = "oversensitive", "NOT_equivalent:oversensitive"
    elif lo > lo_ok and hi < hi_ok:
        direction, verdict = "equivalent", "equivalent"
    else:
        direction, verdict = "inconclusive", "inconclusive"

    # ---- R 单独不够：必须与符号一致率合读 ---------------------------------
    # 任何"回归到均值"的模型都必然 R<1（幅度被压缩），这与"对结构不敏感"是
    # 两件事。区分它们只需要看方向对不对：Δpred 与 Δlabel 同号的比例。
    # 实测来源（2026-11-01，脂溶性 4636 对）：R=0.32 判 insensitive，
    # 但符号一致率 0.73 —— 方向系统性地是对的，只是幅度被压到 1/3。
    # 若照 R 直接写"迟钝"，就是又一次把"压缩"误报成"缺陷"。
    sign_same, sign_n, sign_agree, sign_z = 0, 0, None, None
    for core, ia, ib, _fa, _fb in pairs:
        dy_s = float(y_values[ib]) - float(y_values[ia])
        dp_s = float(preds[ib]) - float(preds[ia])
        if abs(dy_s) < 1e-12 or abs(dp_s) < 1e-12:
            continue
        sign_n += 1
        if (dy_s > 0) == (dp_s > 0):
            sign_same += 1
    if sign_n > 0:
        import math

        sign_agree = sign_same / sign_n
        # 二项符号检验的正态近似（H0: p=0.5）。z>=3.0 ↔ 单侧 p<0.0014。
        sign_z = (sign_same - 0.5 * sign_n) / (0.5 * math.sqrt(sign_n))

    SIGN_Z_FLOOR = 3.0
    if direction == "insensitive" and sign_z is not None and sign_z >= SIGN_Z_FLOOR:
        direction, verdict = "compressed", "NOT_equivalent:compressed"

    power = {
        "n_pairs": n,
        "min_pairs_required": 30,
        "adequate": n >= 30,
        "note": (
            "样本量足以判定"
            if n >= 30
            else "样本量 <30，中位数比值的 bootstrap CI 过宽，结论不可采信"
        ),
    }
    if not power["adequate"]:
        direction, verdict = "insufficient_power", "INSUFFICIENT_POWER"

    return {
        "n_pairs": n,
        "n_cores": len({r["core"] for r in rows}),
        "overall": {
            "median_abs_dlabel": round(med_y, 4),
            "median_abs_dpred": round(med_p, 4),
            "displacement_ratio": round(R, 3),
            "ratio_ci95": [round(lo, 3), round(hi, 3)],
            "ratio_margin": ratio_margin,
            "by_kind": _regression_by_kind(rows),
        },
        "power": power,
        "status": verdict,
        "direction": direction,
        "sign_agreement": (round(sign_agree, 3) if sign_agree is not None else None),
        "sign_agreement_n": sign_n,
        "sign_z": (round(sign_z, 2) if sign_z is not None else None),
        "sign_z_floor": SIGN_Z_FLOOR,
        "interpretation": {
            "equivalent": "模型的结构敏感度幅度与 MMP 经验一致。",
            "insensitive": (
                "模型位移幅度显著小于真实标签变化幅度，且**方向与真实变化"
                "不一致**（符号一致率接近随机）→ 对结构变化确实迟钝"
                "（这不是'稳定'）。"
            ),
            "compressed": (
                "位移幅度被压缩（R<1），但方向与真实变化显著一致"
                "（符号一致率显著>0.5）→ 这是**回归到均值型收缩**，"
                "不是结构迟钝。允许写'幅度保守、方向可靠'，"
                "**禁止**写'对结构变化不敏感'。"
            ),
            "oversensitive": "模型位移幅度显著大于真实标签变化 → 过度敏感。",
            "inconclusive": "CI 跨出等效界，证据不足。",
            "insufficient_power": "样本量不足，不下结论。",
        }[direction],
        "note": (
            "回归型端点专用：判据是位移幅度比 R 的 TOST，不是翻转率。"
            "ratio_margin 是约定值，换端点须重新预注册。"
            "R<1 对'回归到均值'的模型是数学必然，故 R 判定必须与 "
            "sign_agreement 合读：sign_z>=%.1f 时判 compressed 而非 insensitive。"
            % SIGN_Z_FLOOR
        ),
    }


def _regression_by_kind(rows):
    import numpy as np

    out = []
    kinds = {}
    for r in rows:
        kinds.setdefault(r["kind"], []).append(r)
    for kind, rs in sorted(kinds.items()):
        dy = np.array([r["d_label"] for r in rs], float)
        dp = np.array([r["d_pred"] for r in rs], float)
        my = float(np.median(dy)) if len(dy) else 0.0
        out.append(
            {
                "kind": kind,
                "n_pairs": len(rs),
                "median_abs_dlabel": round(my, 4),
                "median_abs_dpred": round(float(np.median(dp)), 4) if len(dp) else None,
                "displacement_ratio": (
                    round(float(np.median(dp)) / my, 3) if my > 0 else None
                ),
            }
        )
    return out


def controls(pairs, labels, probs, shrink=0.15, equiv_margin=0.10, seed=0):
    """正/负对照：证明检验既能通过"对的模型"，也能拒绝"错的模型"。

    - 正对照（oracle-like）：以真标签构造伪概率（小抖动）→ 翻转率≈标签变化率，
      检验**应判 equivalent**；若它都不通过，说明判据本身不可用。
    - 负对照（cliff-blind）：把概率向 0.5 收缩 → 翻转率趋 0，
      检验**应判 insensitive**。
    """
    import random

    rnd = random.Random(seed)
    probs_oracle = [
        min(0.98, max(0.02, 0.90 * float(y) + 0.05 + rnd.uniform(-0.02, 0.02)))
        for y in labels
    ]
    probs_shrunk = [0.5 + (p - 0.5) * shrink for p in probs]
    res = {
        "original": analyze(pairs, labels, probs, equiv_margin),
        "oracle_like": analyze(pairs, labels, probs_oracle, equiv_margin),
        "cliff_blind": analyze(pairs, labels, probs_shrunk, equiv_margin),
    }
    res["test_has_power"] = bool(
        res["oracle_like"]["overall"]["tost_equivalent"]
        and not res["cliff_blind"]["overall"]["tost_equivalent"]
    )
    return res


def negative_control(pairs, labels, probs, shrink=0.15, equiv_margin=0.10):
    """向后兼容入口（仅负对照）。"""
    probs_shrunk = [0.5 + (p - 0.5) * shrink for p in probs]
    return {
        "original": analyze(pairs, labels, probs, equiv_margin),
        "cliff_blind": analyze(pairs, labels, probs_shrunk, equiv_margin),
    }
