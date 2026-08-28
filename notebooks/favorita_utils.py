"""
Shared utilities for the project's notebooks.
Keeps the DuckDB connection, demand metrics and plotting helpers in one place
(avoids duplicating connection/metric code across EDA, forecasting and inventory).
"""
from __future__ import annotations
import os
import numpy as np
import pandas as pd

# Path to the database built by dbt (relative to notebooks/)
DB_PATH = os.environ.get("FAVORITA_DB", "../data/favorita.duckdb")


def get_connection():
    """Read-only DuckDB connection to the star schema."""
    import duckdb
    return duckdb.connect(DB_PATH, read_only=True)


def q(sql: str) -> pd.DataFrame:
    """Run SQL against the star schema and return a DataFrame."""
    con = get_connection()
    try:
        return con.sql(sql).df()
    finally:
        con.close()


# --- Demand metrics (identical to src/forecasting_pipeline.py) ------------
def wmape(y_true, y_pred) -> float:
    """Weighted MAPE: robust to intermittent demand."""
    y_true, y_pred = np.asarray(y_true, float), np.asarray(y_pred, float)
    denom = np.sum(np.abs(y_true))
    return float(np.sum(np.abs(y_true - y_pred)) / denom) if denom else np.nan


def rmse(y_true, y_pred) -> float:
    y_true, y_pred = np.asarray(y_true, float), np.asarray(y_pred, float)
    return float(np.sqrt(np.mean((y_true - y_pred) ** 2)))


def nwrmsle(y_true, y_pred, weights=None) -> float:
    """Normalized Weighted RMSLE (the competition's official metric).
    Pass weights=1.25 for perishables, 1.0 for the rest."""
    y_true, y_pred = np.asarray(y_true, float), np.asarray(y_pred, float)
    y_pred = np.clip(y_pred, 0, None)
    if weights is None:
        weights = np.ones_like(y_true)
    log_diff = (np.log1p(y_pred) - np.log1p(y_true)) ** 2
    return float(np.sqrt(np.sum(weights * log_diff) / np.sum(weights)))


# --- Consistent plot style -------------------------------------------------
def apply_plot_style():
    import matplotlib.pyplot as plt
    plt.rcParams.update({
        "figure.figsize": (11, 4.5),
        "axes.grid": True,
        "grid.alpha": 0.3,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "font.size": 11,
    })


# Shared palette so figures look the same across the three notebooks
COLORS = {
    "primary": "#1f77b4",
    "accent": "#ff7f0e",
    "good": "#2ca02c",
    "bad": "#d62728",
    "muted": "#7f7f7f",
}
