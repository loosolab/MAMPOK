"""Figure 2 — Separation of Concerns: Reusability Model

Left panel: one Mamplate instantiated by N Mamplans
Right panel: responsibility table
"""

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch
import matplotlib.gridspec as gridspec

COLORS = {
    "mamplate_h":   "#6C3483",
    "mamplate_b":   "#E8DAEF",
    "mamplate_e":   "#8E44AD",
    "mamplan_h":    "#1B4F72",
    "mamplan_b":    "#D6EAF8",
    "mamplan_e":    "#2E86C1",
    "arrow":        "#626567",
    "text_dark":    "#1C2833",
    "text_light":   "#FFFFFF",
    "row_devops":   "#FDFEFE",
    "row_admin":    "#F4ECF7",
    "row_analyst":  "#EBF5FB",
    "header_bg":    "#2C3E50",
    "grid_line":    "#D5D8DC",
}


def fbox(ax, x, y, w, h, fc, ec, lw=1.5, radius=0.04, zorder=2):
    box = FancyBboxPatch(
        (x, y), w, h,
        boxstyle=f"round,pad=0,rounding_size={radius}",
        facecolor=fc, edgecolor=ec, linewidth=lw, zorder=zorder,
    )
    ax.add_patch(box)


fig = plt.figure(figsize=(13, 6))
gs = gridspec.GridSpec(1, 2, width_ratios=[1.1, 0.9], wspace=0.12)
ax_left = fig.add_subplot(gs[0])
ax_right = fig.add_subplot(gs[1])
fig.patch.set_facecolor("white")

for ax in [ax_left, ax_right]:
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

# ════════════════════════════════════════════════════════════════════
# LEFT PANEL — Mamplate → [Mamplan A, B, C]
# ════════════════════════════════════════════════════════════════════
ax_left.text(0.5, 0.97, "One template, many projects",
             ha="center", va="top", fontsize=11, fontweight="bold",
             color=COLORS["text_dark"])

# Mamplate box
mt_x, mt_y, mt_w, mt_h = 0.05, 0.70, 0.90, 0.20
fbox(ax_left, mt_x, mt_y, mt_w, mt_h, COLORS["mamplate_b"], COLORS["mamplate_e"], lw=2.5)
# header strip
fbox(ax_left, mt_x, mt_y + mt_h - 0.065, mt_w, 0.065,
     COLORS["mamplate_h"], COLORS["mamplate_h"], lw=0, radius=0.03, zorder=3)
ax_left.text(mt_x + mt_w / 2, mt_y + mt_h - 0.032,
             "cellxgene-mamplate.json",
             ha="center", va="center", fontsize=9.5, fontweight="bold",
             color=COLORS["text_light"], zorder=4)
lines = [
    "image:   ghcr.io/chanzuckerberg/cellxgene:1.2.0",
    "port:    5005                resources: 4 CPU / 16 GiB",
    'command: cellxgene launch __project.files__ --host 0.0.0.0',
]
for i, line in enumerate(lines):
    ax_left.text(mt_x + 0.05, mt_y + 0.125 - i * 0.038, line,
                 ha="left", va="center", fontsize=7.5,
                 color=COLORS["text_dark"], family="monospace", zorder=4)

# Three Mamplan boxes
mp_configs = [
    {"label": "scrna-alice-project-mamplan.json",
     "lines": ["files: rna_atlas.h5ad", "owner: alice", "datatype: scRNA-seq"],
     "x": 0.02},
    {"label": "atac-bob-project-mamplan.json",
     "lines": ["files: atac_peaks.h5ad", "owner: bob", "datatype: ATAC-seq"],
     "x": 0.355},
    {"label": "spatial-carol-mamplan.json",
     "lines": ["files: spatial.h5ad", "owner: carol", "datatype: Spatial"],
     "x": 0.685},
]
mp_w, mp_h = 0.285, 0.26
mp_y = 0.28

for cfg in mp_configs:
    mx, my = cfg["x"], mp_y
    fbox(ax_left, mx, my, mp_w, mp_h, COLORS["mamplan_b"], COLORS["mamplan_e"], lw=2)
    # header
    fbox(ax_left, mx, my + mp_h - 0.06, mp_w, 0.06,
         COLORS["mamplan_h"], COLORS["mamplan_h"], lw=0, radius=0.03, zorder=3)
    ax_left.text(mx + mp_w / 2, my + mp_h - 0.030,
                 cfg["label"], ha="center", va="center",
                 fontsize=6.5, fontweight="bold", color=COLORS["text_light"], zorder=4)
    for i, line in enumerate(cfg["lines"]):
        ax_left.text(mx + mp_w / 2, my + 0.155 - i * 0.048, line,
                     ha="center", va="center", fontsize=7.5,
                     color=COLORS["text_dark"], family="monospace", zorder=4)
    # Arrow from Mamplate bottom to Mamplan top
    ax_top = my + mp_h
    ax_bottom = mt_y
    ax_cx = mx + mp_w / 2
    ax_left.annotate("",
        xy=(ax_cx, ax_top + 0.002), xytext=(ax_cx, ax_bottom - 0.002),
        arrowprops=dict(arrowstyle="-|>", color=COLORS["mamplate_e"],
                        lw=1.8, mutation_scale=13),
        zorder=5,
    )

