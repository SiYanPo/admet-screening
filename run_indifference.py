# -*- coding: utf-8 -*-
r"""A4 无差异曲线（indifference curve）—— **【2026-11-04 撤回 / C18 + 外审 A】**

本脚本的产物（c* / 无差异点 / 条件性优势区）已于 2026-11-04 全部撤回：
Δu(c)=a−q·c 是一阶线性会计恒等式，代价不进入 decided_mask；c* 是线性函数零点，
是代数必然而非可证伪估计量。保留本脚本仅供审计追溯，禁止推断性使用。
正确重构见 run_keystone.py 的 π(c) / S6 第二流水线与 references/ESTIMAND.yaml。

## 为什么这条是次轮处方里最便宜的高价值项
`out_keystone_v43/results.json` 的 `cost_sweep` 已经跑完 9 个代价点 × 3 端点 × 20 种子 ×
4 个对照，但一直被当成"稳健性附表"躺着。评审 §E4 指出：这 12 个数字直接就是
**无差异曲线**——它回答的是"准入层的价值在什么代价比下消失"，而不是"准入层平均有没有用"。

## 定义（写死在代码里，不许事后改）
对某个端点与某个对照 (A − B)，令 Δ(c) 为代价参数 c 下的效用中位数差：
- **无差异点 c\***：Δ(c\*) = 0 的那个 c。Δ>0 表示 A 更好。
- 只在 **CI 不含 0 且符号相反** 的相邻两代价点之间做**线性插值**求 c\*；
  若区间内 CI 跨 0，则 c\* 记为 `interval_contains_zero`（不给虚假精度）。
- 超出网格范围（全正或全负）→ 记 `<min` 或 `>max`，**不外推**。

两条代价轴（`costs` 里 hERG/DILI/BBB 各 3 个数，对应 误放/误弃/弃权 三类代价）：
- `abstain`：弃权代价（越高，弃权越贵）
- `false_pass`：误放代价（越高，漏放越贵）

## 输出
- `out_ext/keystone_indifference.json`
- `out_ext/keystone_indifference.md`（论文/材料可直接引的表）

## 用法
```bash
python run_indifference.py --in out_keystone_v43/results.json
```
"""
from __future__ import annotations

import argparse
import io
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))

AXES = {
    "abstain": ["abstain=0.05", "abstain=0.10", "abstain=0.20",
                "abstain=0.50", "abstain=1.00"],
    "false_pass": ["false_pass=2.0", "false_pass=5.0", "false_pass=10.0"],
}
AXIS_VALUE = {"abstain=0.05": 0.05, "abstain=0.10": 0.10, "abstain=0.20": 0.20,
              "abstain=0.50": 0.50, "abstain=1.00": 1.00,
              "false_pass=2.0": 2.0, "false_pass=5.0": 5.0, "false_pass=10.0": 10.0}


