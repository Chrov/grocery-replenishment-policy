"""
Export Tableau-ready extracts for the demand & inventory dashboard.
Produces 4 flat CSVs in dashboard/data/ :
  1. demand_daily.csv      -> demand + seasonality view (all families/stores)
  2. forecast_vs_actual.csv-> model validation view (BEVERAGES/store 1)
  3. abc_items.csv         -> ABC segmentation view (all items)
  4. inventory_policy.csv  -> service-level trade-off + policy table
Each is denormalized and named for a non-technical audience.
"""
import os
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, "src")
sys.path.insert(0, "notebooks")
from favorita_utils import q  # uses the duckdb built by dbt

OUT = "dashboard/data"
os.makedirs(OUT, exist_ok=True)


def save(df, name):
    path = os.path.join(OUT, name)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"  -> {name}  ({len(df):,} rows, {df.shape[1]} cols)")


# ---------------------------------------------------------------------
# 1. Daily demand + seasonality (all families & stores)
# ---------------------------------------------------------------------
print("[1/4] demand_daily.csv")
demand = q("""
    select
        date,
        family,
        store_nbr,
        city,
        store_type,
        is_holiday,
        is_payday,
        is_weekend,
        sum(unit_sales_clipped) as units_sold,
        count(*)                as line_items
    from main_marts.fct_sales
    group by 1,2,3,4,5,6,7,8
    order by date
""")
demand["date"] = pd.to_datetime(demand["date"])
demand["day_of_week"] = demand["date"].dt.day_name()
demand["month_name"] = demand["date"].dt.month_name()
demand["year_month"] = demand["date"].dt.to_period("M").astype(str)
# earthquake annotation flag for a clean reference band in Tableau
demand["earthquake_window"] = (
    (demand["date"] >= "2016-04-16") & (demand["date"] <= "2016-04-30")
).astype(int)
save(demand, "demand_daily.csv")


# ---------------------------------------------------------------------
# 2. Forecast vs actual (BEVERAGES / store 1 — where models were run)
# ---------------------------------------------------------------------
print("[2/4] forecast_vs_actual.csv (retraining lightweight models)")
FAMILY, STORE, HORIZON = "BEVERAGES", 1, 15

series = q(f"""
    select date, sum(unit_sales_clipped) as y
    from main_marts.fct_sales
    where family = '{FAMILY}' and store_nbr = {STORE}
    group by date order by date
""")
series["date"] = pd.to_datetime(series["date"])
idx = pd.date_range(series["date"].min(), series["date"].max(), freq="D")
series = series.set_index("date").reindex(idx, fill_value=0).rename_axis("date").reset_index()

exog = q(f"""
    select date,
        avg(case when onpromotion then 1.0 else 0.0 end) as promo_share,
        max(oil_price) as oil_price,
        max(case when is_holiday then 1 else 0 end) as is_holiday
    from main_marts.fct_sales
    where family = '{FAMILY}' and store_nbr = {STORE}
    group by date
""")
exog["date"] = pd.to_datetime(exog["date"])
series = series.merge(exog, on="date", how="left")
series["promo_share"] = series["promo_share"].fillna(0)
series["is_holiday"] = series["is_holiday"].fillna(0)
series["oil_price"] = series["oil_price"].ffill().bfill()

REG = ["promo_share", "oil_price", "is_holiday"]
train, test = series.iloc[:-HORIZON].copy(), series.iloc[-HORIZON:].copy()

# baseline
def seasonal_naive(y, h, s=7):
    return np.tile(y[-s:], int(np.ceil(h/s)))[:h]
base_pred = seasonal_naive(train["y"].values, HORIZON)

# prophet
from prophet import Prophet
dfp = train.rename(columns={"date": "ds"})[["ds", "y"] + REG]
mp = Prophet(weekly_seasonality=True, yearly_seasonality=True,
             daily_seasonality=False, changepoint_prior_scale=0.05)
for r in REG: mp.add_regressor(r)
mp.fit(dfp)
prophet_pred = np.clip(mp.predict(test.rename(columns={"date": "ds"})[["ds"]+REG])["yhat"].values, 0, None)

# sarimax
from statsmodels.tsa.statespace.sarimax import SARIMAX
ms = SARIMAX(train["y"].values, exog=train[REG].values, order=(1,1,1),
             seasonal_order=(1,0,1,7), enforce_stationarity=False,
             enforce_invertibility=False).fit(disp=False, maxiter=50)
sarimax_pred = np.clip(ms.forecast(steps=HORIZON, exog=test[REG].values), 0, None)

# lightgbm (item grain, aggregated to compare)
import lightgbm as lgb
panel = q(f"""
    select date, item_nbr, unit_sales_clipped as y,
           case when onpromotion then 1 else 0 end as onpromotion,
           dow, day_of_month, month, is_payday, is_holiday,
           days_to_nearest_holiday, oil_price, oil_price_change, perishable
    from main_marts.fct_sales
    where family = '{FAMILY}' and store_nbr = {STORE}
    order by item_nbr, date
""")
panel["date"] = pd.to_datetime(panel["date"])
panel = panel.sort_values(["item_nbr", "date"])
g = panel.groupby("item_nbr")["y"]
for lag in (7,14,28): panel[f"lag_{lag}"] = g.shift(lag)
for w in (7,28):
    panel[f"roll_mean_{w}"] = g.shift(1).rolling(w, min_periods=1).mean().reset_index(level=0, drop=True)
