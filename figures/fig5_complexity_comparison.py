"""Figure 5 — Deployment Complexity Reduction

Left panel: grouped horizontal bar chart (manual vs. Mampok steps per category)
Right panel: annotated step-by-step comparison list
"""

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.gridspec as gridspec
import numpy as np

COLORS = {
    "manual":   "#C0392B",
    "manual_l": "#FADBD8",
    "mampok":   "#148F77",
    "mampok_l": "#D1F2EB",
    "auto":     "#D5D8DC",
    "text":     "#1C2833",
    "text_dim": "#7F8C8D",
    "bg":       "white",
    "check":    "#1E8449",
    "cross":    "#C0392B",
    "grid":     "#EAECEE",
}

categories = [
    "Infrastructure\nsetup",
    "Data\nupload",
    "Container\nconfiguration",
    "Deploy &\nmonitor",
    "Lifecycle\nmanagement",
]
manual_steps = [5, 3, 4, 3, 3]
mampok_steps = [0, 0, 1, 0, 0]

manual_details = [
    ["kubectl create namespace",
     "kubectl create secret (S3)",
     "Create kubeconfig entry",
     "Configure TLS / cert-manager",
     "Set up Ingress controller"],
    ["aws s3 mb s3://bucket",
     "aws s3 cp data.h5ad s3://…",
     "Verify upload integrity"],
    ["Write Deployment YAML",
     "Write Service YAML",
     "Write Ingress YAML",
     "Configure resource limits"],
    ["kubectl apply -f *.yaml",
     "kubectl get pods (polling)",
     "kubectl describe (debug)"],
    ["Write cleanup cron job",
     "kubectl delete resources",
     "aws s3 rm (data cleanup)"],
]
mampok_details = [
    [("Automated by Mampok", False)] * 5,
    [("Automated by Mampok", False)] * 3,
    [("Write mamplan.json", True),
     ("Automated by Mampok", False),
     ("Automated by Mampok", False),
     ("Automated by Mampok", False)],
    [("Automated by Mampok", False)] * 3,
    [("mampok stop-expired (cron)", True),
     ("Automated by Mampok", False),
     ("Automated by Mampok", False)],
]

fig = plt.figure(figsize=(14, 7))
gs = gridspec.GridSpec(1, 2, width_ratios=[1, 1.2], wspace=0.08)
ax_bar = fig.add_subplot(gs[0])
ax_list = fig.add_subplot(gs[1])
fig.patch.set_facecolor("white")

# ════════════════════════════════════════════════════════════════════
# LEFT — Horizontal grouped bar chart
# ════════════════════════════════════════════════════════════════════
n_cats = len(categories)
y_pos = np.arange(n_cats) * 1.4
bar_h = 0.5

# Manual bars
bars_m = ax_bar.barh(y_pos + bar_h / 2 + 0.03, manual_steps, height=bar_h,
                     color=COLORS["manual"], label="Manual (without Mampok)",
                     zorder=3, edgecolor="white", linewidth=0.5)
# Mampok bars
bars_k = ax_bar.barh(y_pos - bar_h / 2 - 0.03, mampok_steps, height=bar_h,
                     color=COLORS["mampok"], label="With Mampok",
                     zorder=3, edgecolor="white", linewidth=0.5)

# Value labels
for bar, val in zip(bars_m, manual_steps):
    ax_bar.text(bar.get_width() + 0.08, bar.get_y() + bar.get_height() / 2,
                str(val), va="center", ha="left", fontsize=10, fontweight="bold",
                color=COLORS["manual"])

for bar, val in zip(bars_k, mampok_steps):
    if val == 0:
        ax_bar.text(0.15, bar.get_y() + bar.get_height() / 2,
                    "auto", va="center", ha="left", fontsize=8,
                    color=COLORS["text_dim"], fontstyle="italic")
    else:
        ax_bar.text(bar.get_width() + 0.08, bar.get_y() + bar.get_height() / 2,
                    str(val), va="center", ha="left", fontsize=10, fontweight="bold",
                    color=COLORS["mampok"])

