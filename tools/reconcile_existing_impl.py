# -*- coding: utf-8 -*-
"""P0 取证闭环（04 §4.1 / 外部评审 V1）：并排核对既有 n_eff 口径，禁止另起实现。

背景：03 号文件把 02 草稿里的 eigen 公式当成「本轮最重要的技术修正」加以撤回，
但 `adt/independence.py:363-391` 早已用更强的数学理由给出诊断并实现正确替代；
`n_eff_kish_eigen` 也早已自带「不是计票有效票数」的标注。本脚本不定义任何新公式，
只从 `adt.independence` 导入既有函数，把四种口径并排输出并断言它们各自对应什么。

口径对照（以相关矩阵 R 代入 Σ 仅作**演示**，不是估计量）：
  - n_eff_from_corr_matrix : k²/(1ᵀR1)          → 均值的有效样本量，唯一可用于计票权重
  - n_eff_equicorrelated   : k/(1+(k−1)ρ)       → 等相关标准形，生产路径 :300 用的就是它
  - n_eff_kish_eigen       : (Σλ)²/Σλ²          → effective rank / diversity，禁止计票
  - GLS 对照列              : σ̄²·(1ᵀΣ⁻¹1)       → 04 讨论的恒等式；属口径选择，需
                                                  aggregation_operator 显式化，不进生产
  - Var(μ̂)                 : 1/(1ᵀΣ⁻¹1)         → 携带绝对精度信息；plug-in 近似，
                                                  Σ̂ 与 y 相关时有有限样本偏倚

真实 Σ 必须由 B3 配对真值估计；本脚本不产出、也不冒充任何可入票的 Σ。

用法：
    python tools/reconcile_existing_impl.py
    python tools/reconcile_existing_impl.py --json-out review_baseline/reconcile.json
退出码：0=全部断言通过 / 1=断言失败 / 2=导入或读取失败
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    import numpy as np
    from adt.independence import (
        n_eff_from_corr_matrix,
        n_eff_equicorrelated,
        n_eff_kish_eigen,
    )
except Exception as exc:  # pragma: no cover
    print("[reconcile] 导入失败：%s" % exc, file=sys.stderr)
    sys.exit(2)


POLICY = {
    "voting_weight_source": "adt/independence.py::n_eff_from_corr_matrix",
    "forbidden_for_voting": "adt/independence.py::n_eff_kish_eigen",
    "production_equicorr_call": "adt/independence.py:300",
    "sigma_source": "BLOCKED_ON_B3 — 真实源误差协方差需配对真值，本脚本不产出",
    "gls_disclaimer": (
        "σ̄²(1ᵀΣ⁻¹1) 为数学恒等式但属口径选择；"
        "若采用须同时报 aggregation_operator 与两套 n_eff"
    ),
}


def equicorr(k, rho):
    R = np.full((k, k), float(rho))
    np.fill_diagonal(R, 1.0)
    return R


def gls_columns(sigma, eps=1e-9):
    """仅作口径对照：Var(μ̂) 与 σ̄²(1ᵀΣ⁻¹1)，带 ridge 敏感性。"""
    S = np.asarray(sigma, dtype=float)
    k = S.shape[0]
    one = np.ones(k)
    sbar2 = float(np.mean(np.diag(S)))
    reg = S + eps * np.eye(k)
    info = float(one @ np.linalg.solve(reg, one))
    var_muhat = 1.0 / info if info > 0 else float("nan")
    n_eff_gls = sbar2 * info
    cond = float(np.linalg.cond(S))
    # ridge 敏感性：ε 变化时 1ᵀ(Σ+εI)⁻¹1 的漂移（feasible-GLS 有限样本警示）
    ridge = {}
    for e in (1e-9, 1e-6, 1e-3):
        ridge["eps_%g" % e] = round(
            float(one @ np.linalg.solve(S + e * np.eye(k), one)), 6
        )
    return dict(
        sbar2=round(sbar2, 6),
        info=round(info, 6),
        var_muhat=round(var_muhat, 6),
        n_eff_gls=round(n_eff_gls, 6),
        cond=round(cond, 3),
        ridge_sensitivity=ridge,
    )


def build_cases():
    cases = []
    for k, rho in [
        (2, 0.0),
        (2, 0.3),
        (2, 0.5),
        (2, 0.8),
        (3, 0.3),
        (4, 0.3),
        (4, 0.8),
        (2, -0.5),
    ]:
        R = equicorr(k, rho) if rho >= 0 else np.array([[1.0, rho], [rho, 1.0]])
        kish = float(n_eff_from_corr_matrix(R))
        eigen = float(n_eff_kish_eigen(R))
        eq = float(n_eff_equicorrelated(k, rho))
        cases.append(
            dict(
                k=k,
                rho=rho,
                shape="equicorrelated" if rho >= 0 else "negative_pair",
                n_eff_kish=round(kish, 6),
                n_eff_equicorr=round(eq, 6),
                n_eff_eigen=round(eigen, 6),
                delta_kish_eigen=round(kish - eigen, 6),
                polarity_warning=(rho < 0 and kish > k),
                gls=gls_columns(R),
            )
        )
    return cases


def production_evidence():
    """静态取证：生产路径用的是哪个函数，eigen 是否只出现在定义/说明中。"""
    out = {}
    for rel, pat in [
        ("adt/independence.py", "n_eff_equicorrelated"),
        ("adt/independence.py", "n_eff_kish_eigen"),
        ("adt/cli.py", "n_eff_kish_eigen"),
    ]:
        p = ROOT / rel
        if not p.is_file():
            out["%s::%s" % (rel, pat)] = "FILE MISSING"
            continue
        lines = io.open(p, encoding="utf-8", errors="replace").read().splitlines()
        hits = [i + 1 for i, l in enumerate(lines) if pat in l]
        out["%s::%s" % (rel, pat)] = hits
    doc = io.open(ROOT / "adt" / "independence.py", encoding="utf-8").read()
    out["docstring_forbids_eigen_for_voting"] = "不得**用于计票权重" in doc
    return out


def run():
    cases = build_cases()
    ev = production_evidence()
    assertions = []

    def check(cid, ok, detail):
        assertions.append(dict(id=cid, passed=bool(ok), detail=detail))

    eq_ok = all(
        abs(c["n_eff_kish"] - c["n_eff_equicorr"]) < 1e-9
        for c in cases
        if c["shape"] == "equicorrelated"
    )
    check(
        "A1_kish_equals_equicorrelated",
        eq_ok,
        "等相关矩阵下 k²/(1ᵀR1) 必须恒等于 k/(1+(k−1)ρ)；"
        "这也证明生产路径 :300 的等相关口径与矩阵推广一致",
    )

    indep = [c for c in cases if c["rho"] == 0.0][0]
    check(
        "A2_identity_gives_k",
        abs(indep["n_eff_kish"] - indep["k"]) < 1e-9
        and abs(indep["n_eff_eigen"] - indep["k"]) < 1e-9
        and abs(indep["gls"]["n_eff_gls"] - indep["k"]) < 1e-9,
        "Σ=I 时三种口径都应为 k，独立源一票一源",
    )

    pos = [c for c in cases if c["rho"] > 0]
    check(
        "A3_eigen_is_not_voting_n_eff",
        all(abs(c["delta_kish_eigen"]) > 1e-6 for c in pos),
        "ρ>0 时 (Σλ)²/Σλ² 与均值有效样本量不同（effective rank，禁止计票）",
    )

    cli_hits = ev.get("adt/cli.py::n_eff_kish_eigen") or []
    check(
        "A4_eigen_not_used_in_production",
        cli_hits == [],
        "adt/cli.py 中不得出现 n_eff_kish_eigen 调用；实际命中 %s" % cli_hits,
    )
    check(
        "A5_policy_docstring_present",
        ev.get("docstring_forbids_eigen_for_voting") is True,
        "adt/independence.py 必须保留「不得用于计票权重」的口径声明",
    )

    neg = [c for c in cases if c["shape"] == "negative_pair"]
    check(
        "A6_negative_rho_needs_polarity_check",
        bool(neg)
        and all(
            c["polarity_warning"] and c["n_eff_kish"] > c["n_eff_equicorr"] for c in neg
        ),
        "负相关时矩阵口径给出 n_eff>k，而 n_eff_equicorrelated 内部 max(rho,0) "
        "把它截断为 k → 生产路径必须触发 SOURCE_POLARITY_CHECK，"
        "不得直接用等相关近似（外部评审 J1）",
    )

    observations = dict(
        gls_equals_kish_on_equicorrelated=all(
            abs(c["gls"]["n_eff_gls"] - c["n_eff_kish"]) < 1e-6
            for c in cases
            if c["shape"] == "equicorrelated"
        ),
        note=(
            "该数值一致性只在等相关矩阵下成立；一般 Σ 下两口径分叉，"
            "故若采用 GLS 必须显式声明 aggregation_operator 与 reference_variance_policy"
        ),
    )
    return dict(
        version=1,
        generated_by="tools/reconcile_existing_impl.py",
        source_of_truth="adt/independence.py",
        policy=POLICY,
        production_evidence=ev,
        cases=cases,
        observations=observations,
        assertions=assertions,
        passed=all(a["passed"] for a in assertions),
    )


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json-out", default=None)
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    res = run()

    if not a.quiet:
        print("=== n_eff 口径并排（既有实现，无新公式） ===")
        print(
            "%-4s %-6s %-12s %-12s %-12s %-12s"
            % ("k", "rho", "kish(计票)", "equicorr(:300)", "eigen(禁用)", "GLS对照")
        )
        for c in res["cases"]:
            print(
                "%-4d %-6.2f %-12.4f %-12.4f %-12.4f %-12.4f"
                % (
                    c["k"],
                    c["rho"],
                    c["n_eff_kish"],
                    c["n_eff_equicorr"],
                    c["n_eff_eigen"],
                    c["gls"]["n_eff_gls"],
                )
            )
        print("\n=== 断言 ===")
        for x in res["assertions"]:
            print(
                "  %s %-36s %s"
                % ("OK " if x["passed"] else "FAIL", x["id"], x["detail"])
            )
        print("\n=== 生产路径取证 ===")
        for k, v in res["production_evidence"].items():
            print("  %s = %s" % (k, v))
        print(
            "\n[reconcile] passed=%s  断言 %d/%d"
            % (
                res["passed"],
                sum(x["passed"] for x in res["assertions"]),
                len(res["assertions"]),
            )
        )

    if a.json_out:
        p = a.json_out if os.path.isabs(a.json_out) else str(ROOT / a.json_out)
        os.makedirs(os.path.dirname(os.path.abspath(p)), exist_ok=True)
        with io.open(p, "w", encoding="utf-8") as f:
            f.write(json.dumps(res, ensure_ascii=False, indent=2))
        if not a.quiet:
            print("[reconcile] JSON -> %s" % p)
    return 0 if res["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
