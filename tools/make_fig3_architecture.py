# -*- coding: utf-8 -*-
"""Fig. 3 - framework architecture, four layers with one-directional dependencies.

Why this is generated rather than hand-drawn
--------------------------------------------
The caption in the manuscript makes three specific claims: there are four
layers, the dependencies are one-directional, and the admission decision sits
*before* aggregation rather than inside it. A figure that merely looks like an
architecture diagram would not support the third claim, which is the one the
paper's argument depends on. So the boxes are placed to make the ordering
explicit: inside the adjudication layer the admission box precedes the
aggregation box, and a bracket marks that boundary.

Output: figures/fig3_architecture.png at 600 dpi, matching fig1 and fig2.
"""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

plt.rcParams.update({"font.size": 9, "figure.dpi": 600})

INK = "#1a1a1a"
MUTED = "#6b6b6b"
FILL = "#f2f2f2"
FILL_ACC = "#dcdcdc"
EDGE = "#4a4a4a"
ACCENT = "#1a1a1a"


def box(ax, x, y, w, h, label, fill=FILL, bold=False, fs=8.5, sub=None):
    ax.add_patch(
        FancyBboxPatch(
            (x, y), w, h,
            boxstyle="round,pad=0.02,rounding_size=0.06",
            linewidth=0.9, edgecolor=EDGE, facecolor=fill, zorder=2,
        )
    )
    ty = y + h / 2 if sub is None else y + h / 2 + 0.16
    ax.text(x + w / 2, ty, label, ha="center", va="center",
            fontsize=fs, color=INK, fontweight="bold" if bold else "normal", zorder=3)
    if sub:
        ax.text(x + w / 2, y + h / 2 - 0.20, sub, ha="center", va="center",
                fontsize=fs - 1.6, color=MUTED, style="italic", zorder=3)


def arrow(ax, x1, y1, x2, y2, style="-|>", lw=1.0, color=EDGE, ls="-"):
    ax.add_patch(
        FancyArrowPatch((x1, y1), (x2, y2), arrowstyle=style, mutation_scale=10,
                        linewidth=lw, color=color, linestyle=ls, zorder=1,
                        shrinkA=1, shrinkB=1)
    )


def layer_label(ax, y, num, name, note=None):
    ax.text(0.12, y, num, ha="left", va="center", fontsize=10,
            color=ACCENT, fontweight="bold")
    ax.text(0.42, y, name, ha="left", va="center", fontsize=8.6, color=INK)
    if note:
        ax.text(0.42, y - 0.26, note, ha="left", va="center", fontsize=7.2,
                color=MUTED, style="italic")


fig, ax = plt.subplots(figsize=(7.4, 5.6))
ax.set_xlim(0, 10)
ax.set_ylim(0, 10)
ax.axis("off")

# ---- layer bands -------------------------------------------------------------
bands = [
    (7.55, "L1", "Structure and state"),
    (5.55, "L2", "Evidence acquisition"),
    (2.75, "L3", "Adjudication"),
    (0.55, "L4", "Delivery and governance"),
]
band_h = {"L1": 1.35, "L2": 1.35, "L3": 2.30, "L4": 1.45}

for y, num, name in bands:
    h = band_h[num]
    ax.add_patch(
        FancyBboxPatch((0.05, y), 9.9, h,
                       boxstyle="round,pad=0.02,rounding_size=0.08",
                       linewidth=0.6, edgecolor="#c8c8c8", facecolor="#fbfbfb", zorder=0)
    )
    layer_label(ax, y + h - 0.24, num, name)

# ---- L1: structure -----------------------------------------------------------
box(ax, 1.05, 7.78, 1.95, 0.72, "Normalisation", sub="desalt, neutralise, tautomer")
box(ax, 3.25, 7.78, 1.95, 0.72, "Structure key", sub="canonical InChIKey")
box(ax, 5.45, 7.78, 1.95, 0.72, "Authenticity", sub="glycoside, substitution")
box(ax, 7.65, 7.78, 1.95, 0.72, "State", sub="charge, stereochemistry")

# ---- L2: evidence ------------------------------------------------------------
box(ax, 1.05, 5.78, 2.55, 0.72, "Multi-source query", sub="predictors, databases, rules")
box(ax, 3.90, 5.78, 2.55, 0.72, "Availability check", sub="failed call != absence")
box(ax, 6.75, 5.78, 2.55, 0.72, "Evidence record", sub="value, provenance, quality")

# ---- L3: adjudication (the layer the paper is about) -------------------------
box(ax, 1.05, 3.95, 2.15, 0.80, "Source admission", sub="per source, per endpoint",
    fill=FILL_ACC, bold=True)
box(ax, 4.05, 3.95, 2.15, 0.80, "Aggregation", sub="admitted sources only")
box(ax, 7.05, 3.95, 2.15, 0.80, "Domain gate", sub="abstain outside domain")

arrow(ax, 3.22, 4.35, 4.02, 4.35)
arrow(ax, 6.22, 4.35, 7.02, 4.35)

# bracket: admission precedes aggregation
ax.annotate("", xy=(1.02, 3.82), xytext=(6.23, 3.82),
            arrowprops=dict(arrowstyle="-", linewidth=0.8, color=ACCENT))
ax.text(3.60, 3.60, "admission resolved before aggregation",
        ha="center", va="center", fontsize=7.6, color=ACCENT, fontweight="bold")

box(ax, 1.05, 2.95, 8.15, 0.58,
    "Abstention rule calibrated separately from admission",
    fill="#ffffff", fs=8.2)

# ---- L4: delivery ------------------------------------------------------------
box(ax, 1.05, 0.78, 2.35, 0.78, "Cost decision", sub="c* per endpoint", bold=True)
box(ax, 3.70, 0.78, 2.35, 0.78, "Release gates", sub="14 checks")
box(ax, 6.35, 0.78, 2.85, 0.78, "Audit ledger", sub="hash-chained record")

# ---- inter-layer arrows ------------------------------------------------------
arrow(ax, 5.00, 7.55, 5.00, 6.55)
arrow(ax, 5.00, 5.55, 5.00, 4.80)
arrow(ax, 5.00, 2.90, 5.00, 2.30)

# ---- side notes --------------------------------------------------------------
# Both annotations were colliding with boxes: the first with the Domain gate,
# the second with the Audit ledger. They now sit outside the bands.
ax.text(5.00, 0.26, "c* = \u0394u(0) / (cov$_{S1}$ \u2212 cov$_{S4}$)",
        ha="center", va="center", fontsize=8.6, color=ACCENT)

# ---- one-directional dependency marker --------------------------------------
ax.annotate("", xy=(0.30, 0.55), xytext=(0.30, 9.05),
            arrowprops=dict(arrowstyle="-|>", linewidth=0.7, color=MUTED,
                            linestyle=(0, (4, 2))))
ax.text(0.18, 4.8, "one-directional\ndependency", rotation=90, ha="center",
        va="center", fontsize=7.2, color=MUTED)

fig.tight_layout(pad=0.2)
out = "figures/fig3_architecture.png"
fig.savefig(out, dpi=600, bbox_inches="tight")
print("[fig3] ->", out)
