# -*- coding: utf-8 -*-
"""PK/PD 连接层（v4.16）：把 PBPK 的 C(t) 接到药效上。

此前 skill 的暴露侧只算到 **Cmax 与 Margin = IC50/Cmax**（pbpk.margin_table）。
那个口径有三个结构性缺陷，本模块逐个补：
  1. **只用了峰值**：Cmax 相等而 C(t) 形状不同的两个给药方案，疗效/毒性可以完全不同；
  2. **没有时间维度**：`fT>IC50`（高于阈值的累积时间）才是时间依赖性杀菌/抑酶的
     真实驱动量，也是给药间隔设计的依据；
  3. **没有效应室**：多数药效相对血药浓度存在滞后（逆时针滞后环），直接拿 C 算效应
     会低估峰效应、错判 tmax。

本模块提供（全部为**机理连接**，不是新预测源）：
  · Hill/Emax 直接效应：E = E0 + Emax·C^n / (EC50^n + C^n)
  · 效应室（biophase）一阶连接：dCe/dt = ke0·(C − Ce)
  · 时间阈值指标：fT>EC50 / fT>EC90 的绝对时长与占给药间隔比例
  · 效应 AUC、峰效应、达峰时间
  · TMDD 最小模型（靶点介导药物处置）：**缺参数就报错**，不许用默认值凑

硬约束：
  · EC50 必须与 C 同量纲。C 用 µg/mL(=mg/L)，EC50 常用 µM → 必须给 mw 换算；
    量纲不一致时**直接抛 PDParameterError**，不静默按数字算（C71 的教训）。
  · 不做群体 PK（PopPK）参数估计——那是 nlmixr2/Pharmpy 的活，本模块只导出数据集
    （见 adt/interop.py）并接收回填的个体参数。
  · 输出只到"给定机理假设下的 PD 指标"，**不得**表述为临床疗效预测。
"""

from __future__ import division

import math

import numpy as np

__all__ = [
    "PDParameterError",
    "c_mg_per_L_to_uM",
    "hill",
    "effect_compartment",
    "time_above",
    "pd_metrics",
    "tmdd_minimal",
    "qualification_statement",
]


class PDParameterError(ValueError):
    """PD 参数缺失/量纲不一致。必须显式失败，不许用默认值兜底。"""


def c_mg_per_L_to_uM(c, mw):
    """mg/L(=µg/mL) -> µmol/L。mw 单位 g/mol。"""
    if mw is None or mw != mw or mw <= 0:
        raise PDParameterError("换算 C(mg/L)->µM 必须给 mw(g/mol)，收到 %r" % (mw,))
    return np.asarray(c, dtype=float) * 1000.0 / float(mw)


def hill(c, ec50, emax, n=1.0, e0=0.0):
    """Hill/Emax。c 与 ec50 必须同量纲。"""
    if ec50 is None or ec50 != ec50 or ec50 <= 0:
        raise PDParameterError("EC50 必须 >0，收到 %r" % (ec50,))
    if n is None or n != n or n <= 0:
        raise PDParameterError("Hill 系数 n 必须 >0，收到 %r" % (n,))
    c = np.asarray(c, dtype=float)
    cn = np.power(np.clip(c, 0.0, None), n)
    return e0 + emax * cn / (ec50**n + cn)


def effect_compartment(t, c, ke0):
    """一阶效应室：dCe/dt = ke0·(C − Ce)，梯形离散（对线性系统二阶精度）。

    ke0 单位 1/h；ke0→∞ 退化为直接效应（Ce→C）。
    """
    if ke0 is None or ke0 != ke0 or ke0 <= 0:
        raise PDParameterError("ke0 必须 >0（1/h），收到 %r" % (ke0,))
    t = np.asarray(t, dtype=float)
    c = np.asarray(c, dtype=float)
    if t.shape != c.shape or t.size < 2:
        raise PDParameterError("t/c 形状不一致或点数 <2")
    ce = np.empty_like(c)
    ce[0] = 0.0
    for i in range(1, t.size):
        dt = t[i] - t[i - 1]
        if dt <= 0:
            raise PDParameterError("时间轴必须严格递增（第 %d 点 dt=%g）" % (i, dt))
        e = math.exp(-ke0 * dt)
        ce[i] = ce[i - 1] * e + 0.5 * (c[i - 1] + c[i]) * (1.0 - e)
    return ce


