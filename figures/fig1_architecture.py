"""Figure 1 — System Architecture Overview

Three-column layout: Configuration Inputs | Mampok Core | Infrastructure Outputs
"""

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
import matplotlib.patheffects as pe

COLORS = {
    "input_header": "#1B4F72",
    "input_box":    "#D6EAF8",
    "input_border": "#2E86C1",
    "mampok_dark":  "#0E6655",
    "mampok_light": "#D1F2EB",
    "mampok_border":"#148F77",
    "k8s_header":   "#154360",
    "k8s_box":      "#D4E6F1",
    "k8s_border":   "#2874A6",
    "s3_header":    "#784212",
    "s3_box":       "#FDEBD0",
    "s3_border":    "#D35400",
    "arrow":        "#5D6D7E",
    "text_dark":    "#1C2833",
    "text_light":   "#FFFFFF",
    "divider":      "#D5D8DC",
    "url":          "#148F77",
}

def rounded_box(ax, x, y, w, h, color_face, color_edge, radius=0.015, lw=1.5, zorder=2):
    box = FancyBboxPatch(
        (x, y), w, h,
        boxstyle=f"round,pad=0,rounding_size={radius}",
        facecolor=color_face,
        edgecolor=color_edge,
        linewidth=lw,
        zorder=zorder,
    )
    ax.add_patch(box)
    return box

def header_box(ax, x, y, w, h, color_face, color_edge, label, fontsize=9, radius=0.015):
    rounded_box(ax, x, y, w, h, color_face, color_edge, radius=radius, lw=2, zorder=3)
    ax.text(x + w / 2, y + h / 2, label,
            ha="center", va="center", fontsize=fontsize,
            fontweight="bold", color=COLORS["text_light"], zorder=4)

def content_box(ax, x, y, w, h, color_face, color_edge, lines, fontsize=7.5, radius=0.012):
    rounded_box(ax, x, y, w, h, color_face, color_edge, radius=radius, lw=1.2, zorder=3)
    text = "\n".join(lines)
    ax.text(x + w / 2, y + h / 2, text,
            ha="center", va="center", fontsize=fontsize,
            color=COLORS["text_dark"], zorder=4, linespacing=1.5,
            family="monospace")

def arrow(ax, x0, y0, x1, y1, color="#5D6D7E"):
    ax.annotate("",
        xy=(x1, y1), xytext=(x0, y0),
        arrowprops=dict(
            arrowstyle="-|>",
            color=color,
            lw=1.6,
            mutation_scale=12,
        ),
        zorder=5,
    )


fig, ax = plt.subplots(figsize=(14, 7))
ax.set_xlim(0, 1)
ax.set_ylim(0, 1)
ax.axis("off")
fig.patch.set_facecolor("white")

# ── Column dividers ──────────────────────────────────────────────────
for xd in [0.335, 0.665]:
    ax.axvline(xd, color=COLORS["divider"], lw=1, ls="--", zorder=1)

# ── Column headers ───────────────────────────────────────────────────
ax.text(0.167, 0.97, "Configuration Inputs", ha="center", va="top",
        fontsize=10, fontweight="bold", color=COLORS["text_dark"])
ax.text(0.500, 0.97, "Mampok", ha="center", va="top",
        fontsize=10, fontweight="bold", color=COLORS["text_dark"])
ax.text(0.833, 0.97, "Infrastructure Outputs", ha="center", va="top",
        fontsize=10, fontweight="bold", color=COLORS["text_dark"])

# ════════════════════════════════════════════════════════════════════
# LEFT COLUMN — inputs
# ════════════════════════════════════════════════════════════════════
left_x, left_w = 0.02, 0.29

# Analyst → mamplan.json
header_box(ax, left_x, 0.785, left_w, 0.07, COLORS["input_header"], COLORS["input_header"],
           "Analyst  →  mamplan.json", fontsize=8.5)
content_box(ax, left_x, 0.665, left_w, 0.115, COLORS["input_box"], COLORS["input_border"],
            ["tool, files[], project_id",
             "owner, analyst, datatype",
             "cluster, lifetime, auth"], fontsize=7.5)

# Admin → mamplate.json
header_box(ax, left_x, 0.525, left_w, 0.07, COLORS["input_header"], COLORS["input_header"],
           "Admin  →  mamplate.json", fontsize=8.5)
content_box(ax, left_x, 0.405, left_w, 0.115, COLORS["input_box"], COLORS["input_border"],
            ["image, pullPolicy, port",
             "resources (cpu / memory)",
             "command with __tokens__"], fontsize=7.5)

# DevOps → config.json
header_box(ax, left_x, 0.265, left_w, 0.07, COLORS["input_header"], COLORS["input_header"],
           "DevOps  →  config.json", fontsize=8.5)
