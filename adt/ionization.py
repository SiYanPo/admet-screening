# -*- coding: utf-8 -*-
"""电离状态 / pKa 层（v4.14）：把"本机没有可靠 pKa 源"这个已声明缺口补成一个**带区间的估计**。

为什么需要它（原缺口，见 references/00_scope.md 第 25 行与 adt/normalize.py:170）：
  Gate 0.5 一直只做"去盐 + 中和"，即**按 SMARTS 猜电荷**，不看 pH。
  但同一分子在 pH 7.4 下到底带不带电，决定了四件事：
    ① 被动渗透（Caco-2 / BBB）——离子态几乎不透；
    ② 转运体底物类型（有机阴离子 → OATP；有机阳离子 → OCT/MATE）；
    ③ logD7.4 与 logP 的差（logD 才是分配系数的真实量）；
    ④ 与血浆蛋白结合 / 组织分布的方向。

**这个模块不预测 pKa 数值，只做三件更保守的事**：
  1. 认出可电离基团（文献 SMARTS，可审计）；
  2. 用**该基团类别的文献 pKa 区间**（不是拟合值）代入 Henderson–Hasselbalch，
     得到 pH 7.4 下的**电离分数区间**与**净电荷区间**；
  3. 由此给出 logD7.4 相对 logP 的**位移区间**，用来判断"这个分子的 logP 能不能直接当
     logD 用"。

硬约束（写在返回值里，不许省略）：
  * `pka_grade = "literature_category_range"`：pKa 是**类别级文献区间**，不是本分子实测；
    取代基效应（卤素、硝基、邻位位阻、糖苷化）**未建模**；
  * 因此只能用 `charge_class` / `net_charge_range` / `logd_shift_range` 做**分区与方向**
    判断；**禁止**把 `pka_point` 当成"这个分子的 pKa"写进任何表；
  * 若某个基团落在区间两端会改变结论（如 pKa 4.2 与 5.5 跨过 pH 7.4 的分界），
    必须报 `bracket_straddles_ph=True` 并要求用实测 pKa（Graph-pKa / 电位滴定）复核。

与 skill 其它模块的关系：
  * 本模块**不投票**、不进 reliab 计票（它是结构推断，不是外部源预测）；
  * 它是 Gate 0.5 的补充证据，输出落 `ionization.csv`，供人工核对与报告引用。
"""

from __future__ import division

import math

__all__ = [
    "GROUPS",
    "PHYSIOLOGIC_PH",
    "compiled_groups",
    "ionizable_groups",
    "fraction_ionized",
    "ionization_profile",
    "logd_from_logp",
    "charge_class_of",
    "limits_statement",
]

PHYSIOLOGIC_PH = 7.4

