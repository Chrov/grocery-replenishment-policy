"""
Render the README figures from the committed CSV extracts in dashboard/data/.

No database or model run is required: the extracts are produced by
`dashboard/export_tableau_extracts.py` after the dbt build, and this script
turns them into the five charts embedded in the project README.

Usage:  python reports/make_figures.py
"""
from __future__ import annotations

import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "dashboard", "data")
OUT = os.path.join(HERE, "figures")
os.makedirs(OUT, exist_ok=True)

INK, MUTED, GRID = "#212121", "#8a9099", "#dfe3e6"
BLUE, ORANGE, GREEN, RED = "#1f77b4", "#e8710a", "#2e8b57", "#c1121f"
CLASS_COLORS = {"A": "#1f4e79", "B": "#4a90c4", "C": "#a8c8e0"}

plt.rcParams.update({
    "figure.dpi": 130,
    "savefig.dpi": 130,
    "savefig.facecolor": "white",
    "figure.facecolor": "white",
    "axes.facecolor": "white",
    "font.size": 11,
    "axes.titlesize": 12.5,
    "axes.titleweight": "bold",
    "axes.titlecolor": INK,
    "axes.labelcolor": INK,
    "axes.edgecolor": GRID,
    "axes.grid": True,
    "axes.axisbelow": True,   # grid behind bars, not painted over them
    "grid.color": GRID,
    "grid.alpha": 0.9,
    "grid.linewidth": 0.8,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "xtick.color": MUTED,
    "ytick.color": MUTED,
    "legend.frameon": False,
})

stats: dict[str, str] = {}


def read(name: str) -> pd.DataFrame:
    return pd.read_csv(os.path.join(DATA, name), encoding="utf-8-sig")


def save(fig, name: str) -> None:
    path = os.path.join(OUT, name)
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("  -> reports/figures/" + name)


# ---------------------------------------------------------------------
# 1. Demand signals: weekly rhythm + the April 2016 earthquake
# ---------------------------------------------------------------------
def fig_demand_signals() -> None:
    df = read("demand_daily.csv")
    df["date"] = pd.to_datetime(df["date"])
    daily = df.groupby("date", as_index=False)["units_sold"].sum()

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 4.4),
                                   gridspec_kw={"width_ratios": [1.85, 1]})

    ax1.plot(daily["date"], daily["units_sold"], color="#b9c6d4", lw=0.7,
             label="Units sold each day")
    ax1.plot(daily["date"], daily["units_sold"].rolling(7, center=True).mean(),
             color=BLUE, lw=1.9, label="7-day moving average (the underlying trend)")
    ax1.axvspan(pd.Timestamp("2016-04-16"), pd.Timestamp("2016-04-30"),
                color=RED, alpha=0.13)

    quake = daily[(daily.date >= "2016-04-01") & (daily.date <= "2016-05-10")]
    before = quake[quake.date < "2016-04-16"]["units_sold"].mean()
    after = quake[(quake.date >= "2016-04-16") & (quake.date <= "2016-04-30")]["units_sold"].mean()
    quake_lift = after / before - 1
    stats["earthquake_lift"] = "{:+.1%}".format(quake_lift)

    ax1.annotate("2016 earthquake\n{:+.0%} for two weeks".format(quake_lift),
                 xy=(pd.Timestamp("2016-04-23"), after),
                 xytext=(pd.Timestamp("2015-10-15"), daily["units_sold"].max() * 0.99),
                 color=RED, fontsize=10.5, fontweight="bold", ha="center",
                 arrowprops=dict(arrowstyle="->", color=RED, lw=1.2))
    ax1.set_title("Demand is seasonal, and it reacts to real-world shocks")
    ax1.set_ylabel("Units sold per day")
    ax1.legend(loc="lower right", fontsize=9.5)
    ax1.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))

    dow_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    daily["dow"] = daily["date"].dt.day_name()
    dow = daily.groupby("dow")["units_sold"].mean().reindex(dow_order)
    weekend_lift = dow[["Saturday", "Sunday"]].mean() / dow[dow_order[:5]].mean() - 1
    stats["weekend_lift"] = "{:+.0%}".format(weekend_lift)

    colors = [ORANGE if d in ("Saturday", "Sunday") else BLUE for d in dow_order]
    ax2.bar([d[:3] for d in dow_order], dow.values, color=colors)
    ax2.set_title("Weekends run {:+.0%} above weekdays".format(weekend_lift))
    ax2.set_ylabel("Average units per day")

    fig.tight_layout()
    save(fig, "01_demand_signals.png")


