# -*- coding: utf-8 -*-
"""外部 PK/PD 工具互操作桥（v4.18）：把 skill 的参数与数据交给真正的建模软件。

为什么是"桥"而不是"重写"：
  PK-Sim / MoBi（Open Systems Pharmacology，GPLv2）是 .NET 桌面套件，
  nlmixr2 是 R 包，Pharmpy 是 Python 包但面向 NONMEM 模型文件。
  本 skill 既没有、也不应该把它们的求解器重写一遍 —— 那是另一个软件的职责。
  真正缺的是**参数与数据能无损进出**：单位、命名、EVID/CMT 约定、缺失值编码，
  这些错了，模型跑出来的东西没人能复核。

提供三件事：
  1. `pk_sim_compounds()`：把 skill 已有参数（MW / logP / fu / pKa / 溶解度 /
     CLint / 渗透性）映射成 PK-Sim 化合物参数表（含单位与来源字段），
     附 `unmapped` 列表——**没映射上的参数必须显式列出，不许静默丢**；
  2. `nonmem_dataset()`：生成 NONMEM / nlmixr2 / Pharmpy 通用的进阶事件数据集
     （ID/TIME/AMT/EVID/CMT/DV/MDV/RATE/II/ADDL/SS），并做契约校验；
  3. `nlmixr2_skeleton()`：给出可直接改的 R 模型骨架（1 房口服 + Emax）。

诚实边界（v4.21 起**分级**，不再是一个布尔 False）：
  · `pk_sim_cli_snap_passed` —— PK-Sim 12.3.173 真机 `snap -p` 往返，
    **仅化合物层** 32/32 逐位一致；**仿真层未闭环**（见下）；
  · `pharmpy_dataset_ok` —— Pharmpy 2.3.0 `create_datainfo` 真读，
    11228 行 / 12 列 / 28 受试者 / 28 次给药；
  · `nlmixr2_fit_passed` —— R 4.5.3 + nlmixr2 5.0.0 + rxode2 5.0.2，
    FOCEI 60 s 收敛（bobyqa 正常退出）。
  · **仿真层未闭环的真因（2026-11-18 第一手复测，勘误）**：本 skill 的
    `pk_sim_snapshot()` 只构造 `Compounds`，`Simulations` 生来就是 `[]`——**不是被 CLI 丢**。
    CLI `snap -p` 本身**支持**仿真往返：官方 Midazolam 快照完整往返后 SQLite
    `SIMULATIONS` 表实测 =37（ObservedData=115、Protocols=33 全部保留）；
    裁到 1 条并保留其引用 ObservedData 时 =1。
    若清空仿真引用的 ObservedData，PK-Sim 报 `Cannot load Simulation`
    （`WeightedObservedData..ctor` 空引用）但**退出码仍为 0**、仿真被跳过——
    这才是"退出码 0 + Project saved 却无仿真"的确切机制。
    验收必须看**产物计数**（读 `.pksim5` 的 `SIMULATIONS` 表），不看退出码或日志字样。
  · 数据集里 ID = 化合物，不是人体受试者：eta 只能报"化合物间变异"，
    **不得**当 IIV/BSV；240 h 窗口内 cl 不可辨识。
"""

from __future__ import division

import csv
import io

__all__ = [
    "PKSIM_FIELDS",
    "NONMEM_FIELDS",
    "pk_sim_compounds",
    "write_pk_sim_compounds",
    "nonmem_dataset",
    "nonmem_id_map",
    "write_nonmem",
    "validate_nonmem",
    "cmt_layout",
    "cmt_split_ok",
    "mask_nonpositive_obs",
    "nlmixr2_skeleton",
    "pk_initials",
    "INTEROP_NOTICE",
    "pk_sim_snapshot",
    "write_pk_sim_snapshot",
    "PK_SIM_SNAPSHOT_VERSION",
]