def time_above(t, c, thr):
    """高于阈值的累积时长 + 首次/末次跨越时刻 + 以首末时间跨度计的占比。"""
    t = np.asarray(t, dtype=float)
    c = np.asarray(c, dtype=float)
    if t.size < 2 or t.shape != c.shape:
        raise PDParameterError("time_above 需要 ≥2 点且 t/c 等长")
    above = c >= thr
    if not above.any():
        span = float(t[-1] - t[0])
        return dict(
            duration_h=0.0,
            fraction_of_horizon=0.0 if span > 0 else float("nan"),
            t_first=float("nan"),
            t_last=float("nan"),
        )
    idx = np.where(above)[0]
    first_i, last_i = int(idx[0]), int(idx[-1])

    def _cross(i0, i1):
        """在 [i0, i1] 段内线性插值求穿越时刻。"""
        c0, c1 = c[i0], c[i1]
        if c1 == c0:
            return float(t[i0])
        frac = (thr - c0) / (c1 - c0)
        frac = min(max(frac, 0.0), 1.0)
        return float(t[i0] + frac * (t[i1] - t[i0]))

    t_first = float(t[first_i]) if first_i == 0 else _cross(first_i - 1, first_i)
    t_last = float(t[last_i]) if last_i == t.size - 1 else _cross(last_i, last_i + 1)
    dur = max(t_last - t_first, 0.0)
    span = float(t[-1] - t[0])
    return dict(
        duration_h=dur,
        fraction_of_horizon=(dur / span if span > 0 else float("nan")),
        t_first=t_first,
        t_last=t_last,
    )


def pd_metrics(t, c, ec50, emax, n=1.0, e0=0.0, ke0=None, interval_h=None, label=""):
    """给定 C(t) 的 PD 指标集。

    ec50/emax/e0 与 c 同量纲；ke0 给了就走效应室，否则直接效应。
    interval_h：给药间隔（h），用于把 fT>EC50 折算成"每间隔覆盖比例"。
    """
    if interval_h is not None and interval_h <= 0:
        raise PDParameterError("interval_h 必须 >0")
    t = np.asarray(t, dtype=float)
    c = np.asarray(c, dtype=float)
    if t.size < 3:
        raise PDParameterError("PD 指标需要 ≥3 个时间点（实收 %d）" % t.size)
    ec90 = ec50 * 9.0 ** (1.0 / float(n))  # 90% 效应浓度
    ce = effect_compartment(t, c, ke0) if ke0 else c
    eff = hill(ce, ec50, emax, n=n, e0=e0)

    ft50 = time_above(t, ce, ec50)
    ft90 = time_above(t, ce, ec90)
    i_peak = int(np.argmax(eff))
    cmax = float(np.max(ce))
    frac_int = ""
    if interval_h:
        frac_int = round(min(ft50["duration_h"] / float(interval_h), 1.0), 3)

    return dict(
        label=label,
        n_points=int(t.size),
        driver="effect_compartment(ke0=%.3g/h)" % ke0 if ke0 else "plasma_direct",
        cmax_uM_like=round(cmax, 4),
        ec50=ec50,
        ec90=round(ec90, 4),
        emax=emax,
        hill_n=n,
        t_above_ec50_h=round(ft50["duration_h"], 3),
        t_above_ec90_h=round(ft90["duration_h"], 3),
        frac_interval_above_ec50=frac_int,
        frac_horizon_above_ec50=(
            round(ft50["fraction_of_horizon"], 3)
            if ft50["fraction_of_horizon"] == ft50["fraction_of_horizon"]
            else ""
        ),
        effect_auc=round(float(np.trapezoid(eff, t)), 3),
        effect_peak=round(float(eff[i_peak]), 3),
        t_peak_effect_h=round(float(t[i_peak]), 3),
        effect_min=round(float(np.min(eff)), 3),
        plateau=(
            abs(float(eff[i_peak]) - float(eff[-1])) < 0.05 * max(abs(emax), 1e-12)
        ),
        status="ok",
    )


