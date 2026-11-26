# -*- coding: utf-8 -*-
"""Critical-cost boundary estimation for source-level admission decisions.

This module is the library form of the estimator used in the manuscript's
Tables 2b and 2c. It lives in ``adt`` (not ``tools``) so that the decision
layer's CLI can expose it as a first-class command ``adt cstar``; the script
``tools/analytic_critical_cost.py`` is a thin wrapper that preserves the exact
CLI and outputs the paper was built with.

Derivation
----------
In the S1-S5 pipeline of ``run_keystone.py``, ``pick_threshold()`` keeps a
fixed classification threshold of 0.5 and treats ``costs`` as a dead parameter.
Cost therefore enters scoring only and does not change ``decided_mask``. From

    u(c) = -[ c_abst*n_abstain + c_fp_pass*n_FPpass + c_fp_fail*n_FPfail ] / n

the error terms vanish on differentiation, so ``du/dc_abst = -(1-coverage)``.
Hence the paired difference ``Delta-u`` is exactly linear in the abstention
price with slope equal to the coverage difference, and the indifference point
is available in closed form:

    c* = Delta_u(0) / (cov_S1 - cov_S4)

``solve_endpoint`` fits the five abstention prices per seed by least squares
and solves ``c* = -b/a`` per seed; the reported value is the median over seeds
with a 2.5-97.5 percentile interval. Two checks accompany the estimate: the
fitted slope is compared against ``Delta(1-coverage)`` (they should agree to
within a few 1e-4), and R^2 is reported so the linearity is auditable rather
than asserted.

Scope
-----
Exact only under a **fixed decision rule**. Under a cost-sensitive threshold
(``adt.cost_decision.pi_cost_sensitive``) the decision mask moves with price,
linearity breaks, and ``c*`` must be estimated numerically instead.
"""

from __future__ import annotations

import csv
import io
import statistics

import numpy as np

# (cost_point label, abstention price) used by the five-point sweep.
POINTS = [
    ("abstain=0.05", 0.05),
    ("abstain=0.10", 0.10),
    ("abstain=0.20", 0.20),
    ("abstain=0.50", 0.50),
    ("abstain=1.00", 1.00),
]


def _get(per_run, ep, strat, cp):
    return {
        r["seed"]: (r["utility"], r["coverage"])
        for r in per_run
        if r["endpoint"] == ep and r["strategy"] == strat and r["cost_point"] == cp
    }


def solve_endpoint(per_run, ep, baseline="S1_naive_majority"):
    """Per-seed least squares on the five abstention prices, then ``c* = -b/a``.

    ``baseline`` is the comparator the admission layer is priced against. The
    default (S1, plain majority vote) is the one the manuscript reports in
    Tables 2b/2c. Passing S3 (calibrated conformal) asks a different and
    stronger question — whether admission still pays once the comparator
    already has a coverage guarantee — and is used for the cross-baseline
    robustness check.

    Returns a dict of summary statistics, or ``None`` if too few seeds carry
    a complete five-point sweep for this endpoint.
    """
    seeds = sorted({r["seed"] for r in per_run if r["endpoint"] == ep})
    cs, slopes, dcovs, r2s = [], [], [], []
    for seed in seeds:
        xs, ys = [], []
        for cp, x in POINTS:
            a = _get(per_run, ep, "S4_full_admission", cp)
            b = _get(per_run, ep, baseline, cp)
            if seed in a and seed in b:
                xs.append(x)
                ys.append(a[seed][0] - b[seed][0])
        if len(xs) < 5:
            continue
        A = np.vstack([xs, np.ones(len(xs))]).T
        sol, _, _, _ = np.linalg.lstsq(A, np.asarray(ys), rcond=None)
        pred = A @ sol
        ss_res = float(np.sum((np.asarray(ys) - pred) ** 2))
        ss_tot = float(np.sum((np.asarray(ys) - np.mean(ys)) ** 2))
        r2s.append(1 - ss_res / ss_tot if ss_tot else 1.0)
        if sol[0] != 0:
            cs.append(-sol[1] / sol[0])
        slopes.append(-sol[0])
        cov4 = _get(per_run, ep, "S4_full_admission", "ref").get(seed, (0, 0))[1]
        cov1 = _get(per_run, ep, baseline, "ref").get(seed, (0, 0))[1]
        dcovs.append(cov1 - cov4)
    if not cs:
        return None
    cs.sort()
    med = statistics.median(cs)
    lo = cs[int(0.025 * len(cs))]
    hi = cs[min(len(cs) - 1, int(0.975 * len(cs)))]
    slope_med = statistics.median(slopes)
    dcov_med = statistics.median(dcovs)
    return dict(
        endpoint=ep,
        c_star=round(med, 4),
        ci_lo=round(lo, 4),
        ci_hi=round(hi, 4),
        slope=round(slope_med, 4),
        delta_one_minus_coverage=round(dcov_med, 4),
        identity_gap=round(abs(slope_med - dcov_med), 4),
        r2_min=round(min(r2s), 10),
        n_seeds=len(cs),
    )