INTEROP_NOTICE = (
    "导出物已在外层工具真机验证，但**分级**：PK-Sim 化合物层 snap 往返一致"
    "（仿真层未闭环）、Pharmpy 真读数据集、nlmixr2 FOCEI 收敛。"
    "仍须人工核对单位与列名，并在模型里记录 context of use（见 adt/pbpk_qualify）。"
    "另注意：数据集 ID=化合物而非个体，eta 不是 IIV。"
)

# PK-Sim 化合物参数（小分子）：(PK-Sim 参数名, 单位, 本 skill 来源字段, 备注)
PKSIM_FIELDS = [
    ("Name", "", "compound_id", "唯一标识；PK-Sim 用它做化合物键"),
    ("Molecular weight", "g/mol", "mw", "由 RDKit 描述符计算"),
    (
        "Lipophilicity",
        "LogP",
        "clogp",
        "RDKit Crippen；PK-Sim 内可选方法学，导入后按方法重算",
    ),
    (
        "Compound type",
        "",
        "ionization_class",
        "neutral/acid/base/ampholyte/zwitterion —— 由 adt/ionization 给出",
    ),
    ("pKa", "", "pka_values", "多个值用分号分隔；类别级文献估计，非实测（见 limits）"),
    (
        "Fraction unbound (plasma)",
        "",
        "fu_plasma",
        "来自 ADMETlab/ADMET-AI 的 ppb 换算；单源时标低置信",
    ),
    (
        "Solubility at pH 7.4",
        "mg/L",
        "solubility_ph74",
        "常缺；缺则 PK-Sim 用内置 pH-溶解度模型",
    ),
    ("Specific intestinal permeability", "cm/min", "", "**常缺**，见 unmapped"),
    ("Caco-2 permeability", "10^-6 cm/s", "caco2_papp", "log10 值需先换算成线性"),
    (
        "Fraction unbound (microsomes)",
        "",
        "fu_mic",
        "由 CLint 反演的假设值，注意循环论证",
    ),
    (
        "CLint (microsomes)",
        "µL/min/mg protein",
        "clint_microsome",
        "IVIVE 输入；种属须一致",
    ),
    ("Renal clearance", "L/h", "clr", "本 skill 默认 GFR×fu 近似值，标为 assumption"),
]

NONMEM_FIELDS = [
    "ID",
    "TIME",
    "AMT",
    "EVID",
    "CMT",
    "DV",
    "MDV",
    "RATE",
    "II",
    "ADDL",
    "SS",
    "DVID",
]

# OSP 快照版本号：**实测**取自官方 PK-Sim 模型文件
# （Midazolam-Model v2.0, raw.githubusercontent.com/Open-Systems-Pharmacology/
#  Midazolam-Model/v2.0/Midazolam-Model.json），与 PK-Sim 12.3.173 的 snap 命令兼容。
# 版本号写错会被 CLR 反序列化直接拒绝，所以它是硬编码的常量而非"猜一个"。
PK_SIM_SNAPSHOT_VERSION = 80


def _num(v):
    try:
        f = float(v)
        return f
    except (TypeError, ValueError):
        return ""


