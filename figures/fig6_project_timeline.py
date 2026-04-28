"""Figure 6 — Multi-Project Timeline Dashboard (Gantt chart)

Simulated dataset of 9 projects across 6 months.
Shows active, stopped, redeployed, expiring, and expired states.
"""

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch
import matplotlib.dates as mdates
from datetime import datetime, timedelta
import numpy as np

COLORS = {
    "active":   "#148F77",
    "stopped":  "#BDC3C7",
    "expiring": "#E67E22",
    "expired":  "#C0392B",
    "redeploy": "#2E86C1",
    "today_ln": "#E74C3C",
    "bg":       "white",
    "grid":     "#EAECEE",
    "text":     "#1C2833",
    "text_dim": "#7F8C8D",
    "label_bg": "#F8F9FA",
}

# ── Simulated project data ─────────────────────────────────────────────
base = datetime(2026, 1, 1)
today = datetime(2026, 4, 24)

def d(days): return base + timedelta(days=days)

projects = [
    # project_id, tool, datatype, owner, segments, events, lifetime, final_status
    {
        "id": "scrna-atlas-alice",
        "tool": "CellXGene",
        "datatype": "scRNA-seq",
        "owner": "alice",
        "segments": [(d(0), d(55), "active"), (d(55), d(90), "stopped"),
                     (d(90), d(160), "active")],
        "events": [("redeploy", d(90))],
        "lifetime": d(175),
        "final": "expiring",
    },
    {
        "id": "atac-peaks-bob",
        "tool": "CellXGene",
        "datatype": "ATAC-seq",
        "owner": "bob",
        "segments": [(d(5), d(50), "active")],
        "events": [],
        "lifetime": d(48),
        "final": "expired",
    },
    {
        "id": "spatial-slide-carol",
        "tool": "Vitessce",
        "datatype": "Spatial",
        "owner": "carol",
        "segments": [(d(10), d(114), "active")],
        "events": [],
        "lifetime": d(200),
        "final": "active",
    },
    {
        "id": "scrna-timecourse-dan",
        "tool": "CellXGene",
        "datatype": "scRNA-seq",
        "owner": "dan",
        "segments": [(d(20), d(70), "active"), (d(70), d(100), "stopped"),
                     (d(100), d(114), "active")],
        "events": [("redeploy", d(100))],
        "lifetime": d(180),
        "final": "active",
    },
    {
        "id": "bulk-rna-eve",
        "tool": "custom",
        "datatype": "RNA-seq",
        "owner": "eve",
        "segments": [(d(0), d(114), "active")],
        "events": [],
        "lifetime": d(130),
        "final": "expiring",
    },
    {
        "id": "multiome-frank",
        "tool": "Vitessce",
        "datatype": "Multiome",
        "owner": "frank",
        "segments": [(d(30), d(80), "active"), (d(80), d(114), "stopped")],
        "events": [],
        "lifetime": d(200),
        "final": "stopped",
    },
    {
        "id": "cite-seq-grace",
        "tool": "CellXGene",
        "datatype": "CITE-seq",
        "owner": "grace",
        "segments": [(d(45), d(114), "active")],
        "events": [],
        "lifetime": d(185),
        "final": "active",
    },
    {
        "id": "proteomics-henry",
        "tool": "custom",
        "datatype": "Proteomics",
        "owner": "henry",
        "segments": [(d(15), d(55), "active")],
        "events": [],
        "lifetime": d(53),
        "final": "expired",
    },
    {
        "id": "chip-seq-iris",
        "tool": "CellXGene",
        "datatype": "ChIP-seq",
        "owner": "iris",
        "segments": [(d(60), d(114), "active")],
        "events": [],
        "lifetime": d(195),
        "final": "active",
    },
]

# ── Setup figure ───────────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(14, 6.5))
fig.patch.set_facecolor("white")

n = len(projects)
row_h = 0.75
y_positions = list(range(n - 1, -1, -1))  # top to bottom

