"""Figure 3 — Data Persistence Lifecycle

Horizontal swimlane diagram: User actions / Mampok operations / Storage state
across four phases: Deploy, Run, Stop, Redeploy
"""

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
import matplotlib.patheffects as pe

COLORS = {
    "phase_deploy":   "#D6EAF8",
    "phase_run":      "#D5F5E3",
    "phase_stop":     "#FDEBD0",
    "phase_redeploy": "#E8DAEF",
    "phase_border":   "#BFC9CA",
    "lane_user":      "#F8F9FA",
    "lane_mampok":    "#EBF5FB",
    "lane_storage":   "#FEF9E7",
    "lane_label_bg":  "#2C3E50",
    "text_dark":      "#1C2833",
    "text_light":     "#FFFFFF",
    "local":          "#5D6D7E",
    "s3":             "#D35400",
    "k8s":            "#2E86C1",
    "arrow_dn":       "#148F77",
    "arrow_up":       "#8E44AD",
    "sync":           "#F39C12",
    "phase_label":    "#2C3E50",
}


def fbox(ax, x, y, w, h, fc, ec, lw=1.2, radius=0.01, zorder=2, alpha=1.0):
    box = FancyBboxPatch(
        (x, y), w, h,
        boxstyle=f"round,pad=0,rounding_size={radius}",
        facecolor=fc, edgecolor=ec, linewidth=lw, zorder=zorder, alpha=alpha,
    )
    ax.add_patch(box)


fig, ax = plt.subplots(figsize=(14, 6.5))
ax.set_xlim(0, 1)
ax.set_ylim(0, 1)
ax.axis("off")
fig.patch.set_facecolor("white")

# ── Layout constants ─────────────────────────────────────────────────
lane_label_w = 0.11
lane_h = 0.22
lane_y = [0.72, 0.48, 0.24]
lane_labels = ["User\nActions", "Mampok\nOperations", "Storage\nState"]
lane_colors = [COLORS["lane_user"], COLORS["lane_mampok"], COLORS["lane_storage"]]

# Phase x positions (after label column)
phase_starts = [0.115, 0.33, 0.565, 0.775]
phase_ends   = [0.325, 0.56, 0.770, 0.985]
phase_labels = ["① Deploy", "② Run", "③ Stop", "④ Redeploy"]
phase_colors = [COLORS["phase_deploy"], COLORS["phase_run"],
                COLORS["phase_stop"], COLORS["phase_redeploy"]]

total_h = lane_h * 3 + 0.06  # three lanes + gaps
total_y = lane_y[2] - 0.02

# ── Background phase strips ───────────────────────────────────────────
for i, (ps, pe_x, pc) in enumerate(zip(phase_starts, phase_ends, phase_colors)):
    fbox(ax, ps, total_y, pe_x - ps - 0.005, total_h + 0.02, pc, COLORS["phase_border"],
         lw=1, radius=0.008, zorder=1, alpha=0.5)
    ax.text((ps + pe_x) / 2, total_y + total_h + 0.035, phase_labels[i],
            ha="center", va="center", fontsize=10, fontweight="bold",
            color=COLORS["phase_label"])

# ── Lane background + labels ──────────────────────────────────────────
for j, (ly, ll, lc) in enumerate(zip(lane_y, lane_labels, lane_colors)):
    # Lane background (full width minus label)
    fbox(ax, lane_label_w, ly, 1.0 - lane_label_w - 0.005, lane_h - 0.02,
         lc, COLORS["phase_border"], lw=0.8, radius=0.006, zorder=1, alpha=0.6)
    # Lane label box
    fbox(ax, 0.005, ly, lane_label_w - 0.01, lane_h - 0.02,
         COLORS["lane_label_bg"], COLORS["lane_label_bg"], lw=0, radius=0.01, zorder=3)
    ax.text(0.005 + (lane_label_w - 0.01) / 2, ly + (lane_h - 0.02) / 2,
            ll, ha="center", va="center", fontsize=9, fontweight="bold",
            color=COLORS["text_light"], zorder=4, linespacing=1.5)

# ── Horizontal timeline arrow ─────────────────────────────────────────
tl_y = total_y + total_h + 0.065
ax.annotate("", xy=(0.99, tl_y), xytext=(0.11, tl_y),
            arrowprops=dict(arrowstyle="-|>", color="#7F8C8D", lw=1.8, mutation_scale=14))
