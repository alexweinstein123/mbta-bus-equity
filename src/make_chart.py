"""Chart: on-time rate by income quartile vs car-free quartile.

Usage:
    python src/make_chart.py

Needs ridership.py to have run first. Reads results/reliability_by_quartile.csv
and writes figures/chart_reliability_by_quartile.png (for the StoryMap and README).
Two panels share one y-axis, so the flat income bars and the rising car-free bars
compare directly. The dashed line is the MBTA's 70% reliability target.
"""

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "results" / "reliability_by_quartile.csv"
OUT = ROOT / "figures" / "chart_reliability_by_quartile.png"

FONT = "Segoe UI"
INK, MUTED, GRID = "#212529", "#5F6368", "#E3E5E8"
INCOME_COLOR = "#737A82"   # neutral: the measure that shows no difference
CARFREE_COLOR = "#756BB1"  # the maps' car-free purple
TARGET = 0.70

PANELS = [
    ("Income", "By median household income", INCOME_COLOR,
     ["Under $84k", "$84k–$112k", "$112k–$145k", "Over $145k"]),
    ("Car-free share", "By share of households without a car", CARFREE_COLOR,
     ["Under 9%", "9–17%", "17–33%", "Over 33%"]),
]


def main():
    df = pd.read_csv(DATA)
    plt.rcParams.update({"font.family": FONT, "text.color": INK, "axes.labelcolor": MUTED,
                         "xtick.color": MUTED, "ytick.color": MUTED,
                         "text.parse_math": False})  # "$84k–$112k" is text, not a formula
    fig, axes = plt.subplots(1, 2, figsize=(10, 5.2), sharey=True, dpi=300)

    for ax, (measure, subtitle, color, labels) in zip(axes, PANELS):
        values = df[df.measure == measure].on_time_by_rider.to_numpy()
        bars = ax.bar(range(4), values, width=0.62, color=color, zorder=2)
        for b, v in zip(bars, values):  # inside the bar top, clear of the target line
            ax.text(b.get_x() + b.get_width() / 2, v - 0.025, f"{v:.0%}", ha="center", va="top",
                    fontsize=11, color="white", fontweight="semibold")
        ax.axhline(TARGET, color=INK, linewidth=1, linestyle=(0, (4, 3)), zorder=3)
        ax.set_xticks(range(4), labels, fontsize=9.5)
        ax.set_title(subtitle, loc="left", fontsize=11.5, color=INK, pad=10)
        ax.set_xlabel("Quartile of the stop's walkshed, lowest to highest", fontsize=9)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color(GRID)
        ax.tick_params(axis="both", length=0)
        ax.grid(axis="y", color=GRID, linewidth=0.8, zorder=0)

    axes[0].set_ylim(0, 0.85)
    axes[0].set_yticks([0, 0.2, 0.4, 0.6, 0.8], ["0%", "20%", "40%", "60%", "80%"], fontsize=9)
    axes[0].set_ylabel("Share of timepoints on time, weighted by riders", fontsize=9)
    axes[1].text(3.42, TARGET + 0.012, "MBTA target 70%", ha="right", va="bottom", fontsize=8.5, color=INK)

    fig.suptitle("Buses are least reliable where nearly everyone owns a car; income makes no difference",
                 x=0.06, y=0.97, ha="left", fontsize=15, fontweight="bold", color=INK)
    fig.text(0.06, 0.02, "Data: MBTA Bus Arrival Departure Times and Bus Ridership, Fall 2025; U.S. Census Bureau ACS "
             "2020–2024. Quartiles of 1,103 timepoint stops by the demographics of their quarter-mile walkshed. "
             "Chart: Alex Weinstein, 2026.", fontsize=7, color=MUTED, wrap=True)
    fig.subplots_adjust(left=0.08, right=0.98, top=0.85, bottom=0.2, wspace=0.08)
    OUT.parent.mkdir(exist_ok=True)
    fig.savefig(OUT, facecolor="white")
    print(f"Wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
