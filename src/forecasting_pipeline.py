"""
Demand forecasting and inventory optimization pipeline.

Shared implementation of everything the notebooks reuse: demand metrics
(WMAPE, RMSE, NWRMSLE), feature engineering, the four forecasting models,
walk-forward backtesting and the inventory formulas (safety stock, reorder
point, ABC classification, service-level trade-off).

Dependencies: pandas, numpy, scikit-learn, statsmodels, prophet, lightgbm.
pandas-gbq is only needed for the BigQuery path.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd


# =====================================================================
# 1. CONFIGURATION
# =====================================================================
@dataclass
class Config:
    project_id: str = "your_project"
    dataset: str = "favorita"
    horizon: int = 15            # days to forecast
    lead_time: int = 3           # replenishment days (for inventory)
    service_level: float = 0.95  # default target service level
    # z-scores by service level (safety stock)
    z_scores: dict = field(default_factory=lambda: {
        0.90: 1.2816, 0.95: 1.6449, 0.98: 2.0537, 0.99: 2.3263,
    })


# =====================================================================
# 2. DATA LOADING (from BigQuery)
# =====================================================================
def load_from_bigquery(cfg: Config, query: str) -> pd.DataFrame:
    """Read the base modeling table from BigQuery.

    Uses query 10 from 01_bigquery_setup.sql (item-store-day table with features).
    """
    import pandas_gbq  # noqa: local import so it isn't required when working offline
    df = pandas_gbq.read_gbq(query, project_id=cfg.project_id)
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").reset_index(drop=True)


# =====================================================================
# 3. FEATURE ENGINEERING (for the ML model)
# =====================================================================
def build_features(df: pd.DataFrame,
                   group_cols=("store_nbr", "item_nbr"),
                   target="unit_sales") -> pd.DataFrame:
    """Generate lags, rolling stats and calendar features.

    IMPORTANT: compute lags/rolling PER group (store-item) and always with
    shift() so no future information leaks in.
    """
    df = df.sort_values(list(group_cols) + ["date"]).reset_index(drop=True).copy()
    if df.duplicated(list(group_cols) + ["date"]).any():
        raise ValueError("Duplicate series-date keys")
    gaps = df.groupby(list(group_cols))["date"].diff().dropna()
    if not gaps.eq(pd.Timedelta(days=1)).all():
        raise ValueError("Lags require a complete daily calendar per series; do not silently treat missing days as zero")
    g = df.groupby(list(group_cols))[target]

    # Lags
    for lag in (7, 14, 28):
        df[f"lag_{lag}"] = g.shift(lag)

    # Rolling stats (over the already-shifted value -> no leakage)
    for window in (7, 28):
        df[f"roll_mean_{window}"] = g.transform(lambda s: s.shift(1).rolling(window, min_periods=1).mean())
        df[f"roll_std_{window}"] = g.transform(lambda s: s.shift(1).rolling(window, min_periods=1).std())

    # Calendar features (dow, day_of_month, month, is_payday, is_holiday,
    # oil_price, onpromotion) already come from the BigQuery query.
    return df


# =====================================================================
# 4. DEMAND METRICS
# =====================================================================
def wmape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Weighted MAPE: robust to intermittent demand (doesn't blow up with zeros).
    Interpretable as a volume-weighted error percentage.
    """
    y_true, y_pred = np.asarray(y_true), np.asarray(y_pred)
    denom = np.sum(np.abs(y_true))
    if denom == 0:
        return np.nan
    return np.sum(np.abs(y_true - y_pred)) / denom


def rmse(y_true, y_pred) -> float:
    y_true, y_pred = np.asarray(y_true), np.asarray(y_pred)
    return float(np.sqrt(np.mean((y_true - y_pred) ** 2)))