def pk_sim_compounds(params_by_cid, pka_by_cid=None, ion_class_by_cid=None):
    """把 skill 参数映射成 PK-Sim 化合物行。

    params_by_cid: {cid: {mw, clogp, fu_plasma(0-1), solubility_ph74, caco2_papp,
                          fu_mic, clint_microsome, clr, ...}}
    返回 (rows, unmapped)：unmapped 明确列出"哪些 PK-Sim 参数我们给不出"。
    """
    pka_by_cid = pka_by_cid or {}
    ion_class_by_cid = ion_class_by_cid or {}
    rows, unmapped_global = [], []
    for cid, p in params_by_cid.items():
        pka_vals = pka_by_cid.get(cid) or []
        if isinstance(pka_vals, (int, float)):
            pka_vals = [pka_vals]
        row = dict(
            compound_id=cid,
            mw=round(_num(p.get("mw")), 2) if _num(p.get("mw")) != "" else "",
            clogp=round(_num(p.get("clogp")), 3) if _num(p.get("clogp")) != "" else "",
            ionization_class=ion_class_by_cid.get(cid, ""),
            pka_values=";".join("%.2f" % float(x) for x in pka_vals),
            fu_plasma=_num(p.get("fu_plasma")),
            solubility_ph74=_num(p.get("solubility_ph74")),
            caco2_papp=_num(p.get("caco2_papp")),
            fu_mic=_num(p.get("fu_mic")),
            clint_microsome=_num(p.get("clint_microsome")),
            clr=_num(p.get("clr")),
        )
        rows.append(row)
    for pk_name, _unit, src, note in PKSIM_FIELDS:
        if not src:
            unmapped_global.append((pk_name, note))
    missing_fields = []
    for src in ("solubility_ph74", "caco2_papp", "fu_mic"):
        if rows and not any(r.get(src) not in ("", None) for r in rows):
            missing_fields.append(src)
    return rows, dict(
        fields_without_source=unmapped_global,
        columns_empty_in_batch=missing_fields,
        notice=INTEROP_NOTICE,
    )


def write_pk_sim_compounds(path, rows):
    """写 PK-Sim 化合物参数表（CSV，UTF-8-BOM 以便 Excel 直开）。"""
    if not rows:
        raise ValueError("没有可导出的化合物")
    cols = list(rows[0].keys())
    with io.open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return path


def nonmem_id_map(records):
    """compound_id -> 整数 ID（NONMEM/PsN/nlmixr2 **要求 ID 是整数**）。

    这是实测逼出来的：pharmpy 2.3 读 `ID=A-1` 直接
    `ValueError: invalid literal for int()`。用字符串 ID 的数据集在真实工具里
    **根本读不进去**，而本模块原先的契约校验只看 EVID/MDV/排序，抓不到这一条。
    映射按字典序稳定生成，同时落 `nonmem_id_map.csv`，保证结果可回溯。
    """
    ids = sorted({str(r["id"]) for r in records})
    return {cid: i + 1 for i, cid in enumerate(ids)}


def nonmem_dataset(records, default_cmt=1, default_ii=0.0, id_map=None, obs_cmt=None):
    """生成 NONMEM/nlmixr2 数据集行。

    records: list[dict(id, time, amt=..., dv=..., evid=None, cmt=None,
                       rate=0, ii=..., addl=0, ss=0, dvid=1)]
    EVID 缺省推导：amt>0 -> 1（给药），否则 0（观测）；无 dv 的观测行 MDV=1。
    id_map: 给了就用它把 compound_id 换成整数；不给则内部按字典序生成。
    obs_cmt: 观测行的腔号。**口服布局必须给**（给药 CMT=1 灌胃、观测 CMT=2 中央室）。

    v4.21 修复：此前给药与观测共用一个 `default_cmt`，产出数据集在
    **NONMEM ADVAN2 下会被读成"观测在胃肠道"**（吸收相被吃掉、V 荒谬地小），
    而 nlmixr2 单端点模型不按 CMT 匹配输出，所以"看起来能跑"。
    这是"能跑"与"算对"的差别 —— 因此把观测腔拆成独立参数。
    """
    id_map = id_map or nonmem_id_map(records)
    out = []
    for r in records:
        amt = _num(r.get("amt")) or 0.0
        dv = _num(r.get("dv"))
        evid = r.get("evid")
        if evid is None:
            evid = 1 if amt > 0 else 0
        mdv = r.get("mdv")
        if mdv is None:
            mdv = 1 if (evid == 1 or dv == "") else 0
        if r.get("cmt") not in (None, ""):
            cmt = int(r["cmt"])
        elif int(evid) == 0 and obs_cmt is not None:
            cmt = int(obs_cmt)
        else:
            cmt = int(default_cmt)
        out.append(
            dict(
                ID=id_map[str(r["id"])],
                TIME=_num(r.get("time")),
                AMT=amt,
                EVID=int(evid),
                CMT=cmt,
                DV=("" if dv == "" else dv),
                MDV=int(mdv),
                RATE=_num(r.get("rate")) or 0,
                II=_num(r.get("ii")) or default_ii,
                ADDL=int(r.get("addl") or 0),
                SS=int(r.get("ss") or 0),
                DVID=int(r.get("dvid") or 1),
            )
        )
    return out