# ---------------------------------------------------------------------------
# 可电离基团表
#   pka / lo / hi：**该类基团在药物化学文献中的常见区间**，不是某分子实测值。
#   kind：acid（给出质子→带负电）/ base（接受质子→带正电）
#   priority：小者先匹配；同一原子只归属一个基团（避免苯酚又算酚又算酸）
# 依据（类别级，均为主流药物化学教科书/综述口径，不冒充单点实测）：
#  羧酸 4–5（脂肪族）/ 酚 9.5–10.5 / 磺酰胺 8–10.5 / 磷酸二酯 6.5–7.5
#  脂肪胺 9.5–10.5 / 苯胺 4.6 / 吡啶 5.2 / 咪唑 6.0 / 胍 12.5
# ---------------------------------------------------------------------------
GROUPS = [
    dict(
        name="carboxylic_acid",
        kind="acid",
        pka=4.5,
        lo=3.0,
        hi=5.5,
        priority=10,
        smarts="[CX3](=[OX1])[OX2H1]",
        note="脂肪/芳香羧酸；α-吸电子基可低至 1–2，本表未建模",
    ),
    dict(
        name="phosphate_diester_acid",
        kind="acid",
        pka=6.8,
        lo=6.0,
        hi=7.5,
        priority=12,
        smarts="[PX4](=[OX1])([OX2H1])[OX2H1]",
        note="磷酸单酯/二酯的第二个 OH；第一电离常在 1–2（已强酸，不影响 7.4）",
    ),
    dict(
        name="sulfonamide_NH",
        kind="acid",
        pka=9.5,
        lo=8.0,
        hi=10.5,
        priority=15,
        smarts="[SX4](=[OX1])(=[OX1])[NX3;H1,H2]",
        note="芳香磺酰胺偏酸（~8–9），脂肪磺酰胺偏碱（~10–11），方向可能相反",
    ),
    dict(
        name="tetrazole",
        kind="acid",
        pka=4.9,
        lo=4.0,
        hi=5.5,
        priority=16,
        smarts="[nH1]1[nX2][nX2][nX2][cX3]1",
        note="5-取代四唑；生物等排体，酸性接近羧酸",
    ),
    dict(
        name="phenol",
        kind="acid",
        pka=10.0,
        lo=9.0,
        hi=11.0,
        priority=20,
        smarts="[OX2H1]c",
        note="邻/对位吸电子基可降到 7–8（如硝基酚、邻苯二酚的第二解离）",
    ),
    # 2026-11-19（面板实跑）：双胍（二甲双胍）被拆成 amidine + guanidine **两组**，
    # 净电荷算成 +2；真实是单一强碱位点，pH 7.4 下 +1。双胍必须先占位。
    dict(
        name="biguanide",
        kind="base",
        pka=12.4,
        lo=11.5,
        hi=13.0,
        priority=28,
        smarts="[NX3][CX3](=[NX2])[NX3][CX3](=[NX2])[NX3]",
        note="双胍（二甲双胍类）：一条共轭强碱链，只按**一个**碱性位点计；"
        "拆成脒+胍会高估净电荷（实测 +2 vs 真实 +1）",
    ),
    dict(
        name="guanidine",
        kind="base",
        pka=12.5,
        lo=11.0,
        hi=13.5,
        priority=30,
        smarts="[NX3][CX3](=[NX2])[NX3]",
        note="生理 pH 下几乎全质子化；碱性极强",
    ),
    dict(
        name="amidine",
        kind="base",
        pka=11.0,
        lo=10.0,
        hi=12.0,
        priority=32,
        smarts="[NX3][CX3]=[NX2]",
        note="脒；胍的匹配已把它们排除（priority 30 先占原子）",
    ),
    dict(
        name="aniline",
        kind="base",
        pka=4.6,
        lo=3.0,
        hi=5.5,
        priority=40,
        smarts="[NX3;H2,H1,H0;!$(N[C,S]=[O,S])]c",
        note="苯胺/芳胺；与芳环共轭 → 碱性弱，pH 7.4 下多为中性",
    ),
    dict(
        name="pyridine",
        kind="base",
        pka=5.2,
        lo=4.0,
        hi=6.5,
        priority=42,
        smarts="[nX2]1[c,n][c,n][c,n][c,n][c,n]1",
        note="六元芳杂环 N（吡啶/嘧啶/吡嗪）；吸电子取代可降到 2–3",
    ),
    dict(
        name="imidazole",
        kind="base",
        pka=6.0,
        lo=5.0,
        hi=7.0,
        priority=44,
        smarts="[nX2]1[c,n][c,n][c,n][c,n]1",
        note="五元芳杂环的亚胺型 N（咪唑/吡唑/三唑）；pKa 恰在生理 pH 附近 → 质子海绵效应。"
        "**已知偏差**：嘌呤/黄嘌呤环（咖啡因/茶碱/可可碱）的同类 N 实测共轭酸 "
        "pKa≈0.6–1，本表按 6.0 估会高估碱性；pH 7.4 下仍判中性，结论方向不变",
    ),
    dict(
        name="aliphatic_amine",
        kind="base",
        pka=9.5,
        lo=8.5,
        hi=10.5,
        priority=50,
        smarts=(
            "[NX3;H2,H1,H0;!$([NX3][C]=[O,S]);!$([NX3][SX4]=O);"
            "!$([NX3]c);!$([NX3][N,O]);!$([NX3][CX2]#N);!$([N+])]"
        ),
        note="脂肪胺（伯/仲/叔）；酰胺/磺酰胺/芳胺/肼/腈/季铵已排除",
    ),
]