# "instantiates" labels on arrows
ax_left.text(0.5, 0.605, "instantiates", ha="center", va="center",
             fontsize=8, color=COLORS["mamplate_h"], fontstyle="italic")

# Generated URLs
url_y = 0.10
for i, cfg in enumerate(mp_configs):
    ax_cx = cfg["x"] + mp_w / 2
    ax_left.text(ax_cx, url_y,
                 f"→ https://cluster.org/cellxgene/\n   {cfg['label'].split('-mamplan')[0]}",
                 ha="center", va="center", fontsize=6.2, color="#148F77",
                 fontstyle="italic",
                 bbox=dict(boxstyle="round,pad=0.25", facecolor="#D1F2EB",
                           edgecolor="#148F77", lw=0.8))
    ax_left.annotate("",
        xy=(ax_cx, url_y + 0.045), xytext=(ax_cx, mp_y - 0.008),
        arrowprops=dict(arrowstyle="-|>", color="#148F77", lw=1.2, mutation_scale=10),
        zorder=5,
    )

# ════════════════════════════════════════════════════════════════════
# RIGHT PANEL — Responsibility Table
# ════════════════════════════════════════════════════════════════════
ax_right.text(0.5, 0.97, "Separation of Concerns",
              ha="center", va="top", fontsize=11, fontweight="bold",
              color=COLORS["text_dark"])

col_headers = ["Config file", "Written by", "Changes per…", "Contains"]
col_x = [0.02, 0.28, 0.52, 0.72]
col_w = [0.26, 0.24, 0.22, 0.265]

rows = [
    {
        "cells": ["config.json", "DevOps", "Never", "Cluster hosts\nS3 credentials\nAuth proxy"],
        "bg": COLORS["row_devops"],
        "icon": "🔧",
    },
    {
        "cells": ["mamplate.json", "Admin", "Per tool", "Docker image\nResources\nCommand template"],
        "bg": COLORS["row_admin"],
        "icon": "📋",
    },
    {
        "cells": ["mamplan.json", "Analyst", "Per project", "Data files\nOwner / lifetime\nMetadata"],
        "bg": COLORS["row_analyst"],
        "icon": "🧬",
    },
]

table_top = 0.85
row_h = 0.22
table_x, table_w = 0.02, 0.96

# Header row
fbox(ax_right, table_x, table_top, table_w, 0.09,
     COLORS["header_bg"], COLORS["header_bg"], lw=0, radius=0.02, zorder=2)
for j, (hdr, cx) in enumerate(zip(col_headers, col_x)):
    ax_right.text(cx + col_w[j] / 2, table_top + 0.045, hdr,
                  ha="center", va="center", fontsize=8.5, fontweight="bold",
                  color=COLORS["text_light"], zorder=3)

# Data rows
for i, row in enumerate(rows):
    ry = table_top - (i + 1) * row_h
    fbox(ax_right, table_x, ry, table_w, row_h - 0.01,
         row["bg"], COLORS["grid_line"], lw=1, radius=0.015, zorder=2)
    for j, (cell, cx) in enumerate(zip(row["cells"], col_x)):
        ax_right.text(cx + col_w[j] / 2, ry + row_h * 0.42, cell,
                      ha="center", va="center", fontsize=8,
                      color=COLORS["text_dark"], zorder=3,
                      family="monospace" if j == 0 else "sans-serif",
                      fontweight="bold" if j == 0 else "normal")

# Bracket annotation: "Defined once, reused indefinitely"
bx = 0.02
by_top = table_top - row_h + 0.07
by_bot = table_top - 2 * row_h + 0.07
ax_right.annotate("",
    xy=(bx - 0.01, by_bot), xytext=(bx - 0.01, by_top),
    arrowprops=dict(arrowstyle="-", color=COLORS["mamplate_h"], lw=2),
    zorder=5,
)
ax_right.text(bx - 0.04, (by_top + by_bot) / 2, "fixed\nonce",
              ha="center", va="center", fontsize=7,
              color=COLORS["mamplate_h"], fontweight="bold",
              rotation=90)

# Key insight box at bottom
insight = (
    "Each Mamplate can be instantiated by any number of Mamplans.\n"
    "Analysts write only a minimal project description;\n"
    "all infrastructure complexity is handled by Mampok."
)
ax_right.text(0.5, 0.07, insight,
              ha="center", va="center", fontsize=8, color=COLORS["text_dark"],
              style="italic", wrap=True,
              bbox=dict(boxstyle="round,pad=0.5", facecolor="#FDFEFE",
                        edgecolor=COLORS["grid_line"], lw=1.2))

plt.tight_layout(pad=0.5)
out = "figures/output/fig2_separation_of_concerns"
plt.savefig(out + ".pdf", bbox_inches="tight", dpi=300)
plt.savefig(out + ".png", bbox_inches="tight", dpi=300)
print(f"Saved {out}.pdf / .png")
plt.close()