def nwrmsle(y_true, y_pred, weights=None) -> float:
    """Normalized Weighted Root Mean Squared Logarithmic Error.
    The competition's official metric. Weights perishables more heavily
    (pass weights=1.25 for perishables, 1.0 for the rest).
    """
    y_true, y_pred = np.asarray(y_true), np.asarray(y_pred)
    y_pred = np.clip(y_pred, 0, None)  # non-negative sales
    if weights is None:
        weights = np.ones_like(y_true, dtype=float)
    log_diff = (np.log1p(y_pred) - np.log1p(y_true)) ** 2
    return float(np.sqrt(np.sum(weights * log_diff) / np.sum(weights)))


# =====================================================================
# 5. BASELINES (mandatory as a reference)
# =====================================================================
def baseline_seasonal_naive(train: pd.DataFrame, horizon: int,
                            group_cols=("store_nbr", "item_nbr"),
                            target="unit_sales", season=7) -> pd.DataFrame:
    """Seasonal naive: a day's sales = the same weekday last week.
    In retail this baseline is surprisingly strong. RULE: if your model can't
    beat this, it's useless.
    """
    last = (train.sort_values("date")
                 .groupby(list(group_cols)).tail(season))
    # Repeat the last seasonal cycle across the horizon
    preds = []
    for _, grp in last.groupby(list(group_cols)):
        vals = grp[target].values
        rep = np.tile(vals, int(np.ceil(horizon / season)))[:horizon]
        base = {c: grp[c].iloc[0] for c in group_cols}
        for h, v in enumerate(rep):
            preds.append({**base, "h": h, "y_pred": v})
    return pd.DataFrame(preds)


# =====================================================================
# 6. FORECASTING MODELS
# =====================================================================
def fit_predict_prophet(train: pd.DataFrame, test: pd.DataFrame, horizon: int,
                        regressors=("promo_share", "oil_price", "is_holiday")):
    """Prophet: handles multiple seasonality, holidays and changepoints
    (useful for the earthquake shock).

    Expects `train`/`test` with columns: date, y, and the regressors.
    Returns the array of predictions (clipped to >= 0) for the horizon.
    """
    from prophet import Prophet
    regressors = list(regressors)
    dfp = train.rename(columns={"date": "ds"})[["ds", "y"] + regressors]
    m = Prophet(weekly_seasonality=True, yearly_seasonality=True,
                daily_seasonality=False, changepoint_prior_scale=0.05)
    for r in regressors:
        m.add_regressor(r)
    m.fit(dfp)
    future = test.rename(columns={"date": "ds"})[["ds"] + regressors]
    fc = m.predict(future)
    return np.clip(fc["yhat"].values, 0, None), m


def fit_predict_sarimax(train: pd.DataFrame, test: pd.DataFrame, horizon: int,
                        regressors=("promo_share", "oil_price", "is_holiday")):
    """SARIMAX: seasonal + exogenous regressors (promo, oil, holiday).
    order=(1,1,1), seasonal_order=(1,0,1,7) by default.

    Expects `train`/`test` with columns: y, and the regressors.
    Returns the array of predictions (clipped to >= 0) for the horizon.
    """
    from statsmodels.tsa.statespace.sarimax import SARIMAX
    regressors = list(regressors)
    y = train["y"].values
    ex_tr = train[regressors].values
    ex_te = test[regressors].values
    mod = SARIMAX(y, exog=ex_tr, order=(1, 1, 1), seasonal_order=(1, 0, 1, 7),
                  enforce_stationarity=False, enforce_invertibility=False)
    res = mod.fit(disp=False, maxiter=50)
    pred = res.forecast(steps=horizon, exog=ex_te)
    return np.clip(pred, 0, None), res


def fit_predict_lightgbm(train: pd.DataFrame, valid: pd.DataFrame, cfg: Config,
                         features=None, target="y", num_boost_round=200):
    """LightGBM on tabular features. Usually the strongest option in retail.

    Uses objective='tweedie' to handle intermittent demand (many zeros).
    Expects `train`/`valid` to already have the features built (lags, rolling,
    calendar) — see build_features() and the panel in notebook 02.

    Returns (valid with a 'pred' column, trained model).
    """
    import lightgbm as lgb
    if features is None:
        features = ["onpromotion", "dow", "day_of_month", "month", "is_payday",
                    "is_holiday", "days_to_nearest_holiday", "oil_price",
                    "oil_price_change", "perishable",
                    "lag_7", "lag_14", "lag_28", "roll_mean_7", "roll_mean_28"]
    features = [f for f in features if f in train.columns]

    dtrain = lgb.Dataset(train[features], label=train[target])
    params = dict(objective="tweedie", tweedie_variance_power=1.3, metric="rmse",
                  learning_rate=0.05, num_leaves=31, min_child_samples=20,
                  verbose=-1)
    model = lgb.train(params, dtrain, num_boost_round=num_boost_round)
    valid = valid.copy()
    valid["pred"] = np.clip(model.predict(valid[features]), 0, None)
    return valid, model