ax_bar.set_yticks(y_pos)
ax_bar.set_yticklabels(categories, fontsize=9.5)
ax_bar.set_xlabel("Number of manual steps", fontsize=10)
ax_bar.set_xlim(0, 7.5)
ax_bar.set_title("Steps required per task", fontsize=11, fontweight="bold",
                 color=COLORS["text"], pad=10)
ax_bar.grid(axis="x", color=COLORS["grid"], lw=0.8, zorder=0)
ax_bar.spines[["top", "right"]].set_visible(False)
ax_bar.tick_params(left=False)

# Total annotation
total_manual = sum(manual_steps)
total_mampok = sum(mampok_steps)
ax_bar.text(0.97, 0.04,
            f"Total:\n{total_manual} manual steps\nvs. {total_mampok} with Mampok",
            ha="right", va="bottom", transform=ax_bar.transAxes,
            fontsize=9, color=COLORS["text"],
            bbox=dict(boxstyle="round,pad=0.5", facecolor=COLORS["mampok_l"],
                      edgecolor=COLORS["mampok"], lw=1.2))

legend = ax_bar.legend(loc="lower right", fontsize=9, framealpha=0.9,
                       edgecolor=COLORS["text_dim"])

# ════════════════════════════════════════════════════════════════════
# RIGHT — Step-by-step comparison list
# ════════════════════════════════════════════════════════════════════
ax_list.set_xlim(0, 1)
ax_list.set_ylim(0, 1)
ax_list.axis("off")
ax_list.set_title("Step-by-step comparison: deploying CellXGene",
                  fontsize=11, fontweight="bold", color=COLORS["text"], pad=10)

# Column headers
ax_list.text(0.26, 0.965, "Without Mampok", ha="center", va="top",
             fontsize=10, fontweight="bold", color=COLORS["manual"])
ax_list.text(0.76, 0.965, "With Mampok", ha="center", va="top",
             fontsize=10, fontweight="bold", color=COLORS["mampok"])
ax_list.axvline(0.5, color=COLORS["text_dim"], lw=1, ls="--",
                ymin=0.02, ymax=0.96)

# Flatten steps
all_manual = [step for cat in manual_details for step in cat]
all_mampok_raw = [entry for cat in mampok_details for entry in cat]

# Pad to same length
max_len = max(len(all_manual), len(all_mampok_raw))

n_display = 18  # max rows to show
step_h = 0.90 / n_display
y_start = 0.935

for i in range(min(n_display, max_len)):
    ys = y_start - i * step_h

    # Manual side
    if i < len(all_manual):
        ax_list.text(0.02, ys, "✗", ha="left", va="center", fontsize=9,
                     color=COLORS["cross"])
        ax_list.text(0.07, ys, all_manual[i], ha="left", va="center", fontsize=7.8,
                     color=COLORS["text"])

    # Mampok side
    if i < len(all_mampok_raw):
        step_text, is_user = all_mampok_raw[i]
        icon = "✓" if is_user else "—"
        col = COLORS["mampok"] if is_user else COLORS["text_dim"]
        ax_list.text(0.52, ys, icon, ha="left", va="center", fontsize=9, color=col)
        ax_list.text(0.57, ys, step_text, ha="left", va="center", fontsize=7.8,
                     color=col,
                     fontstyle="normal" if is_user else "italic")

# Divider lines between categories
cum = 0
for cat_steps in manual_details[:-1]:
    cum += len(cat_steps)
    yd = y_start - cum * step_h + step_h * 0.35
    ax_list.axhline(yd, color=COLORS["grid"], lw=0.8, xmin=0.01, xmax=0.99)

# Summary row
ax_list.axhline(0.04, color=COLORS["text_dim"], lw=1)
ax_list.text(0.26, 0.025, f"Total: {total_manual} manual steps",
             ha="center", va="center", fontsize=9, fontweight="bold",
             color=COLORS["manual"])
ax_list.text(0.76, 0.025,
             f"Total: {total_mampok} user step + 7 automated",
             ha="center", va="center", fontsize=9, fontweight="bold",
             color=COLORS["mampok"])

plt.tight_layout(pad=0.5)
out = "figures/output/fig5_complexity_comparison"
plt.savefig(out + ".pdf", bbox_inches="tight", dpi=300)
plt.savefig(out + ".png", bbox_inches="tight", dpi=300)
print(f"Saved {out}.pdf / .png")
plt.close()