def _crossing(points):
    """points: [(cost, delta, ci_lo, ci_hi)] 按 cost 升序。返回 dict。"""
    pts = sorted(points)
    if not pts:
        return {"status": "no_data"}
    sig = [(c, d, lo, hi) for c, d, lo, hi in pts if (lo > 0 or hi < 0)]
    # 全部显著同号 → 网格内无交叉
    if len(sig) == len(pts):
        if all(d > 0 for _, d, _, _ in pts):
            return {"status": "always_better", "c_star": None,
                    "note": "网格全段显著为正：无差异点在网格下限之外（<%.3g）"
                            % pts[0][0]}
        if all(d < 0 for _, d, _, _ in pts):
            return {"status": "always_worse", "c_star": None,
                    "note": "网格全段显著为负：无差异点在网格上限之外（>%.3g）"
                            % pts[-1][0]}
    # 找符号翻转的相邻对（要求两端都显著，避免把噪声当交叉）
    for (c1, d1, lo1, hi1), (c2, d2, lo2, hi2) in zip(pts, pts[1:]):
        s1 = lo1 > 0 or hi1 < 0
        s2 = lo2 > 0 or hi2 < 0
        if s1 and s2 and d1 * d2 < 0:
            c_star = c1 + (0 - d1) * (c2 - c1) / (d2 - d1)
            return {"status": "identified",
                    "c_star": round(float(c_star), 4),
                    "bracket": [c1, c2],
                    "delta_at_bracket": [round(d1, 4), round(d2, 4)],
                    "note": "线性插值；两端均显著且符号相反"}
    # 有翻转但有一端不显著 → 只给区间，不给点
    for (c1, d1, lo1, hi1), (c2, d2, lo2, hi2) in zip(pts, pts[1:]):
        if d1 * d2 <= 0:
            return {"status": "interval_contains_zero",
                    "c_star": None, "bracket": [c1, c2],
                    "delta_at_bracket": [round(d1, 4), round(d2, 4)],
                    "note": "符号翻转但至少一端 CI 跨 0，不给点估计"}
    return {"status": "no_sign_change",
            "c_star": None,
            "note": "网格内无符号翻转且非同号全显著（多为不显著段）"}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp",
                    default=os.path.join(HERE, "out_keystone_v43/results.json"))
    ap.add_argument("--out-json", default=os.path.join(
        HERE, "out_ext/keystone_indifference.json"), dest="out_json")
    ap.add_argument("--out-md", default=os.path.join(
        HERE, "out_ext/keystone_indifference.md"), dest="out_md")
    a = ap.parse_args(argv)

    d = json.load(io.open(a.inp, encoding="utf-8"))
    sweep = d["cost_sweep"]
    endpoints = [e.strip() for e in str(d["endpoints"]).split(",")]
    compares = sorted({r["compare"] for rows in sweep.values() for r in rows})

    # 统计口径校正：先把真实规模写清（评审报告曾写"12 代价点"，实为 9）
    n_cost_points = len(sweep)
    n_rows = sum(len(v) for v in sweep.values())
    result = {
        "source": os.path.relpath(a.inp, HERE).replace("\\", "/"),
        "scale_correction": {
            "n_cost_points": n_cost_points,
            "n_comparisons": len(compares),
            "n_endpoints": len(endpoints),
            "n_seeds": d.get("seeds"),
            "n_rows_in_cost_sweep": n_rows,
            "note": ("评审报告写的『12 代价点』实为 12 行/端点（3 对照 × 4 方向口径），"
                     "真正的代价点是 %d 个（ref + 5 档 abstain + 3 档 false_pass）。"
                     "本文件一律以 %d 为准。" % (n_cost_points, n_cost_points)),
        },
        "definition": ("c* = Δ_utility 中位数 = 0 的代价参数；只在两端 CI 均不含 0 "
                       "且符号相反的相邻点间线性插值；不外推。"),
        "grid": {k: v for k, v in AXES.items()},
        "table": {},
    }

    for comp in compares:
        result["table"][comp] = {}
        for axis, keys in AXES.items():
            result["table"][comp][axis] = {}
            for ep in endpoints:
                pts = []
                for k in keys:
                    row = next((r for r in sweep[k]
                                if r["endpoint"] == ep and r["compare"] == comp), None)
                    if row is None:
                        continue
                    lo, hi = row["boot_ci95"]
                    pts.append((AXIS_VALUE[k], row["delta_median"], lo, hi))
                result["table"][comp][axis][ep] = _crossing(pts)

    # ---- 关键结论只从 S4−S1 与 S4−S5 两条对照抽（其余留作附表）--------------
    key = {}
    for comp in ("S4_full_admission - S1_naive_majority",
                 "S4_full_admission - S5_uncalibrated_conf"):
        if comp not in result["table"]:
            continue
        key[comp] = {}
        for axis in AXES:
            key[comp][axis] = {ep: result["table"][comp][axis][ep]["c_star"]
                               for ep in endpoints}
    result["key_crossings"] = key

    # ---- 一句话判定 -------------------------------------------------------
    ab = key.get("S4_full_admission - S1_naive_majority", {}).get("abstain", {})
    cs = [v for v in ab.values() if isinstance(v, (int, float))]
    # 【2026-11-04 / C18 + 外审 A】原 `conditional_advantage` verdict 已撤回。
    # 根因：cost_sweep 是「同一预测，只改代价，不重训」，Δu(c)=a−q·c 是一阶线性
    # 会计恒等式；c* 只是该函数零点，是代数必然而非可证伪命题。产物生成端不得
    # 继续输出「条件性优势区」作为结论，否则任何下游文档都会被 R18 判为违规来源。
    result["verdict"] = {
        "code": "retracted_accounting_identity",
        "statement": (
            "【2026-11-04 已撤回】原 verdict「准入层的优势是条件性的」建立在 "
            "Δu(c)=a−q·c 的一阶线性会计恒等式上：代价只进入事后重标价，不进入 "
            "decided_mask（外审 A 独立复算 R²=0.9999995、q=0.8189）。所谓无差异点 "
            "只是线性函数零点，属代数必然，不是可证伪命题。禁止对外引用本 verdict；"
            "待 π(c) 让代价真正进入决策、且 ESTIMAND.yaml 冻结后重新推导。"),
        "retracted_at": "2026-11-04",
        "admissible_for_external_use": False,
        "supersedes": "conditional_advantage (pre-2026-11-04)",
        "binding_items": ["C18", "B6", "§5.1 复审", "L+2", "外审 A"],
        "grid_c_star_values_retained_for_audit_only": ab,
    }
    if not cs:
        result["verdict"]["grid_note"] = (
            "abstain 轴上无可插值点，结论只能报网格内符号；同样禁止推断性使用。")

    # 2026-11-04 / C18 + §5.1 复审：c* 是 Δu(c)=a-q*c 的会计恒等式零点，
    # 给恒等式加误差棒属「华丽堆砌」。产物必须标禁用推断资格；
    # 与 B6 绑定执行，重构见 references/ESTIMAND.yaml / COST_ELICITATION.md。
    result["estimand_status"] = "accounting_identity_pending_retraction"
    result["inferential_use_forbidden"] = True
    result["c_star_ci95"] = None
    result["c_star_provenance"] = "point_estimate_pending_ci"
    result["ci_policy"] = ("外审 A 独立复算：Δu(c)=a-q*c（R^2=0.9999995, q=0.8189, "
                           "c*=0.2598）。在代价不进入决策掩码前，给 c* 加 bootstrap CI "
                           "只是给恒等式的误差棒做精致，不产生可证伪性，故不出 CI。")
    result["binding_item"] = "B6"
    os.makedirs(os.path.dirname(a.out_json), exist_ok=True)
    with io.open(a.out_json, "w", encoding="utf-8") as f:
        f.write(json.dumps(result, ensure_ascii=False, indent=2))

    # ---- Markdown ---------------------------------------------------------
    L = []
    L.append("# 无差异曲线（RETRACTED 2026-11-04 / C18）\n")
    L.append("> **撤回声明**：原副标题「准入层在什么代价比下才值得用」及其结论 "
             "`conditional_advantage` 已撤回。本表是 Δu(c)=a−q·c 一阶线性会计恒等式的"
             "数值展示：代价只进入事后重标价，不进入 `decided_mask`；表中「无差异点」"
             "是线性函数零点（代数必然），不是可证伪估计量。\n")
    L.append("> **禁止对外引用、禁止推断性使用**（`inferential_use_forbidden=true`）。"
             "保留本产物仅供审计追溯；正确处置见 `references/RETRACTION_NOTE.md` §五，"
             "代价进入决策的重构见 `run_keystone.py` 的 π(c) / S6 第二流水线。\n")
    L.append("> 数据源：`%s`；口径：%s\n" % (result["source"],
                                          result["scale_correction"]["note"]))
    L.append("**定义**：%s\n" % result["definition"])
    L.append("## 主表：S4 完整准入 vs S1 朴素多数投票\n")
    for axis, keys in AXES.items():
        L.append("### 代价轴 `%s`\n" % axis)
        L.append("| 端点 | " + " | ".join(keys) + " | c\\* | 状态 |")
        L.append("|---|" + "---|" * len(keys) + "---|---|")
        for ep in endpoints:
            cells = []
            for k in keys:
                row = next((r for r in sweep[k]
                            if r["endpoint"] == ep
                            and r["compare"] == "S4_full_admission - S1_naive_majority"),
                           None)
                cells.append("—" if row is None else "%+.4f" % row["delta_median"])
            cr = result["table"]["S4_full_admission - S1_naive_majority"][axis][ep]
            L.append("| %s | %s | %s | %s |"
                     % (ep, " | ".join(cells),
                        "—" if cr["c_star"] is None else "%.3g" % cr["c_star"],
                        cr["status"]))
        L.append("")
    L.append("## 判定\n")
    L.append("**%s** — %s\n" % (result["verdict"]["code"], result["verdict"]["statement"]))
    L.append("## 与 S5 未校准基线的对照（排除「基线过强」解释）\n")
    L.append("| 端点 | abstain 轴 c\\* | false_pass 轴 c\\* |")
    L.append("|---|---|---|")
    for ep in endpoints:
        t = result["table"].get("S4_full_admission - S5_uncalibrated_conf", {})
        if not t:
            continue
        ca = t.get("abstain", {}).get(ep, {})
        cf = t.get("false_pass", {}).get(ep, {})
        L.append("| %s | %s | %s |"
                 % (ep,
                    "—" if ca.get("c_star") is None else "%.3g" % ca["c_star"],
                    "—" if cf.get("c_star") is None else "%.3g" % cf["c_star"]))
    L.append("")
    L.append("> 复现：`python run_indifference.py`。所有小数来自 `cost_sweep` 的 "
             "20 种子配对 bootstrap CI，非点估计叙事。\n")
    with io.open(a.out_md, "w", encoding="utf-8") as f:
        f.write("\n".join(L))

    print(json.dumps(result["verdict"], ensure_ascii=False, indent=1))
    for comp, axes in result["key_crossings"].items():
        print("[indiff] %s" % comp)
        for axis, m in axes.items():
            print("   %-11s %s" % (axis, {k: v for k, v in m.items()}))
    print("[indiff] -> %s" % a.out_json)
    print("[indiff] -> %s" % a.out_md)
    return result


if __name__ == "__main__":
    main()