def recursive_predictions(model, history, future, features, group_cols=("item_nbr",), target="y"):
    """Fixed-origin prediction: future targets are discarded, never used as lags.

    Future exogenous fields must be known at the origin. Do not pass realized
    oil prices or unplanned promotions. A complete daily panel is required.
    """
    history = history.copy()
    future = future.copy()
    if history.date.max() >= future.date.min():
        raise ValueError("History and future must be strictly separated")
    future[target] = np.nan
    predictions = []
    for date in sorted(future.date.unique()):
        day = future[future.date == date].copy()
        panel = build_features(pd.concat([history, day], ignore_index=True), group_cols, target)
        day = panel[panel.date == date].copy()
        if day[features].isna().any().any():
            raise ValueError("Missing forecast features; provide sufficient history and known-at-origin inputs")
        day["pred"] = np.clip(model.predict(day[features]), 0, None)
        predictions.append(day)
        day[target] = day["pred"]
        history = pd.concat([history, day], ignore_index=True)
    return pd.concat(predictions, ignore_index=True)


# =====================================================================
# 7. TEMPORAL BACKTESTING (walk-forward / rolling origin)
# =====================================================================
def walk_forward_backtest(
    df: pd.DataFrame,
    forecast_fn: Callable[[pd.DataFrame, int], pd.DataFrame],
    cfg: Config,
    n_folds: int = 4,
    target: str = "unit_sales",
    group_cols=("store_nbr", "item_nbr"),
) -> pd.DataFrame:
    """Rolling-origin backtesting. NEVER use random k-fold on time series: it
    leaks the future into the past and gives false metrics.

    For each fold: train up to a cutoff, predict the horizon, measure, advance.
    """
    dates = np.sort(df["date"].unique())
    results = []

    for fold in range(n_folds):
        # The cutoff moves back `horizon` days per fold from the end
        cut_idx = len(dates) - cfg.horizon * (n_folds - fold)
        if cut_idx <= 0:
            continue
        cutoff = dates[cut_idx]
        horizon_end = dates[min(cut_idx + cfg.horizon - 1, len(dates) - 1)]

        train = df[df["date"] < cutoff]
        actual = df[(df["date"] >= cutoff) & (df["date"] <= horizon_end)]

        preds = forecast_fn(train, cfg.horizon)  # -> group_cols + h + y_pred

        # Join prediction with actual by (group, position in the horizon)
        actual = actual.sort_values(list(group_cols) + ["date"]).copy()
        actual["h"] = actual.groupby(list(group_cols)).cumcount()
        merged = actual.merge(preds, on=list(group_cols) + ["h"], how="inner")

        if merged.empty:
            continue

        w = np.where(merged.get("perishable", 0) == 1, 1.25, 1.0)
        results.append({
            "fold": fold,
            "cutoff": pd.Timestamp(cutoff).date(),
            "n_obs": len(merged),
            "wmape": wmape(merged[target], merged["y_pred"]),
            "rmse": rmse(merged[target], merged["y_pred"]),
            "nwrmsle": nwrmsle(merged[target], merged["y_pred"], weights=w),
        })

    res = pd.DataFrame(results)
    if not res.empty:
        print("Backtest average -> WMAPE: %.3f | RMSE: %.2f | NWRMSLE: %.4f"
              % (res["wmape"].mean(), res["rmse"].mean(), res["nwrmsle"].mean()))
    return res