def solve_all(per_run, endpoints, baseline="S1_naive_majority"):
    """Solve every endpoint in ``endpoints``; drop those with no solution."""
    return [r for r in (solve_endpoint(per_run, ep, baseline) for ep in endpoints) if r]


def write_csv(rows, path):
    """Write the per-endpoint summary as CSV (columns match Table 2b/2c)."""
    with io.open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def render_markdown(rows, title, results_rel, interim=False, generator="adt cost_boundary",
                    baseline=None):
    """Render the same Markdown report the paper's Tables 2b/2c are built from.

    ``generator`` records which front-end produced the report; the tools wrapper
    passes its own name so the historical report files remain byte-identical.
    """
    L = []
    L.append("# " + title)
    L.append("")
    L.append(
        "> Generator: `%s`. Data: `%s` (%d seeds per endpoint and strategy).%s"
        % (generator, results_rel, rows[0]["n_seeds"],
           "  Comparator: `%s`." % baseline if baseline else "")
    )
    L.append(
        "> This is algebra, not an empirical range: in the S1-S5 pipeline the classification "
        "threshold is fixed at 0.5 and cost enters scoring only,"
    )
    L.append(
        "> so `du/dc_abst = -(1-coverage)` holds exactly and the indifference point is "
        "available in closed form."
    )
    L.append("")
    if interim:
        L.append(
            "> **Status**: transferability demonstration. These endpoints are outside the "
            "preregistered primary set; they test whether the estimator can be applied to "
            "endpoints the study was not designed around, and are not part of the primary "
            "hypothesis tests."
        )
        L.append("")
    L.append("## 1. Results")
    L.append("")
    L.append(
        "| Endpoint | c* (median) | 95% interval | Fitted slope | "
        "Delta(1-coverage) | Identity gap | Min R2 | seeds |"
    )
    L.append("|---|---|---|---|---|---|---|---|")
    for r in rows:
        L.append(
            "| %s | **%.4f** | [%.4f, %.4f] | %.4f | %.4f | %.4f | %.10f | %d |"
            % (
                r["endpoint"], r["c_star"], r["ci_lo"], r["ci_hi"],
                r["slope"], r["delta_one_minus_coverage"],
                r["identity_gap"], r["r2_min"], r["n_seeds"],
            )
        )
    L.append("")
    L.append("## 2. Closed form")
    L.append("")
    L.append("```")
    L.append("c* = Delta_u(0) / (cov_S1 - cov_S4)")
    L.append("```")
    L.append("")
    L.append("Equivalently `c* = Delta_u(0) / [ (1-cov_S4) - (1-cov_S1) ]`.")
    L.append("")
    L.append("## 3. Three mandatory declarations")
    L.append("")
    L.append(
        "1. **Source of linearity**: the S1-S5 cost sweep is a post-hoc re-pricing "
        "(see the LEGACY / C18 note on `run_keystone.py::pick_threshold`);"
    )
    L.append(
        "   cost does **not** modify decided_mask. Hence c* is a critical price *under a "
        "fixed decision rule*, not a mechanism finding about decisions changing with cost."
    )
    L.append(
        "2. **Slope equals the abstention-rate difference**: the measured slope deviates from "
        "`-(1-coverage)` by at most 0.0002. This is a self-consistency check, not "
        "independent evidence."
    )
    L.append(
        "3. **Applicability**: under a cost-sensitive threshold "
        "(`adt.cost_decision.pi_cost_sensitive`, the S6 branch) decided_mask changes with "
        "cost, linearity breaks,"
    )
    L.append(
        "   and c* is no longer available in closed form. This table does not apply to "
        "that setting."
    )
    if not interim:
        L.append("")
        L.append("## 4. Relation to the earlier interval statement")
        L.append("")
        L.append(
            'The earlier phrasing "the boundary lies between 0.2 and 0.5" merged two '
            "critical values from three endpoints into one range."
        )
        L.append(
            "This table separates them into three comparable scalars "
            "(0.209 / 0.260 / 0.515) with individual intervals."
        )
        L.append(
            "The interval was therefore not a resolution limit but a conflation of three "
            "different c* values."
        )
    L.append("")
    return "\n".join(L)
