# -*- coding: utf-8 -*-
"""Fig. 4 - the thirteen-endpoint price map as a forest plot.

Why a forest plot rather than a heat map
----------------------------------------
The claim this figure has to support is positional: at a fixed reference price,
nine endpoints fall on the paying side, three do not, and one is negative. A
forest plot makes that a matter of counting points left and right of a line. A
heat map of the same numbers would require the reader to scan a table.

Hollow markers flag the two endpoints run with three seeds instead of twenty, so
the wider intervals are explained in the figure rather than only in the caption.

Output: figures/fig4_forest.png at 600 dpi.
"""
from __future__ import annotations

import csv
import io
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "out_sensitivity", "critical_cost_all13.csv")

plt.rcParams.update({"font.size": 9, "figure.dpi": 600})

INK = "#1a1a1a"
MUTED = "#6b6b6b"
REF = 0.50


def main():
    rows = list(csv.DictReader(io.open(SRC, encoding="utf-8")))
    for r in rows:
        r["c"] = float(r["c_star"])
        r["lo"] = float(r["ci_lo"])
        r["hi"] = float(r["ci_hi"])
        r["n"] = int(r["n_seeds"])
    rows.sort(key=lambda r: r["c"])

    fig, ax = plt.subplots(figsize=(6.6, 4.9))
    ys = range(len(rows))

    for y, r in zip(ys, rows):
        full = r["n"] >= 20
        colour = INK if r["c"] >= REF else MUTED
        ax.plot([r["lo"], r["hi"]], [y, y], color=colour, lw=1.1,
                solid_capstyle="butt", zorder=2)
        ax.plot([r["c"]], [y], marker="o", ms=5.2, color=colour,
                mfc=colour if full else "white", mew=1.2, zorder=3)

    ax.axvline(REF, color=INK, lw=1.0, ls=(0, (3, 2)), zorder=1)
    ax.axvline(0.0, color="#b0b0b0", lw=0.7, zorder=0)

    ax.set_yticks(list(ys))
    ax.set_yticklabels([r["endpoint"].replace("_CarbonMangels", "") for r in rows],
                       fontsize=7.6)
    ax.set_xlabel("critical abstention cost  c*", fontsize=9)
    ax.set_xlim(-0.55, 1.55)
    ax.set_ylim(-0.8, len(rows) - 0.2)

    ax.annotate("reference price 0.50", xy=(REF, len(rows) - 0.55),
                xytext=(REF + 0.04, len(rows) - 0.55), fontsize=7.4, color=INK,
                va="center")
    ax.annotate("c* < 0:\nadmission harmful", xy=(-0.30, 0.55), fontsize=7.0,
                color=MUTED, ha="center", va="bottom")

    # count annotation: how many pay at the reference price
    n_pay = sum(1 for r in rows if r["c"] >= REF)
    n_neg = sum(1 for r in rows if r["c"] < 0)
    ax.text(0.98, 0.04,
            "%d of %d endpoints pay at 0.50;  %d negative" % (n_pay, len(rows), n_neg),
            transform=ax.transAxes, ha="right", va="bottom", fontsize=7.6, color=INK)

    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.tick_params(axis="x", labelsize=7.8)

    fig.tight_layout(pad=0.3)
    out = os.path.join(ROOT, "figures", "fig4_forest.png")
    fig.savefig(out, dpi=600, bbox_inches="tight")
    print("[fig4] ->", out, "| pay=%d/%d neg=%d" % (n_pay, len(rows), n_neg))


if __name__ == "__main__":
    main()
