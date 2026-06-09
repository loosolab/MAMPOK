"""Figure 4 — Project Lifecycle State Machine

State nodes with directed, labeled transitions.
States: PENDING → ACTIVE ↔ (EXPIRING) → STOPPED ← EXPIRED
"""

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
import numpy as np

COLORS = {
    "pending":   ("#D6EAF8", "#2E86C1"),
    "active":    ("#D5F5E3", "#1E8449"),
    "expiring":  ("#FDEBD0", "#D35400"),
    "stopped":   ("#F2F3F4", "#717D7E"),
    "expired":   ("#FADBD8", "#C0392B"),
    "arrow":     "#626567",
    "bg":        "white",
    "text":      "#1C2833",
    "cmd":       "#2C3E50",
}

STATE_SIZE = (0.22, 0.115)  # (width, height)


def draw_state(ax, cx, cy, name, sub, fc, ec, fontsize=10):
    w, h = STATE_SIZE
    box = FancyBboxPatch(
        (cx - w/2, cy - h/2), w, h,
        boxstyle="round,pad=0,rounding_size=0.025",
        facecolor=fc, edgecolor=ec, linewidth=2.5, zorder=3,
    )
    ax.add_patch(box)
    ax.text(cx, cy + 0.018, name,
            ha="center", va="center", fontsize=fontsize, fontweight="bold",
            color=COLORS["text"], zorder=4)
    ax.text(cx, cy - 0.030, sub,
            ha="center", va="center", fontsize=7.5,
            color="#717D7E", fontstyle="italic", zorder=4)


def curved_arrow(ax, x0, y0, x1, y1, label="", rad=0.0, color="#626567",
                 lw=1.6, label_offset=(0, 0)):
    style = f"arc3,rad={rad}"
    ax.annotate("",
        xy=(x1, y1), xytext=(x0, y0),
        arrowprops=dict(
            arrowstyle="-|>", color=color, lw=lw,
            connectionstyle=style, mutation_scale=13,
        ),
        zorder=5,
    )
    if label:
        mx = (x0 + x1) / 2 + label_offset[0]
        my = (y0 + y1) / 2 + label_offset[1]
        ax.text(mx, my, label,
                ha="center", va="center", fontsize=8,
                color=color, fontweight="bold",
                bbox=dict(boxstyle="round,pad=0.2", facecolor="white",
                          edgecolor=color, lw=0.8, alpha=0.9),
                zorder=6)


fig, ax = plt.subplots(figsize=(13, 7))
ax.set_xlim(0, 1)
ax.set_ylim(0, 1)
ax.axis("off")
fig.patch.set_facecolor("white")

ax.set_title("Project Lifecycle State Machine", fontsize=13, fontweight="bold",
             color=COLORS["text"], pad=10)

# ── State positions ───────────────────────────────────────────────────
# PENDING (top left), ACTIVE (center right), EXPIRING (bottom center right),
# STOPPED (bottom center), EXPIRED (far right bottom)
states = {
    "PENDING":  (0.18, 0.72),
    "ACTIVE":   (0.50, 0.72),
    "EXPIRING": (0.72, 0.42),
    "STOPPED":  (0.38, 0.28),
    "EXPIRED":  (0.72, 0.18),
}
state_styles = {
    "PENDING":  (*COLORS["pending"],   "Not yet deployed"),
    "ACTIVE":   (*COLORS["active"],    "Running · URL live"),
    "EXPIRING": (*COLORS["expiring"],  "lifetime < 7 days"),
    "STOPPED":  (*COLORS["stopped"],   "K8s removed · S3 ✓"),
    "EXPIRED":  (*COLORS["expired"],   "lifetime < now"),
}

for name, (cx, cy) in states.items():
    fc, ec, sub = state_styles[name]
    draw_state(ax, cx, cy, name, sub, fc, ec)

# ── Transitions ───────────────────────────────────────────────────────
w, h = STATE_SIZE
hw, hh = w / 2, h / 2

# PENDING → ACTIVE
curved_arrow(ax,
    states["PENDING"][0] + hw, states["PENDING"][1],
    states["ACTIVE"][0] - hw, states["ACTIVE"][1],
    label="mampok deploy", color=COLORS["active"][1],
    label_offset=(0, 0.04))