# 2026-11-19（面板实跑）：4-羟基香豆素类"内酯烯醇"被 `[OX2H1]c` 当成普通酚（pKa 10），
# 于是华法林在 pH 7.4 被判成 neutral_dominant（f_neutral=0.9975），而真实 pKa≈4.5–5.0
# → 应判 ionized_dominant。这不是"类别区间 ±1 log"能解释的偏差，是**认错了基团**。
# 该基团是 β-二羰基的乙烯基酸（vinylogous acid），必须单列。
# 判别条件（刻意收窄，避免误伤 3-羟基黄酮 pKa≈6.7 与普通酚）：
#   ① O–H 连在芳碳上；② 该碳在 6 元芳环内；③ 环内有 O；④ 该环 O **直接连羰基碳**（内酯）。
ENOL_LACTONE = dict(
    name="vinylogous_acid_lactone_enol",
    kind="acid",
    pka=4.7,
    lo=4.0,
    hi=5.5,
    priority=14,
    smarts=None,
    note="4-羟基香豆素/内酯烯醇（β-二羰基乙烯基酸）：pKa 4–5.5；"
    "被普通酚表（10.0）误判会把 pH 7.4 的电荷状态整个颠倒",
)


def _lactone_enol_oxygens(mol):
    """返回属于"内酯烯醇"酸性 OH 的氧原子下标集合（见 ENOL_LACTONE 注释）。"""
    rings = mol.GetRingInfo().AtomRings()
    out = set()
    for a in mol.GetAtoms():
        if a.GetSymbol() != "O" or a.GetTotalNumHs() != 1:
            continue
        c = a.GetNeighbors()[0]
        if not (c.GetIsAromatic() and c.GetSymbol() == "C"):
            continue
        for ring in rings:
            if c.GetIdx() not in ring or len(ring) != 6:
                continue
            o_in_ring = [i for i in ring if mol.GetAtomWithIdx(i).GetSymbol() == "O"]
            if not o_in_ring:
                continue
            for oi in o_in_ring:
                o = mol.GetAtomWithIdx(oi)
                for b in o.GetBonds():
                    nb = b.GetOtherAtom(o)
                    if nb.GetSymbol() != "C":
                        continue
                    # 不要求 O–C 键为单键：RDKit 会把香豆素的内酯环判成芳香环，
                    # 该键显示为 1.5（实测踩过，写成 ==1.0 则整条规则永不命中）。
                    # 判"环 O 连着羰基碳"：nb 有且仅有一个双键氧。
                    has_carbonyl = any(
                        bb.GetBondTypeAsDouble() == 2.0
                        and bb.GetOtherAtom(nb).GetSymbol() == "O"
                        for bb in nb.GetBonds()
                    )
                    if has_carbonyl:
                        out.add(a.GetIdx())
    return out


_CACHE = {}


def compiled_groups():
    """返回按 priority 排序的 [(group_dict, rdkit_pattern)]，进程内缓存。"""
    if "g" in _CACHE:
        return _CACHE["g"]
    from rdkit import Chem, RDLogger

    RDLogger.DisableLog("rdApp.*")
    out = []
    for g in sorted(GROUPS, key=lambda x: x["priority"]):
        patt = Chem.MolFromSmarts(g["smarts"])
        if patt is None:  # 写错 SMARTS 必须当场炸，不许静默跳过
            raise ValueError("SMARTS 编译失败：%s -> %r" % (g["name"], g["smarts"]))
        out.append((dict(g), patt))
    _CACHE["g"] = out
    return out


