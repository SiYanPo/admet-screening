# -*- coding: utf-8 -*-
"""稳健 Z 背景归一化（移植自 reverse-molecular-docking E6a）。

为什么需要它（本项目缺口）
--------------------------
reliab 只回答两件事："跨源是否一致" 与 "相对绝对阈值 PASS/FAIL/UNDETERMINED"。
它回答不了第三个问题：**这个分子的这个值，相对于"同化学型背景"，是不是真的异常？**

  - logS = -3.0 看着不错，但若同类糖苷背景中位就是 -2.8，它并不突出；
  - Caco-2 = -6.2 看着都差，但若同类背景是 -6.6，它反而是"相对好"的。

原始值跨分子/跨源不可直接比；归一化后才有意义——而**归一化的有效性完全取决于
背景化学型是否匹配**（拿随机小分子做背景会"虚构差异"，这是反向 skill C 组实测过的坑）。

方法（稳健、抗单点）
--------------------
  center = median(bg)
  scale  = max(1.4826 * MAD(bg), floor)      # floor 默认 0.30，≈重复性量级
  z      = (S - center) / scale
  z_sd   = (S - center) / sd(bg)             # 旧口径，仅用于尺度冲突检测
  |z - z_sd| > 1.5  → SCALE_CONFLICT（不得静默取一个值，须补背景或人工复核）

为什么用 MAD 不用 SD：SD 不稳健。一个极端值（如 26 可旋转键的糖苷混进小分子背景）
就能把 SD 抬高、把 |z| 压小。稳健中心配稳健尺度。

定向（按 rules 的 shape）
-------------------------
  up（越大越好，如溶解度/Caco-2 logPapp）  → z_favorable = +z
  down（越小越好，如 PPB/CLint）           → z_favorable = -z
  window / step / 无规则                   → z_favorable = None（只报 |z| 异常度，不给方向）

背景两种模式
------------
  bg_rows 给定       跨化学型背景（推荐：同骨架/同分子量量级的类似物）
  within_set=True    以本批分子自身为背景（留一法，回答"本批内谁离群"）

两种模式都遵守同一条缺失语义：**技术失败/域外不是阴性**——missing 行不赋 Z、不排名。
"""

import csv
import io
import os

PRED_FLAGS = {"predicted", "measured", "saturated", "manual"}
DEFAULT_FLOOR = 0.30  # ≈ Vina/预测重复性量级；项目校准值，不是普适常数
DEFAULT_MIN_BG = 5  # n<5 不报 Z；n<50 标 SMALL_N
STABLE_BG = 50
SCALE_CONFLICT_DIFF = 1.5
OUTLIER_Z = 2.0


def _f(v):
    try:
        x = float(v)
        return x if x == x and x not in (float("inf"), float("-inf")) else None
    except (TypeError, ValueError):
        return None


def _median(vals):
    s = sorted(vals)
    n = len(s)
    if n == 0:
        return None
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def robust_scale(values, method="mad", floor=DEFAULT_FLOOR):
    """返回 (center, scale, method_used, degenerate)。scale 不低于 floor。"""
    vals = [v for v in (_f(x) for x in values) if v is not None]
    if not vals:
        return None, None, method, True
    center = _median(vals)
    degenerate = False
    if method == "sd":
        scale = _sd(vals)
        used = "sd"
    else:
        mad = _median([abs(v - center) for v in vals])
        scale = 1.4826 * mad
        used = "mad"
    if scale is None or scale <= 0 or scale < floor:
        scale = floor
        used += "+floor"
        degenerate = True
    return center, scale, used, degenerate


def _sd(vals):
    n = len(vals)
    if n < 2:
        return 0.0
    m = sum(vals) / n
    return (sum((v - m) ** 2 for v in vals) / (n - 1)) ** 0.5


def _shape_of(rule):
    return (rule or {}).get("shape", "down")