ax.text(0.995, tl_y, "time", ha="left", va="center", fontsize=9, color="#7F8C8D")


# ════════════════════════════════════════════════════════════════════
# CONTENT: phase by phase
# ════════════════════════════════════════════════════════════════════

def node(ax, cx, cy, text, fc, ec, w=0.10, h=0.075, fs=7.5, zorder=4, fw="normal"):
    fbox(ax, cx - w/2, cy - h/2, w, h, fc, ec, lw=1.5, radius=0.012, zorder=zorder)
    ax.text(cx, cy, text, ha="center", va="center", fontsize=fs,
            color=COLORS["text_dark"], zorder=zorder+1, fontweight=fw,
            family="monospace", linespacing=1.4)

def vert_arrow(ax, x, y_top, y_bot, color, label="", label_side="right"):
    ax.annotate("", xy=(x, y_bot), xytext=(x, y_top),
                arrowprops=dict(arrowstyle="-|>", color=color, lw=1.6, mutation_scale=11),
                zorder=6)
    if label:
        lx = x + 0.008 if label_side == "right" else x - 0.008
        ha = "left" if label_side == "right" else "right"
        ax.text(lx, (y_top + y_bot) / 2, label,
                ha=ha, va="center", fontsize=6.8, color=color, fontstyle="italic")

# ── Phase 1: Deploy ──────────────────────────────────────────────────
cx1 = (phase_starts[0] + phase_ends[0]) / 2

# User: write mamplan + run deploy
node(ax, cx1, lane_y[0] + 0.12, "mampok deploy\nmy-project/", "#D6EAF8", COLORS["k8s"],
     w=0.17, h=0.075, fw="bold")

# Mampok: upload to S3
node(ax, cx1, lane_y[1] + 0.10, "upload files\nto S3 analysis_data/",
     "#EBF5FB", COLORS["s3"], w=0.17, h=0.075)

# Storage: local → S3
node(ax, cx1 - 0.04, lane_y[2] + 0.09, "local .h5ad",
     "#F8F9FA", COLORS["local"], w=0.12, h=0.065)
ax.annotate("", xy=(cx1 + 0.055, lane_y[2] + 0.09),
            xytext=(cx1 + 0.01, lane_y[2] + 0.09),
            arrowprops=dict(arrowstyle="-|>", color=COLORS["s3"], lw=1.5, mutation_scale=10))
node(ax, cx1 + 0.09, lane_y[2] + 0.09, "S3:\nanalysis_data/",
     "#FDEBD0", COLORS["s3"], w=0.12, h=0.065)

vert_arrow(ax, cx1, lane_y[0] + 0.082, lane_y[1] + 0.145, COLORS["arrow_dn"])
vert_arrow(ax, cx1, lane_y[1] + 0.065, lane_y[2] + 0.14, COLORS["s3"])

# ── Phase 2: Run ─────────────────────────────────────────────────────
cx2 = (phase_starts[1] + phase_ends[1]) / 2

# User: access tool via URL
node(ax, cx2, lane_y[0] + 0.12, "access tool\nhttps://…/project",
     "#D5F5E3", "#27AE60", w=0.17, h=0.075)

# Mampok: init container + rclone sidecar
node(ax, cx2, lane_y[1] + 0.145, "init: download\nfrom S3 → /data/",
     "#EBF5FB", COLORS["k8s"], w=0.17, h=0.065)
node(ax, cx2, lane_y[1] + 0.058, "rclone sidecar:\nsync every 60 s",
     "#EBF5FB", COLORS["sync"], w=0.17, h=0.065)

# Storage: S3 → container, annotations back
node(ax, cx2 - 0.055, lane_y[2] + 0.09, "S3:\nanalysis_data/",
     "#FDEBD0", COLORS["s3"], w=0.11, h=0.065)
node(ax, cx2 + 0.01, lane_y[2] + 0.09, "Container\n/data/*.h5ad",
     "#D4E6F1", COLORS["k8s"], w=0.12, h=0.065)
node(ax, cx2 + 0.11, lane_y[2] + 0.09, "S3:\ncontainer_data/",
     "#FDEBD0", COLORS["s3"], w=0.12, h=0.065)