# =====================================================================
# 8. INVENTORY OPTIMIZATION
#    Translates forecast + error into replenishment decisions.
# =====================================================================
def z_for_service_level(service_level: float, cfg: Config) -> float:
    """Normal quantile for a target service level.

    Config.z_scores covers the four levels the policy assigns by ABC class; any
    other level (the perishable bump can land between them) is computed exactly
    instead of silently defaulting to the 95% value.
    """
    z = cfg.z_scores.get(round(service_level, 2))
    if z is None:
        from scipy.stats import norm
        z = float(norm.ppf(service_level))
    return float(z)


def safety_stock(sigma_forecast_error: float, lead_time: int,
                 service_level: float, cfg: Config) -> float:
    """safety_stock = z * sigma_error * sqrt(lead_time)

    sigma_forecast_error: standard deviation of the FORECAST error, taken per
    item from the backtest. A better forecast means a smaller sigma, which means
    less safety stock for the same service level.
    """
    z = z_for_service_level(service_level, cfg)
    return float(z * sigma_forecast_error * np.sqrt(lead_time))


def reorder_point(avg_daily_demand: float, lead_time: int,
                  ss: float) -> float:
    """ROP = (avg_daily_demand * lead_time) + safety_stock"""
    return float(avg_daily_demand * lead_time + ss)


def abc_classification(item_sales: pd.DataFrame,
                       item_col="item_nbr", sales_col="unit_sales") -> pd.DataFrame:
    """Classify items into A/B/C by cumulative contribution to sales.
    A: up to 80% | B: up to 95% | C: the rest.
    Used to assign differentiated service levels.
    """
    agg = (item_sales.groupby(item_col)[sales_col].sum()
                     .sort_values(ascending=False).reset_index())
    agg["cum_pct"] = agg[sales_col].cumsum() / agg[sales_col].sum()
    agg["abc"] = np.where(agg["cum_pct"] <= 0.80, "A",
                  np.where(agg["cum_pct"] <= 0.95, "B", "C"))
    return agg


def build_inventory_policy(
    forecast_error_by_item: pd.DataFrame,  # item_nbr, sigma_error, avg_demand, perishable
    abc: pd.DataFrame,                     # item_nbr, abc
    cfg: Config,
) -> pd.DataFrame:
    """Build the per-item inventory policy:
    safety stock + reorder point, with service level based on ABC class
    (and stricter for perishables).
    """
    # Differentiated service level by class
    sl_by_class = {"A": 0.98, "B": 0.95, "C": 0.90}

    df = forecast_error_by_item.merge(abc[["item_nbr", "abc"]],
                                      on="item_nbr", how="left")
    rows = []
    for _, r in df.iterrows():
        sl = sl_by_class.get(r["abc"], 0.95)
        # Perishables: bump half a step of strictness (less tolerance for stockout)
        if r.get("perishable", 0) == 1:
            sl = min(sl + 0.03, 0.99)
        ss = safety_stock(r["sigma_error"], cfg.lead_time, sl, cfg)
        rop = reorder_point(r["avg_demand"], cfg.lead_time, ss)
        rows.append({
            "item_nbr": r["item_nbr"],
            "abc": r["abc"],
            "perishable": r.get("perishable", 0),
            "service_level": sl,
            "safety_stock": round(ss, 1),
            "reorder_point": round(rop, 1),
        })
    return pd.DataFrame(rows)


def service_level_tradeoff(sigma_error: float, avg_demand: float,
                           holding_cost: float, cfg: Config) -> pd.DataFrame:
    """Generate the trade-off curve: higher service level means more safety
    stock and more holding cost, but less lost sales.
    For plotting in the dashboard and finding the break-even point.
    """
    rows = []
    for sl in (0.90, 0.95, 0.98, 0.99):
        ss = safety_stock(sigma_error, cfg.lead_time, sl, cfg)
        rows.append({
            "service_level": sl,
            "safety_stock": round(ss, 1),
            "holding_cost": round(ss * holding_cost, 2),  # cost of holding that buffer
        })
    return pd.DataFrame(rows)