content_box(ax, left_x, 0.145, left_w, 0.115, COLORS["input_box"], COLORS["input_border"],
            ["clusters: {host, namespace,",
             "  kubeconfig, ingressClass}",
             "s3: {endpoint, keys, prefix}"], fontsize=7.5)

# ════════════════════════════════════════════════════════════════════
# CENTER COLUMN — Mampok
# ════════════════════════════════════════════════════════════════════
mid_x, mid_w = 0.36, 0.28

# CLI box
header_box(ax, mid_x, 0.73, mid_w, 0.07, COLORS["mampok_dark"], COLORS["mampok_dark"],
           "CLI Interface", fontsize=9)
content_box(ax, mid_x, 0.62, mid_w, 0.105, COLORS["mampok_light"], COLORS["mampok_border"],
            ["deploy  /  stop  /  redeploy",
             "create-mamplan  /  check-status",
             "list-expiring  /  stop-expired"], fontsize=7.5)

# Arrow CLI → Orchestrator
arrow(ax, mid_x + mid_w / 2, 0.62, mid_x + mid_w / 2, 0.545, COLORS["mampok_dark"])

# Orchestrator box
header_box(ax, mid_x, 0.475, mid_w, 0.07, COLORS["mampok_dark"], COLORS["mampok_dark"],
           "Orchestrator", fontsize=9)
content_box(ax, mid_x, 0.32, mid_w, 0.15, COLORS["mampok_light"], COLORS["mampok_border"],
            ["1. Merge Mamplan + Mamplate",
             "2. Expand __token__ variables",
             "3. Build Kubernetes manifests",
             "4. Upload files to S3",
             "5. Apply & await readiness",
             "6. Write back status + URL"], fontsize=7.5)

# ════════════════════════════════════════════════════════════════════
# RIGHT COLUMN — outputs
# ════════════════════════════════════════════════════════════════════
right_x, right_w = 0.685, 0.295

# Kubernetes block
header_box(ax, right_x, 0.70, right_w, 0.07, COLORS["k8s_header"], COLORS["k8s_header"],
           "K8s  Kubernetes Cluster", fontsize=8.5)
content_box(ax, right_x, 0.575, right_w, 0.12, COLORS["k8s_box"], COLORS["k8s_border"],
            ["Deployment  ·  Service",
             "Ingress  ·  Secret",
             "→ HTTPS URL generated"], fontsize=7.5)

# S3 block
header_box(ax, right_x, 0.42, right_w, 0.07, COLORS["s3_header"], COLORS["s3_header"],
           "S3  Object Storage", fontsize=8.5)
content_box(ax, right_x, 0.295, right_w, 0.12, COLORS["s3_box"], COLORS["s3_border"],
            ["analysis_data/  (input files)",
             "container_data/ (runtime outputs)",
             "→ persistent across restarts"], fontsize=7.5)

# ── ARROWS from left column to center ────────────────────────────────
mid_left_edge = mid_x
# Analyst arrow → CLI
arrow(ax, left_x + left_w, 0.820, mid_left_edge, 0.765, COLORS["arrow"])
# Admin arrow → Orchestrator
arrow(ax, left_x + left_w, 0.560, mid_left_edge, 0.540, COLORS["arrow"])
# DevOps arrow → Orchestrator
arrow(ax, left_x + left_w, 0.300, mid_left_edge + 0.02, 0.45, COLORS["arrow"])

# ── ARROWS from center to right column ───────────────────────────────
mid_right_edge = mid_x + mid_w
right_left_edge = right_x
# Orchestrator → K8s
arrow(ax, mid_right_edge, 0.595, right_left_edge, 0.640, COLORS["arrow"])
# Orchestrator → S3
arrow(ax, mid_right_edge, 0.400, right_left_edge, 0.460, COLORS["arrow"])

# ── URL label at bottom ───────────────────────────────────────────────
ax.text(0.833, 0.22, "https://cluster.institute.org/cellxgene/my-project",
        ha="center", va="center", fontsize=8, color=COLORS["url"],
        fontstyle="italic",
        bbox=dict(boxstyle="round,pad=0.3", facecolor="#D1F2EB",
                  edgecolor=COLORS["mampok_border"], lw=1))
arrow(ax, right_x + right_w / 2, 0.575, right_x + right_w / 2, 0.265, COLORS["url"])
ax.text(right_x + right_w / 2 + 0.005, 0.42, "public URL\n(+ opt. JWT auth)",
        ha="left", va="center", fontsize=7, color=COLORS["url"], fontstyle="italic")

plt.tight_layout(pad=0.3)
out = "figures/output/fig1_architecture"
plt.savefig(out + ".pdf", bbox_inches="tight", dpi=300)
plt.savefig(out + ".png", bbox_inches="tight", dpi=300)
print(f"Saved {out}.pdf / .png")
plt.close()