# Arrows: S3 → container
ax.annotate("", xy=(cx2 - 0.005, lane_y[2] + 0.09),
            xytext=(cx2 - 0.005 - 0.049, lane_y[2] + 0.09),
            arrowprops=dict(arrowstyle="-|>", color=COLORS["k8s"], lw=1.4, mutation_scale=9))
# container → S3 container_data
ax.annotate("", xy=(cx2 + 0.055, lane_y[2] + 0.09),
            xytext=(cx2 + 0.055 + 0.002, lane_y[2] + 0.09),
            arrowprops=dict(arrowstyle="-|>", color=COLORS["sync"], lw=1.4, mutation_scale=9))

vert_arrow(ax, cx2 - 0.01, lane_y[1] + 0.11, lane_y[2] + 0.14,
           COLORS["k8s"], "init download", "left")
vert_arrow(ax, cx2 + 0.07, lane_y[2] + 0.135, lane_y[1] + 0.09,
           COLORS["sync"], "periodic sync", "right")

# ── Phase 3: Stop ────────────────────────────────────────────────────
cx3 = (phase_starts[2] + phase_ends[2]) / 2

node(ax, cx3, lane_y[0] + 0.12, "mampok stop\nmy-project/",
     "#FDEBD0", COLORS["s3"], w=0.17, h=0.075, fw="bold")

node(ax, cx3, lane_y[1] + 0.10, "delete K8s resources\nfinal S3 sync",
     "#EBF5FB", COLORS["s3"], w=0.17, h=0.075)

node(ax, cx3 - 0.04, lane_y[2] + 0.09, "Container\ndeleted",
     "#FDEBD0", "#C0392B", w=0.11, h=0.065)
node(ax, cx3 + 0.07, lane_y[2] + 0.09, "S3: data\npreserved ✓",
     "#D5F5E3", "#27AE60", w=0.12, h=0.065, fw="bold")

vert_arrow(ax, cx3, lane_y[0] + 0.082, lane_y[1] + 0.145, COLORS["arrow_dn"])
vert_arrow(ax, cx3, lane_y[1] + 0.065, lane_y[2] + 0.14, COLORS["s3"])

# ── Phase 4: Redeploy ────────────────────────────────────────────────
cx4 = (phase_starts[3] + phase_ends[3]) / 2

node(ax, cx4, lane_y[0] + 0.12, "mampok redeploy\nmy-project/",
     "#E8DAEF", "#8E44AD", w=0.17, h=0.075, fw="bold")

node(ax, cx4, lane_y[1] + 0.10, "restore all data\nfrom S3 → container",
     "#EBF5FB", COLORS["k8s"], w=0.17, h=0.075)

node(ax, cx4 - 0.045, lane_y[2] + 0.09, "S3:\nall data",
     "#FDEBD0", COLORS["s3"], w=0.10, h=0.065)
node(ax, cx4 + 0.06, lane_y[2] + 0.09, "Container\n+ annotations\nrestored ✓",
     "#D5F5E3", "#27AE60", w=0.13, h=0.075, fw="bold")

ax.annotate("", xy=(cx4 + 0.003, lane_y[2] + 0.09),
            xytext=(cx4 + 0.003 - 0.049, lane_y[2] + 0.09),
            arrowprops=dict(arrowstyle="-|>", color=COLORS["k8s"], lw=1.5, mutation_scale=9))

vert_arrow(ax, cx4, lane_y[0] + 0.082, lane_y[1] + 0.145, COLORS["arrow_dn"])
vert_arrow(ax, cx4, lane_y[1] + 0.065, lane_y[2] + 0.15, COLORS["k8s"])

# ── Phase separators (vertical lines) ────────────────────────────────
for xs in phase_ends[:-1]:
    ax.axvline(xs, color=COLORS["phase_border"], lw=1.2, ls=":", zorder=1,
               ymin=(total_y) / 1.0, ymax=(total_y + total_h + 0.02) / 1.0)

plt.tight_layout(pad=0.3)
out = "figures/output/fig3_data_lifecycle"
plt.savefig(out + ".pdf", bbox_inches="tight", dpi=300)
plt.savefig(out + ".png", bbox_inches="tight", dpi=300)
print(f"Saved {out}.pdf / .png")
plt.close()