def build(
    target_rows,
    bg_rows=None,
    rules=None,
    floor=DEFAULT_FLOOR,
    min_bg=DEFAULT_MIN_BG,
    within_set=False,
):
    """计算每个 (compound, endpoint) 相对背景的稳健 Z。

    target_rows / bg_rows: 长表 dict 列表（schema.measurements 同款字段）。
    返回 list[dict]（可直接 write 成 CSV）。
    """
    rules = rules or {}
    use_self = within_set or bg_rows is None
    bg_pool = target_rows if use_self else bg_rows

    # 背景：按 (端点, 单位) 收集所有可用的数值（留一法在循环内剔除同 compound）
    # C78 同源守卫：概率与类别 0/1 不可混算——背景必须按 unit 分组，否则
    # "类别 0" 会被当成 "概率 0" 抬高方差、把 z 压小。
    bg_by_ep = {}
    for r in bg_pool:
        if r.get("domain_flag") not in PRED_FLAGS:
            continue
        v = _f(r.get("value"))
        if v is None:
            continue
        key = (r.get("endpoint", ""), str(r.get("unit", "")).strip().lower())
        bg_by_ep.setdefault(key, []).append((r.get("compound_id", ""), v))

    out = []
    for r in target_rows:
        ep = r.get("endpoint", "")
        cid = r.get("compound_id", "")
        val = _f(r.get("value"))
        rule = rules.get(ep)
        rec = dict(
            compound_id=cid,
            endpoint=ep,
            value="" if val is None else round(val, 4),
            unit=r.get("unit", ""),
            n_bg=0,
            center="",
            scale="",
            scale_method="",
            z="",
            z_sd="",
            z_favorable="",
            flag="",
            qc_flag="",
            note="",
        )

        if r.get("domain_flag") not in PRED_FLAGS or val is None:
            rec["flag"] = "missing"
            rec["note"] = "域外/失败/空值：缺失不得赋分（flag=%s）" % r.get(
                "domain_flag"
            )
            out.append(rec)
            continue

        pool = [
            (c, v)
            for (c, v) in bg_by_ep.get((ep, str(r.get("unit", "")).strip().lower()), [])
            if not (use_self and c == cid)
        ]
        vals = [v for _, v in pool]
        n = len(vals)
        rec["n_bg"] = n
        if n < min_bg:
            rec["flag"] = "BG_TOO_FEW"
            rec["note"] = (
                "背景 n=%d < %d（单位=%r）：不计算 Z"
                "（补背景配体/同单位源，或改 within-set）"
                % (n, min_bg, r.get("unit", ""))
            )
            out.append(rec)
            continue

        center, scale, used, degenerate = robust_scale(vals, "mad", floor)
        sd = _sd(vals)
        z = (val - center) / scale if scale else None
        z_sd = (val - center) / sd if sd and sd > 0 else None
        rec.update(
            center=round(center, 4),
            scale=round(scale, 4),
            scale_method=used,
            z=round(z, 4) if z is not None else "",
            z_sd=round(z_sd, 4) if z_sd is not None else "",
        )

        shape = _shape_of(rule)
        if shape == "up":
            fav = z
        elif shape == "down":
            fav = -z
        else:
            fav = None
        rec["z_favorable"] = round(fav, 4) if fav is not None else ""

        qc = []
        if n < STABLE_BG:
            qc.append("SMALL_N")
        if z is not None and z_sd is not None and abs(z - z_sd) > SCALE_CONFLICT_DIFF:
            qc.append("SCALE_CONFLICT")
        if degenerate:
            qc.append("DEGENERATE")
        if shape not in ("up", "down"):
            qc.append("NO_DIRECTION")
        rec["qc_flag"] = ";".join(qc)

        if z is None:
            rec["flag"] = "BG_TOO_FEW"
        elif abs(z) >= OUTLIER_Z:
            rec["flag"] = "OUTLIER"
        else:
            rec["flag"] = "ok"

        bits = []
        if rec["flag"] == "OUTLIER":
            if fav is not None:
                bits.append("相对背景%s" % ("更优" if fav > 0 else "更差"))
            bits.append("z=%+.2f（|z|≥%.1f）" % (z, OUTLIER_Z))
        if "SCALE_CONFLICT" in rec["qc_flag"]:
            bits.append(
                "尺度冲突(z_mad=%+.2f vs z_sd=%+.2f)：须补背景/人工复核" % (z, z_sd)
            )
        if n < STABLE_BG:
            bits.append("n=%d<50，Z 稳定性有限" % n)
        rec["note"] = "；".join(bits)
        out.append(rec)
    return out


def summarize(rows):
    """按 flag 计数，便于报告一句话引用。"""
    c = {}
    for r in rows:
        c[r["flag"]] = c.get(r["flag"], 0) + 1
    return c


def write(path, rows):
    cols = [
        "compound_id",
        "endpoint",
        "value",
        "unit",
        "n_bg",
        "center",
        "scale",
        "scale_method",
        "z",
        "z_sd",
        "z_favorable",
        "flag",
        "qc_flag",
        "note",
    ]
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with io.open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return len(rows)