def mask_nonpositive_obs(rows, floor=0.0):
    """把"非正观测"标成 MDV=1（不进目标函数），返回被屏蔽的条数。

    v4.21 实测教训：pbpk 曲线在 12–30 h 已衰减到 0，之后几百个时点的 DV 是
    **ODE 的数值零，不是测量值**。把它们当真实观测喂进去会：
      · 用 370/400 个零支配目标函数 → 参数被拉向"拟合零"；
      · 加性残差被压到接近 0，SE 假性变小；
      · 实测后果：FOCEI 报 bobyqa 正常退出，但 tcl 停在初值不动、
        tv 估成 2978 L（半衰期 344 h，与曲线 1.6 h 差 200 倍）——
        **"收敛"不等于"算对"**。

    真正的 BLQ 处理要走 CENS=1 的删失似然；本模块不假装能做，
    只把非正观测排除并**报出条数**，让人知道有效样本有多少。
    """
    n = 0
    for r in rows:
        if r["EVID"] != 0 or r["DV"] in ("", None):
            continue
        try:
            dv = float(r["DV"])
        except (TypeError, ValueError):
            continue
        if dv <= floor:
            r["MDV"] = 1
            n += 1
    return n


def cmt_layout(rows):
    """每个受试者的给药腔 / 观测腔。返回 {ID: (dose_cmts, obs_cmts)}。"""
    lay = {}
    for r in rows:
        d, o = lay.setdefault(r["ID"], (set(), set()))
        (d if r["EVID"] == 1 else o).add(r["CMT"])
    return lay


def cmt_split_ok(rows):
    """给药腔与观测腔是否**完全分离**（两侧都非空且不相交）。"""
    for _cid, (d, o) in cmt_layout(rows).items():
        if not d or not o or (d & o):
            return False
    return True


def validate_nonmem(rows, expect_cmt_split=False):
    """契约校验：返回问题列表（空=通过）。这些错会让 NONMEM/nlmixr2 静默算错。

    expect_cmt_split=True 时额外要求"给药腔与观测腔不相交"——口服布局
    （NONMEM ADVAN2 / nlmixr2 depot+central）下这是硬要求：同腔会让
    NONMEM 把观测当成胃肠道浓度，吸收相被吃掉而 RSE 依然"好看"。
    """
    problems = []
    if not rows:
        return ["数据集为空"]
    if expect_cmt_split and not cmt_split_ok(rows):
        lay = cmt_layout(rows)
        bad = {
            k2: (sorted(d), sorted(o))
            for k2, (d, o) in lay.items()
            if (d & o) or (not d) or (not o)
        }
        problems.append(
            "给药腔与观测腔未分离（前 3 例：%s）。口服布局必须给药 CMT=1 / "
            "观测 CMT=2，否则 NONMEM ADVAN2 会把观测读成胃肠道浓度"
            % (list(bad.items())[:3],)
        )
    seen = {}
    for i, r in enumerate(rows, 1):
        # NONMEM/Pharmpy 会把 ID 当整数解析：字符串 ID 会让数据集**读不进去**
        if not str(r["ID"]).strip().isdigit():
            problems.append(
                "row %d: ID=%r 不是整数（NONMEM/pharmpy 会解析失败，"
                "请用 nonmem_id_map 映射）" % (i, r["ID"])
            )
        if r["EVID"] == 1 and not r["AMT"]:
            problems.append("row %d: EVID=1 但 AMT=0（NONMEM 会当无效给药）" % i)
        if r["EVID"] == 0 and r["DV"] == "" and r["MDV"] == 0:
            problems.append("row %d: 观测行无 DV 却 MDV=0（MDV 必须置 1）" % i)
        if r["EVID"] == 0 and r["AMT"]:
            problems.append("row %d: 观测行带 AMT（应拆成两条记录）" % i)
        if r["EVID"] == 0 and r["MDV"] == 0 and r["DV"] not in ("", None):
            try:
                if float(r["DV"]) <= 0:
                    problems.append(
                        "row %d: 非正观测 (DV=%s) 当真实值参与拟合——模拟曲线的"
                        "数值零不是测量值，请用 mask_nonpositive_obs 置 MDV=1"
                        % (i, r["DV"])
                    )
            except (TypeError, ValueError):
                pass
        if r["II"] and not r["ADDL"] and r["EVID"] == 1:
            problems.append("row %d: 给了 II 但 ADDL=0（单次给药，II 无意义）" % i)
        key = (r["ID"], r["TIME"], r["EVID"], r["CMT"])
        if key in seen:
            problems.append(
                "row %d: 与 row %d 键重复 (ID,TIME,EVID,CMT)" % (i, seen[key])
            )
        seen[key] = i
    ids = {r["ID"] for r in rows}
    for cid in ids:
        ts = [r["TIME"] for r in rows if r["ID"] == cid]
        if ts != sorted(ts):
            problems.append("ID=%s: TIME 未排序（NONMEM 要求按 ID,TIME 排序）" % cid)
        if not any(r["EVID"] == 1 for r in rows if r["ID"] == cid):
            problems.append("ID=%s: 没有任何给药记录（EVID=1）" % cid)
    return problems


