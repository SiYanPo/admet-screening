# -*- coding: utf-8 -*-
"""10 状态灌注限制 PBPK + 安全裕度反推（筛查级）。

收编自项目脚本 e14_pbpk.py（v2.4.0），并把**安全端点接进暴露框架**：

  Margin = IC50 / Cmax         （fu 在分子分母同源，自动约掉；见 margin_table 注释）
  dose_at_margin = dose × Margin_now / Margin_target    （线性动力学下 Cmax ∝ dose）

三项强制自校验（playbook 要求，全部抓到过真 bug）：
  A. 质量守恒：总量 + 已消除(含粪便) 与剂量相对误差 < 1e-4
  B. 场景稳健性：CLint ×0.5/×2 下 Cmax 排序 Spearman ρ ≥ 0.9
  C. MC 收敛：n 与 n/2 的中位数相对差 < 0.05

单位约定：**全模型用 L/h、mg、mg/L**（首版用 mL/min 与 ka(/h) 混用，F 被压低 3.7 倍）。

已知局限（写进输出，不许省略）：
  * Kp 是 logP 启发的，不是 Rodgers–Poulin —— 影响 Vd 与 t½，对 Cmax 影响较小
  * 无肠肝循环、无转运体（糖苷的 OATP/SGLT1 是主控因素）
  * 输入（CLint/fu/Caco-2）通常是单组低置信 → 输出只能作方向与量级判断
"""

import csv
import io
import math
import os
import random
import statistics as st

import numpy as np
from scipy.integrate import solve_ivp
from scipy.stats import spearmanr

# ---------------- 参考生理（70 kg）----------------
_MLMIN_TO_LH = 60.0 / 1000.0
Q = {
    k: v * _MLMIN_TO_LH
    for k, v in dict(
        kidney=980.0,
        liver_art=364.0,
        gut=790.0,
        muscle=952.0,
        fat=280.0,
        rich=840.0,
        rest=1394.0,
    ).items()
}
CO = sum(Q.values())  # ≈ 336 L/h
V = dict(
    plasma=3.0,
    liver=1.8,
    kidney=0.31,
    muscle=28.0,
    fat=15.0,
    rich=4.0,
    rest=12.0,
    gut_wall=1.0,
    portal=0.1,
    lumen=0.25,
)
MPPGL, LIVER_G = 45.0, 1800.0
GFR = 125.0 * _MLMIN_TO_LH
KA_DEFAULT = 0.6
KB_DEFAULT = 0.4  # 胆汁排入肠腔（胆囊间歇排空）
FG_DEFAULT = 0.9

# Redfern 2003 的暂行安全边际（与 05_qa_gates G10 一致）
MARGIN_TIERS = [
    (10, "FAIL", "任何适应症都不足"),
    (30, "TIGHT", "仅危及生命适应症可接受"),
    (100, "OK", "常规可接受"),
    (float("inf"), "WIDE", "宽松（轻度适应症/CNS 亦可用）"),
]


ASSET_HERG = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "assets",
    "herg_reference_ic50.csv",
)

# 与"咖啡酰/肉桂酸酯"骨架最接近的实测锚点关键词（用于几何均值）
HERG_CLOSEST = ("caffeic acid", "CAPE", "cinnamate")