# ---------------------------------------------------------------------
# 2. Forecast accuracy on the 15-day hold-out
# ---------------------------------------------------------------------
def fig_forecast_accuracy() -> None:
    fva = read("forecast_vs_actual.csv")
    fva["date"] = pd.to_datetime(fva["date"])
    wide = fva.pivot(index="date", columns="model", values="units")
    summary = read("forecast_wmape_summary.csv").sort_values("wmape", ascending=False)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 4.4),
                                   gridspec_kw={"width_ratios": [1.7, 1]})

    style = {"Seasonal naive": (MUTED, "--", 1.3),
             "Prophet": (BLUE, "--", 1.3),
             "SARIMAX": (ORANGE, "--", 1.3),
             "LightGBM": (GREEN, "-", 2.2)}
    for model, (color, ls, lw) in style.items():
        if model in wide:
            ax1.plot(wide.index, wide[model], ls, color=color, lw=lw, label=model)
    ax1.plot(wide.index, wide["Actual"], "o-", color=INK, lw=2.2, ms=4.5,
             label="Actual", zorder=5)
    ax1.set_title("15-day hold-out: LightGBM tracks the actual demand curve")
    ax1.set_ylabel("Units per day")
    ax1.legend(ncol=3, loc="upper left", fontsize=9.5)
    ax1.xaxis.set_major_locator(mdates.DayLocator(interval=2))
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))

    bar_colors = [GREEN if m == "LightGBM" else MUTED for m in summary["model"]]
    bars = ax2.barh(summary["model"], summary["wmape"], color=bar_colors, height=0.62)
    for bar, (_, row) in zip(bars, summary.iterrows()):
        label = "{:.3f}".format(row["wmape"])
        if row["vs_baseline_pct"] > 0:
            label += "   -{:.0f}% vs baseline".format(row["vs_baseline_pct"])
        ax2.text(row["wmape"] + 0.012, bar.get_y() + bar.get_height() / 2, label,
                 va="center", fontsize=10, color=INK,
                 fontweight="bold" if row["model"] == "LightGBM" else "normal")
    ax2.set_xlim(0, summary["wmape"].max() * 1.8)
    ax2.set_xlabel("WMAPE (lower is better)")
    ax2.set_title("Every model clears the seasonal-naive bar")
    ax2.grid(axis="y", visible=False)

    best = summary.iloc[-1]
    stats["best_model"] = "{} WMAPE {:.3f} (-{:.0f}%)".format(
        best["model"], best["wmape"], best["vs_baseline_pct"])

    fig.tight_layout()
    save(fig, "02_forecast_accuracy.png")