def fraction_ionized(kind, pka, ph):
    """Henderson–Hasselbalch：返回该基团在给定 pH 下的电离分数（0–1）。"""
    if kind == "acid":
        d = ph - pka  # 越大越电离
    else:
        d = pka - ph
    if d > 12:
        return 1.0
    if d < -12:
        return 0.0
    return 10.0**d / (1.0 + 10.0**d)


def _log_factor(kind, pka, ph):
    if kind == "acid":
        d = ph - pka
    else:
        d = pka - ph
    if d > 12:
        return d
    if d < -12:
        return 0.0
    return math.log10(1.0 + 10.0**d)


def ionizable_groups(smiles):
    """认出可电离基团。返回 list[dict(name, kind, pka, lo, hi, atom_ids, note)]。

    同一原子只归属一个基团（按 priority），避免"酚羟基被算两次"。
    非法/空 SMILES 返回 []（由调用方决定记 out_of_domain）。
    """
    from rdkit import Chem, RDLogger

    RDLogger.DisableLog("rdApp.*")
    m = Chem.MolFromSmiles(smiles) if smiles else None
    if m is None:
        return []
    claimed, hits = set(), []
    # 内酯烯醇先占位（priority 14 的效果），否则会被 phenol 的 [OX2H1]c 抢走
    for oi in _lactone_enol_oxygens(m):
        claimed.add(oi)
        hits.append(
            dict(
                name=ENOL_LACTONE["name"],
                kind=ENOL_LACTONE["kind"],
                pka=ENOL_LACTONE["pka"],
                lo=ENOL_LACTONE["lo"],
                hi=ENOL_LACTONE["hi"],
                atom_ids=[oi],
                note=ENOL_LACTONE["note"],
            )
        )
    for g, patt in compiled_groups():
        for match in m.GetSubstructMatches(patt):
            atoms = set(match)
            if atoms & claimed:  # 与已有基团共享原子 → 跳过（去重）
                continue
            claimed |= atoms
            hits.append(
                dict(
                    name=g["name"],
                    kind=g["kind"],
                    pka=g["pka"],
                    lo=g["lo"],
                    hi=g["hi"],
                    atom_ids=sorted(atoms),
                    note=g["note"],
                )
            )
    hits.sort(key=lambda x: (x["kind"], x["pka"]))
    return hits


def charge_class_of(f_neutral):
    """按未电离分数分区（仅三档，避免伪精度）。"""
    if f_neutral >= 0.90:
        return "neutral_dominant"
    if f_neutral <= 0.10:
        return "ionized_dominant"
    return "mixed"