panel = panel.dropna(subset=["lag_28"])
FEATS = ["onpromotion","dow","day_of_month","month","is_payday","is_holiday",
         "days_to_nearest_holiday","oil_price","oil_price_change","perishable",
         "lag_7","lag_14","lag_28","roll_mean_7","roll_mean_28"]
cut = panel["date"].max() - pd.Timedelta(days=HORIZON)
tr, te = panel[panel.date <= cut], panel[panel.date > cut].copy()
lgbm = lgb.train(dict(objective="tweedie", tweedie_variance_power=1.3, metric="rmse",
                      learning_rate=0.05, num_leaves=31, min_child_samples=20, verbose=-1),
                 lgb.Dataset(tr[FEATS], label=tr["y"]), num_boost_round=200)
te["pred"] = np.clip(lgbm.predict(te[FEATS]), 0, None)
lgb_daily = te.groupby("date")["pred"].sum().reindex(test["date"]).fillna(0).values

# assemble long format for Tableau (date, model, value, actual)
rows = []
for i, d in enumerate(test["date"].values):
    actual = test["y"].values[i]
    for model, pred in [("Actual", actual), ("Seasonal naive", base_pred[i]),
                        ("Prophet", prophet_pred[i]), ("SARIMAX", sarimax_pred[i]),
                        ("LightGBM", lgb_daily[i])]:
        rows.append({"date": pd.Timestamp(d).date(), "model": model,
                     "units": round(float(pred), 1), "actual": round(float(actual), 1)})
fva = pd.DataFrame(rows)

# also a small WMAPE-by-model summary table (handy as a Tableau text table)
def wmape(a, p): a, p = np.asarray(a, float), np.asarray(p, float); return np.sum(np.abs(a-p))/np.sum(np.abs(a))
wm = pd.DataFrame([
    {"model": "Seasonal naive", "wmape": round(wmape(test.y, base_pred), 3)},
    {"model": "Prophet", "wmape": round(wmape(test.y, prophet_pred), 3)},
    {"model": "SARIMAX", "wmape": round(wmape(test.y, sarimax_pred), 3)},
    {"model": "LightGBM", "wmape": round(wmape(test.y, lgb_daily), 3)},
]).sort_values("wmape")
wm["vs_baseline_pct"] = (
    (1 - wm["wmape"] / wm[wm.model == "Seasonal naive"].wmape.values[0]) * 100
).round(1)
save(fva, "forecast_vs_actual.csv")
save(wm, "forecast_wmape_summary.csv")


# ---------------------------------------------------------------------
# 3. ABC segmentation (all items)
# ---------------------------------------------------------------------
print("[3/4] abc_items.csv")
abc = q("""
    select
        a.item_nbr,
        i.family,
        i.perishable,
        a.total_sales,
        a.cum_pct,
        a.abc_class
    from main_marts.mart_item_abc a
    join main_marts.dim_item i using (item_nbr)
    order by a.total_sales desc
""")
abc["perishable_label"] = np.where(abc["perishable"] == 1, "Perishable", "Non-perishable")
abc["rank"] = range(1, len(abc) + 1)
save(abc, "abc_items.csv")


# ---------------------------------------------------------------------
# 4. Inventory policy + service-level trade-off curve
# ---------------------------------------------------------------------
print("[4/4] inventory_policy.csv + service_level_curve.csv")
# reuse the already-computed policy if present, else note absence
policy_src = "outputs/inventory_policy.csv"
err_src = "outputs/forecast_error_by_item.csv"
if os.path.exists(policy_src):
    policy = pd.read_csv(policy_src, encoding="utf-8-sig")
    # enrich with family for slicing in Tableau
    fam = q("select item_nbr, family from main_marts.dim_item")
    policy = policy.merge(fam, on="item_nbr", how="left")
    save(policy, "inventory_policy.csv")
else:
    print("     (outputs/inventory_policy.csv missing — run notebook 03 first)")

# service-level trade-off curve (illustrative, on a representative class-A item)
if os.path.exists(err_src):
    err = pd.read_csv(err_src, encoding="utf-8-sig")
    err = err.merge(q("select item_nbr, abc_class from main_marts.mart_item_abc"),
                    on="item_nbr", how="left")
    a_item = err[err.abc_class == "A"].sort_values("avg_demand", ascending=False).iloc[0]
    z = {0.90:1.2816, 0.95:1.6449, 0.98:2.0537, 0.99:2.3263}
    lead, unit_hold, price = 3, 0.5, 3.0
    curve_rows = []
    for sl in (0.90, 0.95, 0.98, 0.99):
        ss = z[sl] * a_item.sigma_error * np.sqrt(lead)
        holding = ss * unit_hold
        lost = (1 - sl) * a_item.avg_demand * price * lead
        curve_rows.append({"service_level": sl, "safety_stock": round(ss, 1),
                           "holding_cost": round(holding, 2),
                           "expected_lost_sales": round(lost, 2),
                           "total_cost": round(holding + lost, 2)})
    save(pd.DataFrame(curve_rows), "service_level_curve.csv")
else:
    print("     (outputs/forecast_error_by_item.csv missing — run notebook 02 first)")

print("\nDone. Extracts in", OUT)