# ── Draw bars ─────────────────────────────────────────────────────────
for i, (proj, y) in enumerate(zip(projects, y_positions)):
    for (t_start, t_end, state) in proj["segments"]:
        color = COLORS[state]
        width = (t_end - t_start).days
        x_start = (t_start - base).days
        ax.barh(y, width, left=x_start, height=row_h * 0.72,
                color=color, alpha=0.85, zorder=3, edgecolor="white", linewidth=0.3)

    # Redeploy markers (diamond)
    for (event_type, event_date) in proj["events"]:
        xd = (event_date - base).days
        ax.plot(xd, y, marker="D", color=COLORS["redeploy"],
                markersize=7, zorder=5, markeredgecolor="white", markeredgewidth=0.8)

    # Lifetime marker (triangle)
    if proj["final"] in ("active", "expiring", "stopped"):
        xl = (proj["lifetime"] - base).days
        if 0 <= xl <= 180:
            ax.plot(xl, y + row_h * 0.38, marker="v", color=COLORS["expiring"],
                    markersize=8, zorder=5, markeredgecolor="white", markeredgewidth=0.5)

    # Expired marker (X)
    if proj["final"] == "expired":
        last_seg = proj["segments"][-1]
        xe = (last_seg[1] - base).days
        ax.plot(xe, y, marker="X", color=COLORS["expired"],
                markersize=9, zorder=5, markeredgecolor="white", markeredgewidth=0.5)

# ── Y-axis labels ──────────────────────────────────────────────────────
ax.set_yticks(y_positions)
labels = [f"{p['id']}  ({p['tool'][:3].upper()}·{p['datatype'][:6]})" for p in projects]
ax.set_yticklabels(labels, fontsize=8.5, family="monospace")
ax.tick_params(left=False, labelsize=8.5)

# ── X-axis: months ────────────────────────────────────────────────────
month_starts = [0, 31, 59, 90, 120, 151]
month_labels = ["Jan 2026", "Feb", "Mar", "Apr", "May", "Jun"]
ax.set_xticks(month_starts)
ax.set_xticklabels(month_labels, fontsize=9.5)
ax.set_xlim(-2, 182)
ax.set_ylim(-0.8, n - 0.2)

# Grid lines
for ms in month_starts:
    ax.axvline(ms, color=COLORS["grid"], lw=0.8, zorder=1)
ax.set_axisbelow(True)

# ── TODAY line ────────────────────────────────────────────────────────
today_x = (today - base).days
ax.axvline(today_x, color=COLORS["today_ln"], lw=2, ls="--", zorder=4)
ax.text(today_x + 1, n - 0.4, "TODAY", fontsize=8.5, color=COLORS["today_ln"],
        fontweight="bold", ha="left", va="top")

# ── Spines ────────────────────────────────────────────────────────────
ax.spines[["top", "right"]].set_visible(False)
ax.spines["left"].set_visible(False)
ax.set_xlabel("Month (2026)", fontsize=10)
ax.set_title("Mampok — Multi-Project Lifecycle Dashboard (simulated data)",
             fontsize=11, fontweight="bold", color=COLORS["text"], pad=10)

# ── Legend ────────────────────────────────────────────────────────────
legend_items = [
    mpatches.Patch(facecolor=COLORS["active"],  label="Active"),
    mpatches.Patch(facecolor=COLORS["stopped"], label="Stopped (data in S3)"),
    mpatches.Patch(facecolor=COLORS["expired"], label="Expired (auto-stopped)"),
    plt.Line2D([0], [0], marker="D", color="w", markerfacecolor=COLORS["redeploy"],
               markersize=8, label="Redeploy event"),
    plt.Line2D([0], [0], marker="v", color="w", markerfacecolor=COLORS["expiring"],
               markersize=8, label="Lifetime (expiry date)"),
    plt.Line2D([0], [0], marker="X", color="w", markerfacecolor=COLORS["expired"],
               markersize=8, label="Auto-stopped (expired)"),
]
ax.legend(handles=legend_items, loc="lower right", fontsize=8.5,
          framealpha=0.95, edgecolor=COLORS["text_dim"],
          ncol=2, bbox_to_anchor=(0.99, 0.01))

plt.tight_layout(pad=0.5)
out = "figures/output/fig6_project_timeline"
plt.savefig(out + ".pdf", bbox_inches="tight", dpi=300)
plt.savefig(out + ".png", bbox_inches="tight", dpi=300)
print(f"Saved {out}.pdf / .png")
plt.close()