def write_nonmem(path, rows):
    with io.open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=NONMEM_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return path


_NLMIXR2 = """# nlmixr2 骨架 —— validated_against_tool = nlmixr2_fit_passed
# 实测环境：R 4.5.3 + nlmixr2 5.0.0 + rxode2 5.0.2（conda-forge，Windows）
# 实测结果：11228 行 / 28 受试者 / FOCEI 60 s 收敛，"Normal exit from bobyqa"
# 安装：install.packages("nlmixr2")（运行时编译模型还需要 Rtools）
library(nlmixr2)

# 两个由实测暴露、必须写进报告的前提（不要把这份结果当常规 popPK）：
# 1) 本数据集的 ID = 化合物，不是人体受试者。eta 估出来的是"化合物间变异"，
#    不得当作 IIV/BSV 报告。实测 eta 收缩为负（-72% / -281%）正是这个原因。
# 2) 实测辨识性只有 V：V=1433 L（RSE 3.8%，95%CI 1330–1540）可估；
#    CL / ka / F 的 95%CI 跨四个数量级（RSE 3.6e3% / 2.0e6%），是 flip-flop
#    与"曲线几乎无噪声"共同导致的不可辨识。这些数字不要当估计结果写进报告。
#    另：曲线在 12–30 h 已衰减到 0，后续时点是 ODE 数值零，导出时已置 MDV=1；
#    真正做 BLQ 需 CENS=1 的删失似然，本骨架不假装能处理。

{init_note}

f <- function() {{
  ini({{
    tcl   <- {cl_init}      # L/h
    tv    <- {v_init}       # L
    tka   <- {ka_init}      # 1/h
    tf    <- {f_init}       # 生物利用度（口服单次给药下与 V 不可同时辨识 → 建议 fix(1.0)）
    addSd <- {add_sd}       # 加性误差（浓度单位）
    eta_cl ~ {omega}
    eta_v  ~ {omega}
  }})
  model({{
    cl <- tcl * exp(eta_cl)
    v  <- tv  * exp(eta_v)
    ka <- tka
    f  <- tf
    d/dt(depot)      <- -ka * depot
    d/dt(central)    <-  ka * depot - (cl / v) * central
    cp <- central / v
    cp ~ add(addSd)
  }})
}}

# 读入 adt.interop 导出的数据集（UTF-8 无 BOM；给药 CMT=1 胃肠道 / 观测 CMT=2 中央室）
# 若用 --obs-cmt / --dose-cmt 改过腔号，以 nonmem_dataset.csv 的 CMT 列实际值为准。
d <- read.csv("{data_path}")

fit <- nlmixr2(f, d, est = "focei", control = foceiControl(print = 0))
print(fit)

# PD（Emax）阶段：把个体 PK 参数代入 Hill 模型，或改用 nlmixr2 的 PD compartment
# Ec50 / Emax 初值须来自体外实测；不要用 ADMET 预测值直接当 Ec50。
"""