# ACTIVE → STOPPED (down-left)
curved_arrow(ax,
    states["ACTIVE"][0] - 0.04, states["ACTIVE"][1] - hh,
    states["STOPPED"][0] + 0.02, states["STOPPED"][1] + hh,
    label="mampok stop", color=COLORS["stopped"][1], rad=0.15,
    label_offset=(-0.07, 0))

# STOPPED → ACTIVE (up-right)
curved_arrow(ax,
    states["STOPPED"][0] + 0.04, states["STOPPED"][1] + hh,
    states["ACTIVE"][0] - 0.02, states["ACTIVE"][1] - hh,
    label="mampok redeploy", color=COLORS["active"][1], rad=0.15,
    label_offset=(0.08, 0))

# ACTIVE → EXPIRING (right-down, time passes)
curved_arrow(ax,
    states["ACTIVE"][0] + hw * 0.7, states["ACTIVE"][1] - hh,
    states["EXPIRING"][0], states["EXPIRING"][1] + hh,
    label="time passes\n(lifetime − now < 7d)", color=COLORS["expiring"][1], rad=-0.2,
    label_offset=(0.1, 0.04))

# EXPIRING → STOPPED (down)
curved_arrow(ax,
    states["EXPIRING"][0] - hw * 0.6, states["EXPIRING"][1] - hh,
    states["STOPPED"][0] + hw * 0.8, states["STOPPED"][1] + hh * 0.5,
    label="mampok stop", color=COLORS["stopped"][1], rad=0.1,
    label_offset=(0.03, -0.04))

# EXPIRING → EXPIRED (down)
curved_arrow(ax,
    states["EXPIRING"][0], states["EXPIRING"][1] - hh,
    states["EXPIRED"][0], states["EXPIRED"][1] + hh,
    label="lifetime < now", color=COLORS["expired"][1], rad=0.0,
    label_offset=(0.12, 0))

# EXPIRED → STOPPED (left)
curved_arrow(ax,
    states["EXPIRED"][0] - hw, states["EXPIRED"][1],
    states["STOPPED"][0] + hw, states["STOPPED"][1] - hh * 0.3,
    label="mampok stop-expired\n(batch)", color=COLORS["expired"][1], rad=-0.2,
    label_offset=(0, -0.07))

# STOPPED → ACTIVE self-loop label (--reupload)
ax.text(0.44, 0.52, "--reupload flag\nuploads new files", ha="center", va="center",
        fontsize=7, color=COLORS["active"][1], fontstyle="italic",
        bbox=dict(boxstyle="round,pad=0.2", facecolor="white",
                  edgecolor=COLORS["active"][1], lw=0.7, alpha=0.8))

# ── Legend ────────────────────────────────────────────────────────────
legend_items = [
    mpatches.Patch(facecolor=COLORS["pending"][0],  edgecolor=COLORS["pending"][1],  label="PENDING"),
    mpatches.Patch(facecolor=COLORS["active"][0],   edgecolor=COLORS["active"][1],   label="ACTIVE"),
    mpatches.Patch(facecolor=COLORS["expiring"][0], edgecolor=COLORS["expiring"][1], label="EXPIRING"),
    mpatches.Patch(facecolor=COLORS["stopped"][0],  edgecolor=COLORS["stopped"][1],  label="STOPPED"),
    mpatches.Patch(facecolor=COLORS["expired"][0],  edgecolor=COLORS["expired"][1],  label="EXPIRED"),
]
ax.legend(handles=legend_items, loc="lower left", fontsize=8.5,
          framealpha=0.95, edgecolor=COLORS["arrow"],
          bbox_to_anchor=(0.01, 0.03))

# ── Batch note ────────────────────────────────────────────────────────
ax.text(0.5, 0.04,
        "mampok stop-expired — batch command that stops all projects where lifetime < now",
        ha="center", va="center", fontsize=8, color="#7F8C8D", fontstyle="italic")

plt.tight_layout(pad=0.4)
out = "figures/output/fig4_state_machine"
plt.savefig(out + ".pdf", bbox_inches="tight", dpi=300)
plt.savefig(out + ".png", bbox_inches="tight", dpi=300)
print(f"Saved {out}.pdf / .png")
plt.close()