# ---------------------------------------------------------------------
# 3. ABC concentration
# ---------------------------------------------------------------------
def fig_abc_pareto() -> None:
    abc = read("abc_items.csv").sort_values("rank")
    n = len(abc)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 4.4),
                                   gridspec_kw={"width_ratios": [1.5, 1]})

    n_a = int((abc["abc_class"] == "A").sum())
    share_a = 100 * abc.loc[abc.abc_class == "A", "total_sales"].sum() / abc["total_sales"].sum()
    stats["abc"] = "class A = {}/{} items ({:.0f}%) = {:.0f}% of sales".format(
        n_a, n, 100 * n_a / n, share_a)

    ax1.bar(abc["rank"], 100 * abc["total_sales"] / abc["total_sales"].sum(),
            color=[CLASS_COLORS[c] for c in abc["abc_class"]], width=0.85)
    ax1.set_title("Sales concentrate in a handful of items (Pareto)")
    ax1.set_xlabel("Items ranked by sales, highest first")
    ax1.set_ylabel("Share of sales of each item (%)", color=CLASS_COLORS["A"])
    ax1.tick_params(axis="y", colors=CLASS_COLORS["A"])

    ax1b = ax1.twinx()
    cum_line, = ax1b.plot(abc["rank"], 100 * abc["cum_pct"], color=INK, lw=2,
                          label="Running total of sales (right axis)")
    thr_line = ax1b.axhline(80, color=RED, ls="--", lw=1.2, label="80% of all sales")
    cross_y = 100 * abc["cum_pct"].iloc[n_a - 1]
    ax1b.plot([n_a], [cross_y], "o", color=RED, ms=9, zorder=6)
    ax1b.set_ylim(0, 105)
    ax1b.set_ylabel("Running total of sales (%)")
    ax1b.grid(False)
    ax1b.legend(handles=[cum_line, thr_line], loc="lower right", fontsize=9.5)

    ax1b.annotate("Adding items left to right,\n"
                  "the running total crosses 80% here:\n"
                  "{} items ({:.0f}% of the catalog)\n"
                  "carry {:.0f}% of sales".format(n_a, 100 * n_a / n, share_a),
                  xy=(n_a + 0.8, cross_y), xytext=(n_a + 4, 38),
                  fontsize=10, fontweight="bold", color=INK,
                  arrowprops=dict(arrowstyle="->", color=INK, lw=1.2))

    grp = abc.groupby("abc_class").agg(items=("item_nbr", "count"),
                                       sales=("total_sales", "sum"))
    grp["pct_items"] = 100 * grp["items"] / grp["items"].sum()
    grp["pct_sales"] = 100 * grp["sales"] / grp["sales"].sum()
    x = np.arange(len(grp))
    ax2.bar(x - 0.2, grp["pct_items"], width=0.38, color=MUTED, label="% of items")
    ax2.bar(x + 0.2, grp["pct_sales"], width=0.38,
            color=[CLASS_COLORS[c] for c in grp.index], label="% of sales")
    for xi, (pi, ps) in enumerate(zip(grp["pct_items"], grp["pct_sales"])):
        ax2.text(xi - 0.2, pi + 1.5, "{:.0f}%".format(pi), ha="center",
                 fontsize=9.5, color=MUTED)
        ax2.text(xi + 0.2, ps + 1.5, "{:.0f}%".format(ps), ha="center",
                 fontsize=9.5, fontweight="bold", color=INK)
    ax2.set_xticks(x, ["Class " + c for c in grp.index])
    ax2.set_ylim(0, 92)
    ax2.set_ylabel("%")
    ax2.set_title("Inventory effort should follow value, not item count")
    ax2.legend(fontsize=9.5)
    ax2.grid(axis="x", visible=False)

    fig.tight_layout()
    save(fig, "03_abc_pareto.png")


