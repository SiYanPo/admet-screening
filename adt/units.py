# -*- coding: utf-8 -*-
"""单位换算层（R22 / R2-4）：把"跳过"改成"能换算就换算，不能换算就给语义原因"。

评审 R2-4 原话："24 对单位异构直接跳过计票是信息浪费；log 单位换算表是有限可枚举的，
跳过只能是换算失败后的兜底。"

**实测修正**：本框架 run6 里那 24 对并不是 log/线性这类可换算差异，而是
`class`（0/1 类别）vs `probability`（概率）——即 C78 明令禁止混算的**语义类型**差异，
不是量纲差异。把类别硬映射成概率（0→0.05/1→0.95）会臆造精度，属编造。
故本模块的处置分三档：
  · `same`      ：同单位，直接配对
  · `converted` ：可换算（log↔线性、M/nM/uM、%↔fraction），**换算后配对**
  · `semantic`  ：语义类型差异（class vs probability），**拒绝换算**并写明原因
"""

LOG_KEYS = ("log", "log10", "plog", "log10(cm/s)")

import math

# 以"分子量无关"的浓度换算为骨架；系数是真实换算关系，非拟合
CONC_FACTOR = {  # → M
    "m": 1.0,
    "mm": 1e-3,
    "um": 1e-6,
    "µm": 1e-6,
    "nm": 1e-9,
    "pm": 1e-12,
}
FRACTION_UNITS = ("fraction", "ratio", "unitless")
PERCENT_UNITS = ("percent", "%", "pct")
CLASS_UNITS = ("class", "label", "binary", "bool")
PROB_UNITS = ("probability", "prob", "p")


# 只有这些"底数token"才代表摩尔浓度；用白名单而不是子串判断，
# 否则 "log10(cm/s)"（Papp，单位是速度不是浓度）会因含 "cm" 的 "m" 被误判成可换算。
_MOLAR_TOKENS = {
    "m",
    "molar",
    "mol/l",
    "mol/liter",
    "mol·l-1",
    "mol l-1",
    "moldm-3",
    "mol/dm3",
}


def _norm(u):
    return (u or "").strip().lower()


def _log_core(u):
    """取出 log 单位的"底数token"；不是 log 家族返回 None。"""
    u = _norm(u)
    for pre in ("plog", "log10", "log"):
        if u.startswith(pre):
            return u[len(pre) :]
    return None


def _is_molar_log(u):
    """is this unit a logarithm OF a molar concentration?"""
    core = _log_core(u)
    if core is None:
        return False
    core = core.strip().strip("()[]").replace(" ", "")
    return core in _MOLAR_TOKENS


def canonical(u):
    u = _norm(u)
    if u in CONC_FACTOR:
        return "M"
    if u in PERCENT_UNITS:
        return "fraction"
    if u in FRACTION_UNITS:
        return "fraction"
    if u in CLASS_UNITS:
        return "class"
    if u in PROB_UNITS:
        return "probability"
    if u.startswith("log"):
        return "log"
    return u


def is_semantic_mismatch(ua, ub):
    ca, cb = canonical(ua), canonical(ub)
    pair = {ca, cb}
    return pair == {"class", "probability"}


def convert(value, from_u, to_u):
    """在已知换算族内转换；不可换算返回 None（调用方必须据此降级，不得猜）。

    判定顺序是刻意的：先处理"同串恒等"和"百分比包裹"，再做浓度族线性换算，
    最后才处理 log↔线性。顺序错了就会出现"uM vs nM 被判成 same"或"45% → 45"这类静默错误。
    """
    ca, cb = canonical(from_u), canonical(to_u)
    ua, ub = _norm(from_u), _norm(to_u)

    # 0) 同一字符串：恒等（唯一不需要推理的情形）
    if ua == ub:
        return value

    # 1) 百分比包裹：% ↔ fraction/probability（45% → 0.45）
    if (ua in PERCENT_UNITS) != (ub in PERCENT_UNITS):
        other = cb if ua in PERCENT_UNITS else ca
        if other in ("fraction", "probability"):
            return value / 100.0 if ua in PERCENT_UNITS else value * 100.0

    # 2) 浓度族线性换算（uM 与 nM 的 canonical 同为 "M"，必须先于 ca==cb 分支）
    if ca == "M" and cb == "M":
        return value * CONC_FACTOR[ua] / CONC_FACTOR[ub]

    # 3) log ↔ 摩尔浓度。
    #    只有"摩尔浓度的 log"才能还原；log10(cm/s) 是 Papp（速度），不是浓度（不得乱换）。
    if ca == "log" and cb == "M":
        if not _is_molar_log(from_u):
            return None
        return 10.0 ** float(value)  # log10(M) = -6 → 1e-6
    if ca == "M" and cb == "log":
        if not _is_molar_log(to_u):
            return None
        return math.log10(float(value))  # 1e-6 → -6

    # 4) 同族内部
    if ca == cb:
        if ca == "log":
            # 两种不同写法的 log 单位（log10(m) vs log(m)）底数未必一致，不猜
            return None
        return value

    # 5) 概率 / 比例互认（数值同义，不涉及精度臆造）
    if {ca, cb} <= {"fraction", "probability"}:
        return value

    return None


def try_pair(va, ua, vb, ub):
    """返回 (va2, vb2, status, note)。status ∈ {same, converted, semantic, unconvertible}。"""
    ca, cb = canonical(ua), canonical(ub)
    if ca == cb:
        # 同一族但原始单位不同（uM vs nM）也要换算，不能当"same"
        if _norm(ua) == _norm(ub):
            return va, vb, "same", ""
        vb2 = convert(vb, ub, ua)
        if vb2 is not None:
            return va, vb2, "converted", "%s→%s" % (ub, ua)
        # 同族但换算不出来（例如两种 log 写法底数不明）：不能假装 same
        return None, None, "unconvertible", "同族但无可枚举换算（%s vs %s）" % (ua, ub)
    if is_semantic_mismatch(ua, ub):
        return (
            None,
            None,
            "semantic",
            (
                "class vs probability：语义类型差异，非量纲差异（C78 禁止混算）；"
                "如需合并须先有明确标定映射并在报告中声明"
            ),
        )
    # 优先把 b 转到 a 的单位
    vb2 = convert(vb, ub, ua)
    if vb2 is not None:
        return va, vb2, "converted", "%s→%s" % (ub, ua)
    va2 = convert(va, ua, ub)
    if va2 is not None:
        return va2, vb, "converted", "%s→%s" % (ua, ub)
    return None, None, "unconvertible", "无可枚举换算（%s vs %s）" % (ua, ub)