def ionization_profile(smiles, ph=PHYSIOLOGIC_PH):
    """pH 下的电离画像。

    返回 dict：
      available        是否可算（SMILES 可解析）
      n_acid/n_base    可电离基团计数
      groups           逐基团 f_ionized_point / f_ionized_range
      f_neutral        未电离（净电荷≈0 的母体形态）分数，point + range
      net_charge       平均净电荷 Σ(f_acid) − Σ(f_base)，point + range
      charge_class     neutral_dominant / mixed / ionized_dominant
      zwitterion       同时存在显著酸性与碱性电离
      logd_shift       logD_pH − logP 的位移（负数），point + range
      bracket_straddles_ph  是否有基团在区间两端跨过"电离与否"的分界
      pka_grade        证据等级（固定字符串）
      limits           使用边界原文
    """
    groups = ionizable_groups(smiles)
    base_out = dict(
        available=False,
        ph=ph,
        n_acid=0,
        n_base=0,
        groups=[],
        f_neutral=float("nan"),
        f_neutral_range=(float("nan"),) * 2,
        net_charge=float("nan"),
        net_charge_range=(float("nan"),) * 2,
        charge_class="unknown",
        zwitterion=False,
        logd_shift=float("nan"),
        logd_shift_range=(float("nan"),) * 2,
        bracket_straddles_ph=False,
        pka_grade="literature_category_range",
        limits=limits_statement(),
    )
    if not groups:
        # 三种可能：SMILES 非法、确实没有可电离基团、或**永久荷电**（季铵等）。
        # v4.22 修复：run7 实测 Berberine 的芳环季铵 [n+] 有 formal charge +1，
        # 却被判成 neutral_no_group / net_charge=0 —— 季铵在任何 pH 都荷电，
        # 不属于"无可电离基团"，必须单独归类，否则 logD/BBB/膜渗透全部判错方向。
        from rdkit import Chem, RDLogger

        RDLogger.DisableLog("rdApp.*")
        m = Chem.MolFromSmiles(smiles) if smiles else None
        if m is None:
            return base_out
        formal = sum(a.GetFormalCharge() for a in m.GetAtoms())
        if formal != 0:
            base_out.update(
                available=True,
                charge_class="permanently_charged",
                net_charge=float(formal),
                net_charge_range=(float(formal), float(formal)),
                f_neutral=0.0,
                f_neutral_range=(0.0, 0.0),
                logd_shift=0.0,
                logd_shift_range=(0.0, 0.0),
                note="formal_charge=%+d（季铵/两性离子等永久荷电，"
                "与 pH 无关；logD≈logP−|电荷修正|，勿按中性分子外推）" % formal,
            )
            return base_out
        base_out.update(
            available=True,
            charge_class="neutral_no_group",
            f_neutral=1.0,
            f_neutral_range=(1.0, 1.0),
            net_charge=0.0,
            net_charge_range=(0.0, 0.0),
            logd_shift=0.0,
            logd_shift_range=(0.0, 0.0),
        )
        return base_out

    rows = []
    f_neutral = 1.0
    f_neutral_lo, f_neutral_hi = 1.0, 1.0
    for g in groups:
        f = fraction_ionized(g["kind"], g["pka"], ph)
        # 区间端点：对酸而言 pKa 越大越不电离；对碱而言 pKa 越大越电离
        f_at = {p: fraction_ionized(g["kind"], p, ph) for p in (g["lo"], g["hi"])}
        f_lo, f_hi = min(f_at.values()), max(f_at.values())
        # 母体（未电离）分数的上下界：电离分数越大，母体越小
        n_lo, n_hi = 1.0 - f_hi, 1.0 - f_lo
        rows.append(
            dict(
                name=g["name"],
                kind=g["kind"],
                pka=g["pka"],
                pka_range=[g["lo"], g["hi"]],
                atom_ids=g["atom_ids"],
                note=g["note"],
                f_ionized=round(f, 4),
                f_ionized_range=[round(f_lo, 4), round(f_hi, 4)],
            )
        )
        f_neutral *= 1.0 - f
        f_neutral_lo *= n_lo
        f_neutral_hi *= n_hi

    acids = [r for r in rows if r["kind"] == "acid"]
    bases = [r for r in rows if r["kind"] == "base"]
    net = sum(-r["f_ionized"] for r in acids) + sum(r["f_ionized"] for r in bases)
    net_lo = sum(-r["f_ionized_range"][1] for r in acids) + sum(
        r["f_ionized_range"][0] for r in bases
    )
    net_hi = sum(-r["f_ionized_range"][0] for r in acids) + sum(
        r["f_ionized_range"][1] for r in bases
    )

    # logD 位移 = −Σ log10(1+10^δ)：多质子化的扩展 Henderson–Hasselbalch
    shift = -sum(_log_factor(g["kind"], g["pka"], ph) for g in groups)
    # 逐基团取使位移最大的端点，保证包住真实位移
    shift_lo = -sum(
        _log_factor(g["kind"], (g["lo"] if g["kind"] == "acid" else g["hi"]), ph)
        for g in groups
    )
    shift_hi = -sum(
        _log_factor(g["kind"], (g["hi"] if g["kind"] == "acid" else g["lo"]), ph)
        for g in groups
    )
    lo_v, hi_v = min(shift_lo, shift_hi), max(shift_lo, shift_hi)

    straddle = any(
        r["f_ionized_range"][0] < 0.5 < r["f_ionized_range"][1] for r in rows
    )

    base_out.update(
        available=True,
        n_acid=len(acids),
        n_base=len(bases),
        groups=rows,
        f_neutral=round(f_neutral, 4),
        f_neutral_range=(round(f_neutral_lo, 4), round(f_neutral_hi, 4)),
        net_charge=round(net, 3),
        net_charge_range=(round(net_lo, 3), round(net_hi, 3)),
        charge_class=charge_class_of(f_neutral),
        zwitterion=bool(
            acids
            and bases
            and max((r["f_ionized"] for r in acids), default=0) > 0.5
            and max((r["f_ionized"] for r in bases), default=0) > 0.5
        ),
        logd_shift=round(shift, 3),
        logd_shift_range=(round(lo_v, 3), round(hi_v, 3)),
        bracket_straddles_ph=straddle,
    )
    return base_out