# ---------------------------------------------------------------------
# 4. Service level vs cost
# ---------------------------------------------------------------------
def fig_service_tradeoff() -> None:
    c = read("service_level_curve.csv")
    x = 100 * c["service_level"]

    fig, ax = plt.subplots(figsize=(9.5, 4.6))
    ax.plot(x, c["holding_cost"], "o-", color=BLUE, lw=1.8, label="Holding cost")
    ax.plot(x, c["expected_lost_sales"], "o-", color=RED, lw=1.8, label="Expected lost sales")
    ax.plot(x, c["total_cost"], "o-", color=INK, lw=2.6, label="Total cost")

    opt = c.loc[c["total_cost"].idxmin()]
    flat = c[c["total_cost"] <= c["total_cost"].min() * 1.02]
    lo, hi = 100 * flat["service_level"].min(), 100 * flat["service_level"].max()
    ax.axvspan(lo, hi, color=GREEN, alpha=0.10)
    ax.text((lo + hi) / 2, c["total_cost"].max() * 1.02,
            "Economically flat between {:.0f}% and {:.0f}%\n"
            "(\\${:.2f} vs \\${:.2f} total cost)".format(
                lo, hi, flat["total_cost"].min(), flat["total_cost"].max()),
            fontsize=10.5, fontweight="bold", color=INK, ha="center", va="center")
    stats["service_optimum"] = "min total cost at {:.0%} (${:.2f}); flat {:.0f}-{:.0f}%".format(
        opt["service_level"], opt["total_cost"], lo, hi)

    ax.set_ylim(0, c["total_cost"].max() * 1.12)
    ax.set_title("Past ~95% service, extra buffer costs more than the stockouts it prevents",
                 fontsize=12, pad=12)
    ax.set_xlabel("Target service level (%)")
    ax.set_ylabel("Cost per replenishment cycle ($)")
    ax.set_xticks(x, ["{:.0f}".format(v) for v in x])
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.19), ncol=3, fontsize=10)
    fig.tight_layout()
    save(fig, "04_service_level_tradeoff.png")


# ---------------------------------------------------------------------
# 5. The policy, and what a better forecast is worth
# ---------------------------------------------------------------------
def fig_inventory_impact() -> None:
    pol = read("inventory_policy.csv")

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 4.4))

    grp = (pol.groupby("abc")
              .agg(items=("item_nbr", "count"),
                   safety_stock=("safety_stock", "mean"),
                   service_level=("service_level", "mean"))
              .reindex(["A", "B", "C"]))
    bars = ax1.bar(grp.index, grp["safety_stock"],
                   color=[CLASS_COLORS[c] for c in grp.index], width=0.6)
    for bar, (cls, row) in zip(bars, grp.iterrows()):
        ax1.text(bar.get_x() + bar.get_width() / 2, row["safety_stock"] + 0.7,
                 "{:.1f} units\n{:.0%} service - {} items".format(
                     row["safety_stock"], row["service_level"], int(row["items"])),
                 ha="center", fontsize=10, color=INK)
    ax1.set_ylim(0, grp["safety_stock"].max() * 1.42)
    ax1.set_title("Buffer is allocated by class, not spread evenly")
    ax1.set_ylabel("Average safety stock per item (units)")
    ax1.set_xlabel("ABC class")
    ax1.grid(axis="x", visible=False)

    total = pol["safety_stock"].sum()
    reductions = [0.0, 0.10, 0.20, 0.30]
    totals = [total * (1 - r) for r in reductions]
    colors = [MUTED] + [GREEN] * 3
    bars = ax2.bar(["today" if r == 0 else "-{:.0%}".format(r) for r in reductions],
                   totals, color=colors, width=0.6)
    for bar, t, r in zip(bars, totals, reductions):
        note = "{:,.0f} units".format(t)
        if r:
            note += "\n({:,.0f} freed)".format(total - t)
        ax2.text(bar.get_x() + bar.get_width() / 2, t + total * 0.02, note,
                 ha="center", fontsize=10, color=INK)
    ax2.set_ylim(0, total * 1.25)
    ax2.set_title("Safety stock scales 1:1 with forecast error")
    ax2.set_ylabel("Total safety stock (units)")
    ax2.set_xlabel("Reduction in forecast error, service level held constant")
    ax2.grid(axis="x", visible=False)
    stats["safety_stock"] = "{:,.0f} units across {} items; -20% error frees {:,.0f} units".format(
        total, len(pol), total * 0.2)

    fig.tight_layout()
    save(fig, "05_inventory_impact.png")


if __name__ == "__main__":
    print("Rendering README figures from dashboard/data/ ...")
    fig_demand_signals()
    fig_forecast_accuracy()
    fig_abc_pareto()
    fig_service_tradeoff()
    fig_inventory_impact()
    print("\nHeadline numbers used in the README:")
    for k, v in stats.items():
        print("  {:18s} {}".format(k, v))