def pk_initials(rows, dose_mg=None):
    """从 C(t) 推 1 房口服模型的初值 —— **不是估计结果**，只为让骨架能开跑。

    实测教训（v4.21）：骨架原本写死 CL=5 L/h、V=50 L，而本 skill 的 pbpk
    曲线量级是 V≈3000 L（100 mg 给药、Cmax 0.07–0.29 mg/L），差两个数量级，
    直接跑会卡在初值附近。初值应当由数据给出：

      V0   = AMT / Cmax            （mg / (mg/L) = L）
      ka0  = 1 / Tmax              （粗估，钳在 [0.05, 10] /h）
      CL0  = λz · V0               （λz 取末端两点对数斜率）
      addSd= 0.05 · median(C)      （观测噪声的地板）

    跨化合物取中位数。返回 {} 表示数据不足，调用方应回落到默认值。
    """
    import math

    by = {}
    for r in rows:
        if r["EVID"] != 0 or r["DV"] in ("", None):
            continue
        by.setdefault(r["ID"], []).append((float(r["TIME"]), float(r["DV"])))
    vs, kas, cls, sds, amts = [], [], [], [], []
    for _cid, pts in by.items():
        pts = [p for p in pts if p[1] > 0]
        if len(pts) < 3:
            continue
        cmax = max(c for _t, c in pts)
        tmax = min(t for t, c in pts if c == cmax)
        if cmax <= 0:
            continue
        amt = dose_mg
        if amt is None:
            amt = next(
                (
                    r["AMT"]
                    for r in rows
                    if r["ID"] == _cid and r["EVID"] == 1 and r["AMT"]
                ),
                None,
            )
        if not amt:
            continue
        v0 = amt / cmax
        ka0 = min(max(1.0 / tmax if tmax > 0 else 1.0, 0.05), 10.0)
        # 末端斜率只在"浓度仍 >1% Cmax"的点上取：本 skill 的曲线在 12–168 h
        # 已衰减到 0，直接取最后两点会得到 λz≈0（实测 CL 估成 0.001 L/h、假 t½=1e6 h）。
        pos = [(t, c) for t, c in pts if c >= 0.01 * cmax]
        (t1, c1), (t2, c2) = (pos[-2], pos[-1]) if len(pos) >= 2 else (pts[-2], pts[-1])
        lam = (math.log(c2) - math.log(c1)) / (t2 - t1) if t2 > t1 else 0.0
        cl0 = min(max(-lam, 1e-4), 10.0) * v0
        vs.append(v0)
        kas.append(ka0)
        cls.append(cl0)
        # 残差地板按 Cmax 给，不按全样本中位数：400 个时点里大半是衰减尾，
        # 中位数会给出 2e-06 这种"噪声为零"的假初值（实测）。
        sds.append(0.05 * cmax)
        amts.append(amt)
    if not vs:
        return {}
    med = lambda a: sorted(a)[len(a) // 2]
    return dict(
        v_init=round(med(vs), 1),
        ka_init=round(med(kas), 3),
        cl_init=round(med(cls), 3),
        add_sd=round(med(sds), 6),
        n_compounds=len(vs),
        dose_mg=med(amts),
    )


def nlmixr2_skeleton(
    data_path="nonmem_dataset.csv",
    cl_init=5.0,
    v_init=50.0,
    ka_init=0.6,
    f_init=1.0,
    add_sd=0.1,
    omega=0.2,
    init_note=None,
):
    """输出可直接改的 nlmixr2 R 脚本字符串。

    默认初值是通用量级（CL≈5 L/h、V≈50 L、ka≈0.6/h），**多数批次不适配**；
    调用方应先用 `pk_initials(rows)` 从数据推初值再传进来。
    这些**只是初值**，不是估计结果。
    """
    if not init_note:
        init_note = (
            "# 初值是通用量级（CL 5 L/h、V 50 L、ka 0.6/h），"
            "**未必适配本批数据**；\n"
            "# 建议改用 adt.interop.pk_initials(rows) 从 C(t) 推初值后再填。"
        )
    return _NLMIXR2.format(
        data_path=data_path,
        cl_init=cl_init,
        v_init=v_init,
        ka_init=ka_init,
        f_init=f_init,
        add_sd=add_sd,
        omega=omega,
        init_note=init_note,
    )


# ---------------------------------------------------------------------------
# OSP 快照（Version 80）：让 PK-Sim / MoBi 能**直接读进去**，而不是"照着 CSV 手填"
#
# 字段名与嵌套结构不是猜的：取自官方 Midazolam-Model v2.0 的 Compounds[0]
# （Name / IsSmallMolecule / PlasmaProteinBindingPartner / Lipophilicity /
#   FractionUnbound / Solubility / PkaTypes / Parameters），
# 并已用 PK-Sim 12.3.173 的 `PKSim.CLI snap -p` 实测转换成功（见 CHANGELOG v4.21）。
# ---------------------------------------------------------------------------
_SNAP_TOP_KEYS = [
    "Version",
    "ExpressionProfiles",
    "Individuals",
    "Compounds",
    "Formulations",
    "Protocols",
    "Events",
    "Simulations",
    "ParameterIdentifications",
    "ObservedData",
    "ObservedDataClassifications",
    "SimulationClassifications",
]

_SNAP_NOTE = (
    "由 admet-screening 生成；参数为预测值或类别级估计，**不是实测**，"
    "用于 PK-Sim 建模前必须在模型文件里保留 ValueOrigin 说明"
)


def _vo(desc):
    """PK-Sim 的 ValueOrigin：没有它就等于"来源不明"，有它才能被审计。"""
    return {"Source": "Unknown", "Description": desc}


def _pka_types(centres, ion_class, problems, cid):
    """把 adt/ionization 的基团列表转成 PK-Sim 的 PkaTypes。

    只认 dict（{kind, pka}）；只给数值时**按 ion_class 猜类型并记一笔**——
    猜的事必须留痕，不能静默。
    """
    out = []
    for c in centres or []:
        if isinstance(c, dict):
            kind = c.get("kind")
            val = c.get("pka")
            if val is None:
                continue
            out.append(
                {
                    "Type": "Base" if kind == "base" else "Acid",
                    "Pka": round(float(val), 2),
                }
            )
        else:
            inferred = "Base" if ion_class in ("base",) else "Acid"
            out.append({"Type": inferred, "Pka": round(float(c), 2)})
            problems.append(
                "%s: pKa=%s 只有数值没有酸碱类型，按 ion_class=%r 推成 %s"
                % (cid, c, ion_class, inferred)
            )
    # 同值同型去重（甘草查尔酮类常有多个等价酚羟基）
    seen, uniq = set(), []
    for t in out:
        k = (t["Type"], t["Pka"])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(t)
    return uniq


def pk_sim_snapshot(
    params_by_cid, pka_by_cid=None, ion_class_by_cid=None, note=_SNAP_NOTE
):
    """生成 PK-Sim/MoBi 可加载的 OSP 快照（Version 80，仅含 Compounds）。

    params_by_cid: {cid: {mw, clogp, fu_plasma, solubility_ph74, ...}}
    pka_by_cid:    {cid: [ {kind, pka} 或 float ]}
    返回 (snapshot_dict, meta)。meta 里必须有：
      · `omitted`：**能算但不该硬凑**的参数（如 Caco-2 → 肠道渗透性需要模型假设）
      · `problems`：猜过的、缺的、需要人工补的
    """
    pka_by_cid = pka_by_cid or {}
    ion_class_by_cid = ion_class_by_cid or {}
    compounds, problems, omitted = [], [], []

    for cid in sorted(params_by_cid):
        p = params_by_cid[cid]
        ion = ion_class_by_cid.get(cid, "")
        mw = _num(p.get("mw"))
        logp = _num(p.get("clogp"))
        fu = _num(p.get("fu_plasma"))
        sol = _num(p.get("solubility_ph74"))

        c = {
            "Name": str(cid),
            "IsSmallMolecule": True,
            "PlasmaProteinBindingPartner": "Albumin",
        }

        if logp == "":
            problems.append(
                "%s: 缺 logP（clogp）→ 不写 Lipophilicity，PK-Sim 会用默认值" % cid
            )
        else:
            c["Lipophilicity"] = [
                {
                    "Name": "Measurement",
                    "Parameters": [
                        {
                            "Name": "Lipophilicity",
                            "Value": round(float(logp), 3),
                            "Unit": "Log Units",
                            "ValueOrigin": _vo("RDKit Crippen logP；" + note),
                        }
                    ],
                }
            ]

        if fu == "":
            problems.append(
                "%s: 缺 fu(plasma) → PK-Sim 用 1.0 默认值，PPB 结论作废" % cid
            )
        else:
            c["FractionUnbound"] = [
                {
                    "Name": "Measurement",
                    "Species": "Human",
                    "Parameters": [
                        {
                            "Name": "Fraction unbound (plasma, reference value)",
                            "Value": float(fu),
                            "ValueOrigin": _vo("单源预测换算；" + note),
                        }
                    ],
                }
            ]

        if sol not in ("", None) and float(sol or 0) > 0:
            c["Solubility"] = [
                {
                    "Name": "Measurement",
                    "Parameters": [
                        {
                            "Name": "Solubility at reference pH",
                            "Value": round(float(sol), 6),
                            "Unit": "mg/l",
                            "ValueOrigin": _vo("预测溶解度；" + note),
                        },
                        {
                            "Name": "Reference pH",
                            "Value": 7.4,
                            "ValueOrigin": _vo("固定 pH 7.4 参考点"),
                        },
                    ],
                }
            ]
        else:
            problems.append("%s: 缺溶解度 → PK-Sim 走内置 pH-溶解度模型" % cid)

        types = _pka_types(pka_by_cid.get(cid), ion, problems, cid)
        if types:
            c["PkaTypes"] = types
        elif ion and ion != "neutral":
            problems.append("%s: ion_class=%r 但没有可写出的 pKa 中心" % (cid, ion))

        if mw != "":
            c["Parameters"] = [
                {
                    "Name": "Molecular weight",
                    "Value": round(float(mw), 2),
                    "Unit": "g/mol",
                    "ValueOrigin": _vo("RDKit 分子量"),
                }
            ]
        compounds.append(c)

    if any(_num(p.get("caco2_papp")) != "" for p in params_by_cid.values()):
        omitted.append(
            (
                "Specific intestinal permeability",
                "Caco-2 Papp(10^-6 cm/s) → 肠道通透性(cm/min) 需要 qgut/面积/"
                "孔隙假设，换算系数不是常数；宁可留空让人在 PK-Sim 里选方法",
            )
        )

    snap = {k: [] for k in _SNAP_TOP_KEYS}
    snap["Version"] = PK_SIM_SNAPSHOT_VERSION
    snap["Compounds"] = compounds
    meta = dict(
        n_compounds=len(compounds),
        problems=problems,
        omitted=omitted,
        snapshot_version=PK_SIM_SNAPSHOT_VERSION,
        validated_against_tool="pk_sim_cli_snap_passed",
        notice=INTEROP_NOTICE,
    )
    return snap, meta


def write_pk_sim_snapshot(path, snapshot):
    """写 OSP 快照 JSON（utf-8 无 BOM：.NET 的 Json.NET 对 BOM 容忍但没必要冒险）。"""
    import json

    with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(snapshot, fh, ensure_ascii=False, indent=2)
    return path