def load_herg_anchors(path=None):
    """读 assets/herg_reference_ic50.csv，返回有数值的锚点行。"""
    p = path or ASSET_HERG
    out = []
    if not os.path.exists(p):
        return out
    with io.open(p, encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            try:
                v = float(r.get("ic50_um") or "")
            except (TypeError, ValueError):
                continue
            out.append(
                dict(
                    name=(r.get("compound") or "").strip(),
                    cls=(r.get("class") or "").strip(),
                    ic50=v,
                    level=(r.get("provenance_level") or "").strip(),
                    note=r.get("note") or "",
                    source=r.get("source") or "",
                )
            )
    return out


def evidence_ic50_anchor(path=None, keywords=HERG_CLOSEST):
    """hERG IC50 的**证据锚点**（几何均值 + 范围），供 Margin 分析用。

    为什么需要它：hERG 的三个计算源（ADMETlab/ADMET-AI/vNN）都只给概率或类别，
    没有任何一家给 IC50（浓度）。于是 Margin 只能用假设 IC50 —— 而假设值直接决定
    结论（本项目 J 在 10 µM 下 22×TIGHT、在 2.5 µM 下 5.6×FAIL）。

    为什么只给"锚点"不给"精确值"（C84）：同一分子（curcumin）手工膜片钳 5.55 µM、
    自动化平台 >100 µM，**相差 20 倍**。所以 IC50 的不确定度 ≥10×，任何"精确 Margin"
    都是伪精度；本函数因此只返回点估计 + 范围，并强制调用方用档位表达。

    返回 dict(point, lo, hi, n, n_all, median_all, closest)。
    """
    rows = load_herg_anchors(path)
    if not rows:
        return dict(
            point=float("nan"),
            lo=float("nan"),
            hi=float("nan"),
            n=0,
            n_all=0,
            median_all=float("nan"),
            closest=[],
        )
    allv = sorted(r["ic50"] for r in rows)
    close = [r for r in rows if any(k.lower() in r["name"].lower() for k in keywords)]
    if close:
        point = math.exp(sum(math.log(r["ic50"]) for r in close) / len(close))
    else:
        point = st.median(allv)
    lo, hi = (
        (min(r["ic50"] for r in close), max(r["ic50"] for r in close))
        if close
        else (allv[0], allv[-1])
    )
    return dict(
        point=point,
        lo=lo,
        hi=hi,
        n=len(close),
        n_all=len(rows),
        median_all=st.median(allv),
        closest=[r["name"] for r in close],
    )


def in_phys_range_ok(clint_um, fu_pct):
    """与裁决层共用的物理边界（C80）：CLint ≥ 0、0 ≤ fu ≤ 100。

    负 CLint（ADMET-AI 在 APAP 上给 −4.3）会让 Eh<0、Fh>1，必须挡在 PBPK 之外。
    """
    try:
        cl, fu = float(clint_um), float(fu_pct)
    except (TypeError, ValueError):
        return False
    return 0.0 <= cl <= 5000.0 and 0.0 <= fu <= 100.0


def margin_tier(m):
    for hi, tag, desc in MARGIN_TIERS:
        if m < hi:
            return tag, desc
    return "WIDE", "宽松"


def kp_from_logp(clogp):
    base = max(0.0, clogp - 1.0)
    return dict(
        plasma=1.0,
        liver=1.0 + 0.1 * base,
        kidney=1.2,
        muscle=1.0 + 0.1 * base,
        fat=1.0 + 0.4 * base,
        rich=1.0 + 0.1 * base,
        rest=1.0 + 0.1 * base,
        gut_wall=1.0 + 0.1 * base,
        portal=1.0,
    )


def _rhs(t, y, p):
    # 状态：肠道腔/肠壁/门静脉/肝/血浆/肾/肌肉/脂肪/富血流/其余/**胆汁**/**累计消除**
    lum, gut, por, liv, pla, kid, mus, fat, rich, rest, bile, eli = y
    kp, clint, clr = p["kp"], p["clint_u"], p["clr"]
    fbile, kbile, fre = p["fbile"], p["kbile"], p["fre"]
    c_p = pla / V["plasma"]
    c = lambda a, k: a / (V[k] * kp[k])
    absorbed_in = p["ka"] * lum
    absorb = absorbed_in * p["fa"] * p["fg"]
    fecal = absorbed_in - absorb  # 未吸收必须记入消除汇，否则质量不守恒
    c_gw, c_por, c_liv = c(gut, "gut_wall"), c(por, "portal"), c(liv, "liver")
    c_kid, c_mus, c_fat = c(kid, "kidney"), c(mus, "muscle"), c(fat, "fat")
    c_rich, c_rest = c(rich, "rich"), c(rest, "rest")
    # 肝消除拆成"代谢"与"胆汁排泄"两条路（EHR，v2.5.0）。
    # 关键：**总肝清除不变**（= clint·c_liv），只是出口不同 —— 所以
    #   fre=0 时胆汁全进粪便，AUC 必须与"无 EHR"基线一致（可测的不变量）；
    #   fre>0 时药物经胆汁→肠腔→门静脉回到体循环，等效清除率下降 → AUC/t½ 上升。
    elim_liv_total = clint * c_liv
    elim_liv = elim_liv_total * (1.0 - fbile)
    bile_in = elim_liv_total * fbile
    bile_out = kbile * bile
    reabsorb = bile_out * fre
    bile_fecal = bile_out - reabsorb
    elim_kid = clr * c_kid
    venous = (
        (Q["liver_art"] + Q["gut"]) * c_liv
        + Q["kidney"] * c_kid
        + Q["muscle"] * c_mus
        + Q["fat"] * c_fat
        + Q["rich"] * c_rich
        + Q["rest"] * c_rest
    )
    return [
        -absorbed_in,
        absorb + Q["gut"] * c_p - Q["gut"] * c_gw,
        Q["gut"] * c_gw - Q["gut"] * c_por + reabsorb,
        (
            Q["liver_art"] * c_p
            + Q["gut"] * c_por
            - (Q["liver_art"] + Q["gut"]) * c_liv
            - elim_liv_total
        ),
        venous - CO * c_p,
        Q["kidney"] * (c_p - c_kid) - elim_kid,
        Q["muscle"] * (c_p - c_mus),
        Q["fat"] * (c_p - c_fat),
        Q["rich"] * (c_p - c_rich),
        Q["rest"] * (c_p - c_rest),
        bile_in - bile_out,
        elim_liv + elim_kid + fecal + bile_fecal,
    ]


def simulate(
    dose_mg,
    clint_um,
    fu,
    fa,
    clogp,
    ka=KA_DEFAULT,
    fg=FG_DEFAULT,
    tmax_h=240.0,
    n_out=4000,
    kp_scale=1.0,
    route="oral",
    fbile=0.0,
    kbile=KB_DEFAULT,
    fre=0.0,
):
    """fbile=0 时与 v2.4 完全等价（无肠肝循环），保证向后可比。

    fbile: 肝消除中进入胆汁的分数（0–1）
    kbile: 胆汁排入肠腔的一级速率（1/h），默认 0.4（胆囊间歇排空）
    fre  : 胆汁中药物被肠腔重吸收的分数（0–1）
    """
    kp = {k: 1.0 + (v - 1.0) * kp_scale for k, v in kp_from_logp(clogp).items()}
    p = dict(
        ka=ka,
        fa=fa,
        fg=fg,
        kp=kp,
        clint_u=clint_um * MPPGL * LIVER_G / 1000.0 * _MLMIN_TO_LH * fu,
        clr=GFR * fu,
        fbile=max(0.0, min(1.0, fbile)),
        kbile=kbile,
        fre=max(0.0, min(1.0, fre)),
    )
    y0 = [0.0] * 12
    y0[0 if route == "oral" else 4] = dose_mg
    sol = solve_ivp(
        _rhs,
        (0.0, tmax_h),
        y0,
        args=(p,),
        method="LSODA",
        rtol=1e-8,
        atol=1e-10,
        t_eval=np.linspace(0, tmax_h, n_out),
    )
    if not sol.success:
        raise RuntimeError("ODE 失败：%s" % sol.message)
    return dict(
        t=sol.t, c_pl=sol.y[4] / V["plasma"], total=sol.y.sum(axis=0), dose=dose_mg
    )


def metrics(res, mw):
    t, c = res["t"], res["c_pl"]
    cmax = float(c.max())
    auc = float(np.trapezoid(c, t))
    thalf = float("nan")
    tail = (c <= 0.10 * cmax) & (c >= 0.002 * cmax)
    if tail.sum() >= 6:
        x, yv = t[tail], np.log(c[tail])
        slope, intercept = np.polyfit(x, yv, 1)
        if slope < 0:
            pred = slope * x + intercept
            ss_res = float(((yv - pred) ** 2).sum())
            ss_tot = float(((yv - yv.mean()) ** 2).sum())
            if ss_tot > 0 and 1 - ss_res / ss_tot >= 0.90:
                thalf = -math.log(2) / slope
    return dict(
        cmax_uM=cmax / mw,
        cmax_nM=cmax / mw * 1e6,
        tmax_h=float(t[int(np.argmax(c))]),
        auc_nMh=auc / mw * 1e6,
        thalf_h=thalf,
    )


def mass_balance(res):
    return abs(float(res["total"][-1]) - res["dose"]) / res["dose"]


def bioavailable_fraction(dose_mg, clint_um, fu, fa, clogp, mw, **kw):
    """F = AUC_oral / AUC_iv（同一套参数，消除线性系统的比例偏差）。

    kw 透传给 simulate（如 fbile/fre），使 F 与 EHR 场景自洽。
    """
    a_o = metrics(simulate(dose_mg, clint_um, fu, fa, clogp, **kw), mw)["auc_nMh"]
    a_i = metrics(simulate(dose_mg, clint_um, fu, 1.0, clogp, route="iv", **kw), mw)[
        "auc_nMh"
    ]
    return a_o / a_i if a_i > 0 else float("nan")


def margin_table(cmax_nM, ic50_uM_list):
    """安全裕度 = IC50/Cmax。

    **为什么 fu 不用出现**：Margin 的严格定义是 IC50,u/Cmax,u；两个 u 用的是同一个 fu
    （同一化合物、同一血浆），约掉后就是 IC50/Cmax（总量口径）。若 IC50 来自不同
    蛋白基质（如含血清的膜片钳），必须显式换算——这一点写进 note，不能默认。
    """
    out = []
    for ic50 in ic50_uM_list:
        m = ic50 * 1000.0 / cmax_nM if cmax_nM > 0 else float("inf")
        tag, desc = margin_tier(m)
        out.append(dict(ic50_uM=ic50, margin=m, tier=tag, tier_desc=desc))
    return out


def dose_at_margin(dose_mg, cmax_nM, ic50_uM, target):
    """线性动力学：Cmax ∝ dose → 达到目标裕度所需的剂量。"""
    if cmax_nM <= 0:
        return float("inf")
    m_now = ic50_uM * 1000.0 / cmax_nM
    if m_now <= 0 or m_now == float("inf"):
        return float("inf")
    return dose_mg * m_now / target


def ehr_scan(
    comps,
    dose_mg,
    fbile_grid=(0.0, 0.2, 0.4, 0.6),
    fre_grid=(0.0, 0.5, 0.8),
    tmax_h=480.0,
    n_out=800,
    route="oral",
):
    """肠肝循环参数扫描：量化"缺 EHR"这一局限能把 AUC/t½ 放大多少倍。

    comps: [dict(compound_id, mw, clogp, clint_um, fu_pct, fa)]
    每个分子先跑基线（fbile=0，即无 EHR），再跑 fbile×fre 网格，
    返回相对基线的放大倍数（ratio）。**不做任何"最可能值"假设**——
    给的是"如果 EHR 存在，结论会移动多少"的边界。
    """
    out = []
    for c in comps:
        fu = float(c["fu_pct"]) / 100.0
        base = metrics(
            simulate(
                dose_mg,
                c["clint_um"],
                fu,
                c["fa"],
                c["clogp"],
                tmax_h=tmax_h,
                n_out=n_out,
                route=route,
            ),
            c["mw"],
        )
        for fb in fbile_grid:
            for fr in fre_grid:
                r = simulate(
                    dose_mg,
                    c["clint_um"],
                    fu,
                    c["fa"],
                    c["clogp"],
                    tmax_h=tmax_h,
                    n_out=n_out,
                    route=route,
                    fbile=fb,
                    fre=fr,
                )
                m = metrics(r, c["mw"])
                th_b, th = base["thalf_h"], m["thalf_h"]
                out.append(
                    dict(
                        compound_id=c["compound_id"],
                        fbile=fb,
                        fre=fr,
                        cmax_nM=round(m["cmax_nM"], 1),
                        auc_nMh=round(m["auc_nMh"], 1),
                        thalf_h=round(th, 2) if th == th else "",
                        cmax_ratio=(
                            round(m["cmax_nM"] / base["cmax_nM"], 3)
                            if base["cmax_nM"]
                            else ""
                        ),
                        auc_ratio=(
                            round(m["auc_nMh"] / base["auc_nMh"], 3)
                            if base["auc_nMh"]
                            else ""
                        ),
                        thalf_ratio=(
                            round(th / th_b, 3)
                            if (th == th and th_b == th_b and th_b)
                            else ""
                        ),
                        mass_err=float("%.1e" % mass_balance(r)),
                    )
                )
    return out


def scenario_rho(rows, fa_by, dose_mg, mult=2.0):
    """CLint ×mult 下的 Cmax 排序是否稳定（返回 Spearman ρ）。"""
    base = [r["cmax_nM"] for r in rows]
    alt = []
    for r in rows:
        res = simulate(
            dose_mg,
            r["clint_um"] * mult,
            r["fu_pct"] / 100.0,
            fa_by.get(r["compound_id"], 0.26),
            r["clogp"],
        )
        alt.append(metrics(res, r["mw"])["cmax_nM"])
    return spearmanr(base, alt).correlation


def mc_convergence(pairs, dose_mg, n=2000, seed=7, fa_span=None):
    """MC：返回 (full_medians, half_medians, 最大相对差)。

    pairs: [(compound_id, mw, clogp, clint_um, fu_pct)]
    """

    def run(k, s):
        rnd = random.Random(s)
        acc = {cid: [] for cid, *_ in pairs}
        for _ in range(k):
            for cid, mw, clogp, clint, fu_pct in pairs:
                fa_hi = (fa_span or {}).get(cid, 0.52)
                res = simulate(
                    dose_mg,
                    clint * rnd.uniform(0.6, 1.4),
                    fu_pct / 100.0 * rnd.uniform(0.7, 1.3),
                    rnd.uniform(0.0, fa_hi),
                    clogp,
                    kp_scale=rnd.uniform(0.7, 1.3),
                    tmax_h=96.0,
                    n_out=400,
                )
                acc[cid].append(metrics(res, mw)["cmax_nM"])
        return {k2: st.median(v) for k2, v in acc.items()}

    half, full = run(n // 2, seed), run(n, seed)
    rel = [abs(full[c] - half[c]) / full[c] for c in full if full[c] > 0]
    return full, half, (max(rel) if rel else float("nan"))


def mc_rank_probability(pairs, dose_mg, n=2000, seed=7, fa_span=None, top=3):
    """MC 参数不确定性下的**暴露排名概率**（移植自外部会话 exp8-A）。

    点估计只能给"谁第 1"，给不了"这个第 1 有多稳"。本函数对
    CLint/Fa/fu/Kp 同时抽样（同 mc_convergence 的分布），每次模拟重排 Cmax，
    输出每个分子的 P(前 top)/P(后 top)/平均名次/中位 Cmax。

    pairs: [(compound_id, mw, clogp, clint_um, fu_pct)]
    返回：按平均名次升序的 list[dict]。
    """
    rnd = random.Random(seed)
    rank_acc = {cid: [] for cid, *_ in pairs}
    cmax_acc = {cid: [] for cid, *_ in pairs}
    for _ in range(n):
        cur = {}
        for cid, mw, clogp, clint, fu_pct in pairs:
            fa_hi = (fa_span or {}).get(cid, 0.52)
            res = simulate(
                dose_mg,
                clint * rnd.uniform(0.6, 1.4),
                fu_pct / 100.0 * rnd.uniform(0.7, 1.3),
                rnd.uniform(0.0, fa_hi),
                clogp,
                kp_scale=rnd.uniform(0.7, 1.3),
                tmax_h=96.0,
                n_out=300,
            )
            cm = metrics(res, mw)["cmax_nM"]
            cur[cid] = cm
            cmax_acc[cid].append(cm)
        order = sorted(cur, key=lambda c: cur[c], reverse=True)  # Cmax 高 = 名次 1
        for i, c in enumerate(order, 1):
            rank_acc[c].append(i)
    out = []
    nn = len(pairs)
    for cid in rank_acc:
        rr = rank_acc[cid]
        out.append(
            dict(
                compound_id=cid,
                p_top=round(sum(1 for r in rr if r <= top) / len(rr), 3),
                p_bottom=round(sum(1 for r in rr if r > nn - top) / len(rr), 3),
                mean_rank=round(sum(rr) / len(rr), 2),
                median_cmax=round(st.median(cmax_acc[cid]), 1),
            )
        )
    out.sort(key=lambda r: r["mean_rank"])
    return out


# ===========================================================================
# 学术化层（v3.0.0）：公式自校验 / IVIVE 假设 / 申报口径 / EHR 机制前提 / CiPA
# ===========================================================================
QH = Q["liver_art"] + Q["gut"]  # 肝总血流 ≈ 90.6 L/h


def eh_well_stirred(fu, clint_b_lh, qh=None):
    """well-stirred 肝提取率 Eh = fu·CLint_b/(Qh + fu·CLint_b)。

    文献：Pang KS, Rowland M. J Pharmacokinet Biopharm. 1977;5(6):625-653.
          DOI: 10.1007/BF01059688
    关键点（本项目踩过的坑 C81）：**fu 乘在 CLint 上，不是乘在 Qh 上**。
    把 fu 乘到分母 Qh 上会让 Eh 从 0.34 变成 0.80（差 2.4 倍），
    而且量纲检查查不出来——只有教科书算例能抓住。
    """
    q = QH if qh is None else qh
    den = q + fu * clint_b_lh
    return (fu * clint_b_lh) / den if den > 0 else 0.0


def well_stirred_selfcheck(qh=None):
    """可执行的教科书自校验（不是注释，是函数）。

    三个解析解：
      ① fu=1、CLint_b=Qh        → Eh=0.500（半提取）
      ② fu=0.5、CLint_b=2·Qh    → Eh=0.500（fu 与 CLint 的乘积决定）
      ③ fu=0、任意 CLint        → Eh=0（无游离药物即无代谢）
    返回 dict(ok, cases=[...], qh)。
    """
    q = QH if qh is None else qh
    cases = [
        dict(name="fu=1, CLint_b=Qh", fu=1.0, clint_b=q, expect=0.5),
        dict(name="fu=0.5, CLint_b=2Qh", fu=0.5, clint_b=2 * q, expect=0.5),
        dict(name="fu=0", fu=0.0, clint_b=q, expect=0.0),
        dict(name="CLint→∞", fu=1.0, clint_b=1e9, expect=1.0),
    ]
    ok = True
    for c in cases:
        c["got"] = round(eh_well_stirred(c["fu"], c["clint_b"], q), 6)
        c["pass"] = abs(c["got"] - c["expect"]) < 1e-4
        ok = ok and c["pass"]
    return dict(ok=ok, cases=cases, qh=round(q, 2))


# IVIVE 缩放常数（Obach 2011, Curr Top Med Chem 11:450-466,
# DOI: 10.2174/156802611794480873）：必须显式声明的假设，不能藏在代码里
IVIVE_DEFAULTS = dict(mppgl=MPPGL, liver_g=LIVER_G, fu_mic=1.0, blood_plasma_ratio=1.0)


def ivive_assumptions(
    clint_um,
    fu_pct,
    fu_mic=None,
    mppgl=None,
    liver_g=None,
    qh=None,
    scale_factors=(0.5, 2.0),
):
    """从微粒体 CLint 到肝清除：把**全部假设摊开**并做敏感性。

    公式链（与 simulate 内部一致）：
      CLint,app (µL/min/mg) × MPPGL (mg/g) × 肝重 (g) → µL/min → ×0.06 → L/h
      CLint,u = CLint,app / fu_mic（微粒体结合校正）
      CLint,b = CLint,scaled × fu_p（血浆游离分数，近似换算到游离药物浓度基准）
      Eh      = fu·CLint_b/(Qh + fu·CLint_b)
      CLh     = Qh·Eh

    返回 dict(clint_app, fu_mic, clint_scaled_lh, clint_b_lh, eh, clh_lh,
             assumptions=[...], sensitivity=[...], caveat)。
    """
    d = dict(IVIVE_DEFAULTS)
    if mppgl is not None:
        d["mppgl"] = mppgl
    if liver_g is not None:
        d["liver_g"] = liver_g
    d["fu_mic"] = 1.0 if fu_mic is None else float(fu_mic)
    q = QH if qh is None else qh
    fu = max(0.0, min(1.0, float(fu_pct) / 100.0))

    def _scale(cl, fm):
        # µL/min/mg × mg/g × g = µL/min → L/h
        return cl / fm * d["mppgl"] * d["liver_g"] / 1000.0 * _MLMIN_TO_LH

    scaled = _scale(float(clint_um), d["fu_mic"])
    clint_b = scaled * fu
    eh = eh_well_stirred(fu, clint_b, q)
    assumptions = [
        dict(
            item="MPPGL（微粒体蛋白/肝重）",
            value=d["mppgl"],
            unit="mg/g",
            basis="文献默认 45；个体/物种差异可达 2×（Obach 2011）",
        ),
        dict(item="肝重", value=d["liver_g"], unit="g", basis="70 kg 成人 1800 g"),
        dict(
            item="fu_mic（微粒体结合）",
            value=d["fu_mic"],
            unit="-",
            basis="未实测 → 假定 1.0（**这是最可能低估 CLint 的假设**）",
        ),
        dict(
            item="血/浆比",
            value=d["blood_plasma_ratio"],
            unit="-",
            basis="未实测 → 假定 1.0；全血清除需按此换算",
        ),
        dict(
            item="肝血流 Qh",
            value=round(q, 2),
            unit="L/h",
            basis="灌注限制模型（Pang & Rowland 1977）",
        ),
    ]
    sens = []
    for f in scale_factors:
        for label, mult in (("CLint×%.1f" % f, f), ("CLint÷%.1f" % f, 1.0 / f)):
            cb = clint_b * mult
            e2 = eh_well_stirred(fu, cb, q)
            sens.append(
                dict(
                    variant=label,
                    clint_b_lh=round(cb, 2),
                    eh=round(e2, 3),
                    clh_lh=round(q * e2, 2),
                )
            )
    return dict(
        clint_app=round(float(clint_um), 2),
        fu_mic=d["fu_mic"],
        clint_scaled_lh=round(scaled, 2),
        clint_b_lh=round(clint_b, 2),
        eh=round(eh, 3),
        clh_lh=round(q * eh, 2),
        assumptions=assumptions,
        sensitivity=sens,
        caveat=(
            "IVIVE 的不确定度主要来自 fu_mic 与缩放因子，而不是 ODE；"
            '本函数只给"量级+敏感性"，不主张 regulator-grade 的 CLint'
        ),
    )


def ehr_prerequisites(
    clint_um, fu_pct, clogp, transporter_mediated=False, mw=None, qh=None
):
    """肠肝循环的机制前提（Fagerholm 2008, J Pharm Pharmacol 60:535-542,
    DOI: 10.1211/jpp.60.5.0001）。

    Fagerholm 的核心结论：**动物数据外推差、分子量阈值不成立**；
    EHC 需要 ①主动转运进胆汁/肠上皮 ②低代谢清除 ③中等以上渗透性。
    因此本函数不预测 fbile，只回答"这个分子**是否具备**发生 EHC 的前提"。
    """
    q = QH if qh is None else qh
    iv = ivive_assumptions(clint_um, fu_pct, qh=q)
    eh = iv["eh"]
    checks = []

    low_cl = eh < 0.30
    checks.append(
        dict(
            item="低代谢提取（Eh<0.30）",
            met=bool(low_cl),
            value="Eh=%.2f" % eh,
            why="高提取药物首过即被清除，胆汁排泄无足轻重",
        )
    )

    perm = clogp is not None and clogp >= 0.5
    checks.append(
        dict(
            item="中等以上渗透性（clogp≥0.5 作代理）",
            met=bool(perm),
            value="clogp=%s" % ("-" if clogp is None else round(clogp, 2)),
            why="重吸收需要跨肠上皮；极性过大则胆汁排入后直接随粪便走",
        )
    )

    checks.append(
        dict(
            item="主动转运参与（MRP2/BCRP/OATP 等）",
            met=bool(transporter_mediated),
            value="transporter_mediated=%s" % transporter_mediated,
            why="多数 EHC 阳性药物有转运体介导；纯被动扩散的 EHC 少见",
        )
    )

    if mw is not None:
        # 信息项：**不计入满足数**——Fagerholm 的结论恰恰是"MW 阈值不成立"，
        # 把它当成一条"满足"会让所有分子凭空多一票、永远 plausible。
        checks.append(
            dict(
                item="分子量阈值（<500 Da 也不能排除）",
                met=None,
                value="mw=%.0f" % mw,
                why="Fagerholm：MW 阈值不成立，不可据此排除 EHC（信息项不计分）",
            )
        )

    n_met = sum(1 for c in checks if c["met"] is True)
    if n_met >= 3:
        verdict, note = (
            "plausible",
            "机制前提基本具备：EHR 扫描的 fbile/fre 上界应认真对待",
        )
    elif n_met == 2:
        verdict, note = "uncertain", "部分前提具备：EHR 只能作敏感性分析，不作预测"
    else:
        verdict, note = "unlikely", "前提不足：EHR 大概率不是本分子的主要机制"
    return dict(
        verdict=verdict,
        n_met=n_met,
        n_checks=len(checks),
        checks=checks,
        note=note,
        citation="Fagerholm 2008 J Pharm Pharmacol 60:535-542",
    )


def qualification_statement(screening_level=True):
    """PBPK 的**申报口径**声明（FDA 2018 PBPK 指南 + EMA 2018 PBPK 指南）。

    FDA 区分 platform qualification（平台资格）与 model verification（模型验证），
    并要求"用 PBPK 替代临床 PK 需个案评估"；EMA 规定报告须含目的/平台资格/
    参数假设/模型开发/情景模拟/敏感性分析/预测性能/局限。
    本函数把这些**变成可打印的声明**，避免报告里含混其辞。
    """
    return dict(
        intended_use=(
            "筛选级：判断暴露量级与安全裕度是否值得进一步投入；"
            "**不用于**剂量选择、药物相互作用豁免或替代临床 PK"
        ),
        platform_qualification=(
            "本实现为自建 12 状态灌注限制模型，**未经**监管平台资格"
            "（qualification）；与 Simcyp/GastroPlus 无可比性声明"
        ),
        verification=(
            "已做三项内部校验：质量守恒（<1e-4）、情景稳健性（CLint×2 排序 "
            "ρ≥0.9）、蒙特卡洛折半收敛（相对偏差<0.10）；"
            "**未做**外部验证（无临床 PK 数据集）"
        ),
        sensitivity_analysis=(
            "已做：CLint×2 情景、IVIVE 缩放因子 ±2×、EHR 参数扫描、" "MC 参数抽样"
        ),
        predictive_performance=(
            "不可评估：无实测 Cmax/AUC 对照集；" "当前只能与同类文献量级比对"
        ),
        limitations=[
            ("fa 为外部给定或默认值，未经 Caco-2 校准（暴露侧最大不确定度）"),
            ("fu_mic 未实测，按 1.0 处理 → 可能低估 CLint"),
            ("EHR 的 fbile/fre 无实测来源，只给边界"),
            ("hERG 只有单通道 IC50 锚点，非 CiPA 多通道路线"),
        ],
        ema_report_sections=[
            "目的",
            "平台资格与模型开发",
            "参数与假设",
            "情景模拟",
            "敏感性分析",
            "预测性能",
            "局限",
        ],
        screening_level=screening_level,
    )


def herg_evidence_route():
    """hERG 风险证据路线（CiPA：Li et al. Clin Pharmacol Ther 2019;105:466-475）。

    只能锚定单通道 IC50 时，必须显式声明这是**简化路线**：
    CiPA 用多离子通道（hERG/Na_v1.5/Ca_v1.2 等）+ 人心肌细胞 in silico 模型，
    在独立验证集上同时满足排序与分类指标——"只看 hERG IC50"被证明不够。
    """
    return dict(
        route="single_channel_ic50_anchor",
        limitation=(
            '仅有 hERG 单通道 IC50 锚点：无法区分"阻断 hERG 但代偿性延长/不延长'
            '动作电位"的情形；糖苷类还可能是激动剂/部分阻断，尾电流法 IC50 '
            "会高估风险"
        ),
        cipa_route=(
            "CiPA：hERG + Na_v1.5 + Ca_v1.2 等多通道数据 → ORd 人心肌细胞模型 → "
            "动作电位时程/早后除极评分"
        ),
        data_needed=[
            "hERG 膜片钳 IC50（含尾电流）",
            "Na_v1.5 / Ca_v1.2 峰值电流抑制率",
            "（可选）hiPSC-CM 动作电位或 MEA",
        ],
        reporting_rule=(
            "只报档位（Redfern 10/30/100×）不报精确倍数；"
            "跨平台差异可达 20×（C84），同一分子不可跨平台比较"
        ),
    )


def write_academic(path, rows):
    """把每分子的 IVIVE/EHR 学术字段写一张表。"""
    cols = [
        "compound_id",
        "clint_app",
        "fu_mic",
        "clint_scaled_lh",
        "clint_b_lh",
        "eh",
        "clh_lh",
        "ehr_verdict",
        "ehr_n_met",
        "ehr_note",
    ]
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with io.open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return len(rows)