def tmdd_minimal(
    t, c_nM, r0_nM, kon_per_nM_per_h, koff_per_h, kint_per_h, kdeg_per_h, label=""
):
    """靶点介导药物处置（TMDD）最小模型。

    dR/dt  = ksyn − kon·C·R + koff·RC − kdeg·R
    dRC/dt = kon·C·R − koff·RC − kint·RC
    dC/dt  = −kon·C·R + koff·RC   （只保留结合项；处置项由 PBPK 提供，这里不重复）

    **缺任何一个参数都抛 PDParameterError**：TMDD 的参数（R0、kon/koff/kint、kdeg）
    在 ADMET 流程里通常完全没有，用默认值凑出来的曲线没有意义。
    """
    need = dict(
        r0_nM=r0_nM,
        kon_per_nM_per_h=kon_per_nM_per_h,
        koff_per_h=koff_per_h,
        kint_per_h=kint_per_h,
        kdeg_per_h=kdeg_per_h,
    )
    miss = [k for k, v in need.items() if v is None or v != v or v <= 0]
    if miss:
        raise PDParameterError(
            "TMDD 需要全部 5 个正参数，缺/非法：%s。"
            "这些量通常只能来自靶点表达与 SPR/细胞实验 —— "
            "不许用默认值凑（凑出来的占用率曲线会被误读成有效结论）" % ", ".join(miss)
        )
    t = np.asarray(t, dtype=float)
    c = np.asarray(c_nM, dtype=float)
    if t.size < 3 or t.shape != c.shape:
        raise PDParameterError("TMDD 需要 ≥3 点且 t/c 等长")
    ksyn = kdeg_per_h * r0_nM

    def rhs(_t, y):
        R, RC = max(y[0], 0.0), max(y[1], 0.0)
        # 自由药物浓度：用输入曲线插值，不做药物自身的质量守恒（那是 PBPK 的职责）
        idx = np.searchsorted(t, _t, side="right") - 1
        idx = min(max(idx, 0), t.size - 2)
        frac = (_t - t[idx]) / (t[idx + 1] - t[idx]) if t[idx + 1] > t[idx] else 0.0
        Cf = c[idx] + frac * (c[idx + 1] - c[idx])
        on = kon_per_nM_per_h * Cf * R
        off = koff_per_h * RC
        return [ksyn - on + off - kdeg_per_h * R, on - off - kint_per_h * RC]

    from scipy.integrate import solve_ivp

    sol = solve_ivp(
        rhs,
        (float(t[0]), float(t[-1])),
        [r0_nM, 0.0],
        t_eval=t,
        method="LSODA",
        rtol=1e-8,
        atol=1e-12,
    )
    if not sol.success:
        raise RuntimeError("TMDD ODE 失败：%s" % sol.message)
    R, RC = sol.y[0], sol.y[1]
    occ = RC / np.maximum(R + RC, 1e-12)
    return dict(
        label=label,
        model="tmdd_minimal",
        r0_nM=r0_nM,
        kon=kon_per_nM_per_h,
        koff=koff_per_h,
        kint=kint_per_h,
        kdeg=kdeg_per_h,
        ksyn=round(ksyn, 6),
        occupancy_peak=round(float(occ.max()), 4),
        occupancy_min=round(float(occ.min()), 4),
        t_peak_occupancy_h=round(float(t[int(np.argmax(occ))]), 3),
        target_depletion_pct=round(100.0 * (1.0 - float(R.min() / r0_nM)), 2),
        status="ok",
        limits="最小 TMDD：未建模药物处置项、未建模二价结合/内吞饱和；"
        "参数须来自 SPR 或靶点表达实测",
    )


def qualification_statement():
    return (
        "PD 指标是**机理假设下的推演**，不是疗效/毒性预测："
        "EC50/Emax 来自体外或同类物外推时，fT>EC50 只反映'在该假设下暴露覆盖阈值的时间'；"
        "Hill 系数固定时 fT>EC90 由 EC90=EC50·9^(1/n) 反算，不是独立信息；"
        "未做 ORd/AP 或疾病进展模型，不得外推到临床终点。"
    )