def logd_from_logp(logp, profile):
    """logP -> logD(pH) 的区间估计。

    公式：logD = logP − Σ_k log10(1 + 10^δ_k)，δ_k = pH−pKa（酸）/ pKa−pH（碱）。
    对多质子化体系这是"各位点相互独立"的近似（严格需考虑微观解离常数），
    误差量级与 pKa 区间本身同阶，因此**只报区间，不报点值**。
    """
    if not profile.get("available"):
        return dict(available=False, logD=float("nan"), logD_range=(float("nan"),) * 2)
    if logp is None or logp != logp:
        return dict(available=False, logD=float("nan"), logD_range=(float("nan"),) * 2)
    lo, hi = profile["logd_shift_range"]
    return dict(
        available=True,
        logD=round(logp + profile["logd_shift"], 2),
        logD_range=(round(logp + lo, 2), round(logp + hi, 2)),
        delta_from_logp=round(profile["logd_shift"], 2),
        note="logD 区间随 pKa 类别区间传播；不得当实测值",
    )


def limits_statement():
    return (
        "pKa 为**类别级文献区间**估计（±1 log 量级），不建模取代基/邻位位阻/糖苷化；"
        "只能用于电离分区与方向判断，禁止作为定量 logD 输入或写入任何 pKa 数值表。"
        "已知偏差：嘌呤/黄嘌呤环 N 高估碱性约 5 个 log 单位（结论仍为中性）；"
        "邻苯二酚第二解离（pKa≈13）未单列，会低估双阴离子比例。"
        "需要数值时用 Graph-pKa / 电位滴定，并通过 readback 通道回填。"
    )


def render(profile, compound_id=""):
    """一行人类可读摘要（CLI 打印用）。"""
    if not profile.get("available"):
        return "%s: SMILES 不可解析，电离状态未评估" % compound_id
    if profile["charge_class"] == "neutral_no_group":
        return "%s: 无可电离基团（pH %.1f 下中性）" % (compound_id, profile["ph"])
    if profile["charge_class"] == "permanently_charged":
        return "%s: 永久荷电（净电荷 %+.0f，季铵/两性离子，与 pH 无关）" % (
            compound_id,
            profile["net_charge"],
        )
    agg = {}
    for r in profile["groups"]:
        agg[r["name"]] = agg.get(r["name"], 0) + 1
    gs = ", ".join(
        "%s×%d(pKa %.1f)"
        % (k, v, next(r["pka"] for r in profile["groups"] if r["name"] == k))
        for k, v in agg.items()
    )
    return "%s: %s（净电荷 %+.2f [%+.2f,%+.2f]）%s%s | %s" % (
        compound_id,
        profile["charge_class"],
        profile["net_charge"],
        profile["net_charge_range"][0],
        profile["net_charge_range"][1],
        " 两性离子" if profile["zwitterion"] else "",
        " ⚠pKa区间跨分界" if profile["bracket_straddles_ph"] else "",
        gs,
    )
