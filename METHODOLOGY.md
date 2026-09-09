> Reviewed 2026-09-08: legacy advanced-model metrics and derived stock policies are not validated fixed-origin results. See [DECISION_REVIEW.md](DECISION_REVIEW.md) and outputs/review_backtest.csv for the completed benchmark.

# Methodology

The [README](README.md) reports what the project found. This document covers how each piece was built, why each decision was made over the alternatives, and where the reasoning is weaker than the headline numbers suggest.

**Contents**

1. [The decision the project serves](#1-the-decision-the-project-serves)
2. [The data](#2-the-data)
3. [The warehouse layer (dbt)](#3-the-warehouse-layer-dbt)
4. [Exploratory analysis](#4-exploratory-analysis)
5. [Forecasting](#5-forecasting)
6. [Statistical traps worked around](#6-statistical-traps-worked-around)
7. [The inventory layer](#7-the-inventory-layer)
8. [The reporting layer](#8-the-reporting-layer)
9. [Reproducing the whole thing](#9-reproducing-the-whole-thing)
10. [Decisions worth revisiting](#10-decisions-worth-revisiting)

---

## 1. The decision the project serves

Everything downstream is shaped by one operational question: **how many units of each item should each store order today?**

A replenishment decision is not "predict tomorrow's sales". It is "choose a quantity that covers demand over the **lead time** — the days between placing the order and the stock arriving — with an acceptable probability of not running out." Three quantities are needed:

| Quantity | Where it comes from | Why it is needed |
|---|---|---|
| Expected demand over the lead time | The forecast | The bulk of the order |
| Uncertainty of that forecast (σ) | The forecast's **error**, measured out of sample | The buffer on top |
| Tolerance for stockouts | A business choice (service level) | Converts σ into units |

Accuracy is an input to σ, and σ sets the buffer. The chain is:

```
forecast  →  forecast error (σ)  →  safety stock  →  reorder point  →  cost of the chosen service level
```

Each arrow is a section below: §5 produces the forecast and measures σ, §7 turns σ into a policy and prices the service level.

The economic argument for accuracy follows from the safety-stock formula (§7.1): the buffer is **proportional** to σ. Halve the forecast error and you halve the buffer needed to deliver the same service. The buffer is capital, and for perishables it is also spoilage, so a lower sigma converts into money at an unchanged service level.

---

## 2. The data

### 2.1 Why the data is synthetic

The intended source is the Kaggle [Corporación Favorita Grocery Sales Forecasting](https://www.kaggle.com/c/favorita-grocery-sales-forecasting) competition: ~125M rows of item-store-day sales from an Ecuadorian retailer, with store metadata, item attributes, oil prices and holidays.

That data is gated: it needs a Kaggle account, acceptance of the competition rules, and a ~5 GB download, so a reader cannot run the pipeline without completing them.

The alternative was a generator ([`data/generate_synthetic_favorita.py`](data/generate_synthetic_favorita.py)) that emits the **same six tables, with the same column names and types**, so the entire pipeline downstream is source-agnostic. Swapping in the real CSVs changes the source and nothing else.

The trade is reproducibility at the cost of external validity. Every number in this repository describes the synthetic data; the method transfers, the results do not.

### 2.2 What the generator reproduces, and how

Each signal the analysis later looks for is injected on purpose, so the EDA tests whether the pipeline recovers a signal known to be present:

| Signal | Mechanism in the generator |
|---|---|
| Weekly seasonality | A day-of-week multiplier, higher on weekends |
| Annual seasonality | A December uplift |
| Payday cycle | A multiplier around the 15th and month-end |
| Promotional lift | `onpromotion` multiplies the Poisson rate by a family-specific factor (1.3× for BREAD/BAKERY up to 2.1× for BEVERAGES) |
| Oil correlation | A ±5% macro multiplier driven by the standardized oil price |
| Earthquake shock | Emergency-goods families get a 2.4× multiplier on 2016-04-16, decaying by 0.1 per day over two weeks |
| Perishable volatility | A larger lognormal noise term per series (σ 0.27 vs 0.165) |
| Intermittency | A per-item sell probability; days below it produce no row at all, so zeros are structural rather than imputed |
| Returns | ~0.5% of rows flipped negative |
| Dirty promo field | ~16% of `onpromotion` values set to NaN, as in the real file |
| Fractional units | Perishables occasionally sold by weight, producing float quantities |

Demand for an item-store-day is drawn from a Poisson distribution whose rate is the product of all applicable multipliers, with a lognormal noise term. Poisson is the right family here: demand is a non-negative integer count, and its variance grows with its mean, which is what retail demand does.

### 2.3 What it does not reproduce well

Two signals came out weaker than intended:

- **Oil–demand correlation: 0.22.** Mild by construction (a ±5% band). In the real data the relationship is plausibly larger and lagged; here it is a weak contemporaneous association.
- **Perishable volatility.** The noise term is genuinely larger for perishables, but the effect is small enough that a naive measurement reverses its sign. That is a full worked example in [§6.4](#64-the-perishable-volatility-trap).

### 2.4 Scale

The generator has two scales. Everything in the repository was built at `--scale mvp`:

| | Real dataset | `--scale mvp` |
|---|---|---|
| Rows | ~125,000,000 | 110,624 |
| Stores | 54 | 6 |
| Items | ~4,000 | 60 |
| Families | 33 | 8 |
| Days | ~1,680 | 593 (2015-01-01 → 2016-08-15) |

MVP scale keeps the full pipeline — build, test, three notebooks, four models — runnable end to end on a laptop. It is small enough that some results are thin: see [§10](#10-decisions-worth-revisiting).

---

## 3. The warehouse layer (dbt)

### 3.1 Why a star schema, and why dbt at all

The alternative was to load CSVs straight into pandas. It was rejected for three reasons:

1. **The cleaning decisions need to be visible and testable.** Choices like "a NaN promotion counts as no promotion" or "returns are excluded from demand but kept as a flag" are business logic. Buried in a notebook cell they are invisible; as a dbt model with a test attached they are reviewable.
2. **The same definitions must serve every consumer.** The ABC classification is used by the EDA, by the inventory policy and by the BI extracts. Defined once as a model, all three read the same numbers. Defined three times in three notebooks, they drift.
3. **A star schema is what the destination looks like.** Item-store-day facts with conformed date/store/item/oil dimensions is the shape a BI tool queries and an analyst joins against without help.

Materialization follows the layer: **staging as views** (cheap, just cleaning and typing) and **marts as tables** (queried repeatedly, worth materializing). This is set once in `dbt_project.yml` rather than per model.

### 3.2 Staging: one decision per source

Five staging models, each carrying the cleaning decisions for one source.

**`stg_sales`** — the important one, three decisions:
- `onpromotion` normalizes to boolean, and **NaN becomes `false`**. The conservative direction: an unknown promotion is treated as no promotion, so the model does not credit lift to days that may not have had any.
- Negative `unit_sales` are returns. They are kept as an `is_return` flag rather than deleted, because losing them would silently change row counts.
- `unit_sales_clipped = greatest(unit_sales, 0)` is the column used for demand modeling. Returns are an accounting event, not demand; feeding negatives to a demand model corrupts both the level and the variance.

**`stg_oil`** — the real oil file has gaps on weekends and holidays. Filled by **forward-fill** (`last_value(... ignore nulls)` over an unbounded preceding window), with a backward-fill for any leading nulls. Forward-fill is the correct direction for a price series: on a Saturday the last known price *is* the information available. Interpolation would invent a price that never traded, and a backward-fill would leak a future price into the past.

**`stg_holidays`** — a single date can appear several times (national + local + event). Since the calendar only needs "was this a holiday", rows are de-duplicated to one per date, excluding `Work Day` entries (transferred holidays that are actually worked) and rows flagged `transferred`. The distinction matters: a transferred holiday does not move demand on its nominal date.

**`stg_items`** and **`stg_stores`** — typing and trimming. `perishable` is exposed both as 0/1 (the NWRMSLE weighting needs the integer) and as a boolean.

### 3.3 Marts: the star

Six models.

**`fct_sales`** — the fact table, store-item-day grain, with all four dimensions pre-joined. Denormalizing at build time is deliberate: the notebooks pull feature panels repeatedly, and paying the join once at build beats paying it on every query.

**`dim_date`** — the calendar, and the only dimension with real logic in it:
- `is_payday` covers days 15, 30, 31 and `last_day(date)`, so February's month-end is caught.
- `days_to_nearest_holiday` exists because demand moves **before** a holiday, not only on it. It is computed with a cross join between every date and every holiday date, taking the minimum absolute difference. At MVP scale this is trivial; at real scale it would need rewriting as a range join or an as-of join.
- The date spine is `select distinct date from stg_sales`, so the calendar covers days that recorded at least one sale chain-wide. Any fully empty day would be absent — see [§10](#10-decisions-worth-revisiting).

**`dim_oil`** — carries the level, the daily change (`oil_price - lag(oil_price)`) and a 7-day moving average. The change is included because for a macro regressor the *movement* often carries more signal than the level.

**`dim_item`**, **`dim_store`** — thin pass-throughs. They exist for the star's shape and its foreign-key tests, not for transformation.

**`mart_item_abc`** — the ABC classification, as a model rather than notebook code. Items are ranked by total sales, a running share of the total is computed, and thresholds from `dbt_project.yml` vars (`0.80` / `0.95`) assign the class. Parameterizing the thresholds keeps the classification a business rule that changes in one place. One subtlety: the running total uses SQL's default window frame, which groups tied values together; with float sales volumes ties are effectively absent, but on integer volumes it would matter.

### 3.4 What the 21 tests actually guard

Each test protects a specific failure mode:

| Test | Failure it catches |
|---|---|
| `unique` + `not_null` on `fct_sales.id` | A fan-out from a bad join silently duplicating sales |
| `relationships` from `fct_sales` to `dim_store` / `dim_item` | Orphan facts — a sale for an item that is not in the catalog |
| `not_null` on `unit_sales_clipped` | The clipping logic failing open and letting nulls into the model input |
| `accepted_values [0,1]` on `perishable` | A type change breaking the NWRMSLE weighting |
| `unique` on each dimension key | A dimension losing its grain, which would fan out every fact join |
| `accepted_values ['A','B','C']` on `abc_class` | The threshold logic producing an unclassified item, which would drop out of the inventory policy |
| `unique` + `not_null` on `dim_date.date` | A duplicated calendar row multiplying sales on that day |

Every one of them guards a downstream consumer, not just the table it sits on.

### 3.5 Portability to BigQuery

The SQL is deliberately close to portable. Locally, a macro (`load_raw_sources`) registers the CSVs as DuckDB views so `source()` resolves; on BigQuery the raw tables already exist and the macro is unnecessary. The remaining differences are documented in [`dbt/README.md`](dbt/README.md#migrate-to-bigquery-real-kaggle-dataset): `EXTRACT(DAYOFWEEK)` indexes from 1 in BigQuery and 0 in DuckDB, `date_diff` argument order differs, and `try_cast` becomes `SAFE_CAST`.

---

## 4. Exploratory analysis

The EDA ([`notebooks/01_eda.ipynb`](notebooks/01_eda.ipynb)) is organized as seven questions, each with a hypothesis stated before the query and each ending in a decision about the model.

| # | Question | How it was measured | Result | Consequence |
|---|---|---|---|---|
| 1 | Is there weekly seasonality? | Mean daily units by day of week | Weekends +37% over weekdays | Period-7 seasonality is mandatory: SARIMAX `s=7`, Prophet `weekly_seasonality=True`, `dow` as a LightGBM feature |
| 2 | Does the pay cycle move demand? | Mean units on `is_payday` vs the rest | +13.7% | `is_payday` enters as a calendar feature |
| 3 | How much do promotions lift sales, and does it vary? | Mean units with vs without `onpromotion`, by family | 1.30× (BREAD/BAKERY) to 1.97× (BEVERAGES) | `onpromotion` enters **every** model as a regressor. Because the multiplier varies by family, a single global promo effect would over-forecast some families and under-forecast others |
| 4 | Where is sales value concentrated? | `mart_item_abc` | Class A = 24/60 items (40%) = 79% of sales | Service levels differentiated by class (§7.4) |
| 5 | Did the April 2016 earthquake move demand? | Mean daily units, two weeks before vs two weeks after 2016-04-16 | +16.2% | A real shock, not an outlier to discard: Prophet handles it via changepoints; in production it is an event flag |
| 6 | Does the oil price track demand? | Pearson correlation, aggregate daily units vs `oil_price` | 0.22 | `oil_price` and `oil_price_change` kept as regressors, with modest expectations |
| 7 | Do perishables behave differently? | Coefficient of variation, perishable vs not | Pooled: 0.93 vs 1.01. Within-series: 0.56 vs 0.53 | See [§6.4](#64-the-perishable-volatility-trap) — the two measurements disagree, and only one of them answers the question |

Question 5 required judgment rather than a query. A +16% two-week spike is exactly the shape of an outlier that a data-cleaning reflex would trim. It should not be trimmed: it is a genuine demand event with a known physical cause, and a model that has never seen a demand shock will be blindsided by the next one. The distinction between "anomalous and real" and "anomalous and spurious" cannot be made statistically — it needs the context.

---

## 5. Forecasting

### 5.1 Choosing the metric

Item-store-day retail demand is intermittent: many days record no sale at all. That single fact rules out the default metric.

**MAPE is unusable.** It divides by the actual value, so a day with zero sales contributes a division by zero, and a day with one unit contributes an enormous percentage. On intermittent series MAPE is dominated by the smallest actuals.

**WMAPE is the primary metric:**

```
WMAPE = Σ|y − ŷ| / Σ|y|
```

It is the total absolute error expressed as a share of total volume. Zeros contribute to the numerator without destroying the denominator, and it reads naturally to a business audience: *"we are off by 16% of the volume we move."*

**RMSE** is reported alongside as a complement, because it penalizes large misses quadratically. A model can win on WMAPE while occasionally missing badly, and those large misses are what cause stockouts.

**NWRMSLE** is the competition's official metric and is implemented for comparability:

```
NWRMSLE = sqrt( Σ wᵢ (ln(1+ŷᵢ) − ln(1+yᵢ))² / Σ wᵢ )
```

Two properties matter: the log transform makes it penalize *relative* rather than absolute error (missing 10 units on a 20-unit item is worse than on a 200-unit one), and the weights `wᵢ` are 1.25 for perishables — an explicit statement that being wrong about a perishable costs more.

### 5.2 Choosing the aggregation level

At item-store-day grain the series are mostly zeros, and classical time-series models (SARIMAX, Prophet) estimate poorly on them: seasonal terms fit noise, and the likelihood is dominated by the zeros. At family-store-day the series is smooth, seasonal and estimable.

The choice was not to pick one grain but to match the grain to the model:

- **Prophet and SARIMAX** run on the **family-store-day** aggregate (BEVERAGES, store 1), where the series is well behaved.
- **LightGBM** runs at **item-store-day** grain with a `tweedie` objective. Tweedie is designed for non-negative data with a point mass at zero — exactly intermittent demand — which lets the model work at the finer grain where the actual decision lives.

The cost of this choice is that the comparison between the two groups is not a clean experiment. That is discussed in [§6.2](#62-aggregation-and-error-cancellation).

### 5.3 The validation protocol

**Random k-fold cross-validation is never used, anywhere in this project.** On a time series it trains on data that comes after the data it tests on, so the model sees the future and the resulting metric does not survive deployment.

Two time-respecting protocols are used instead:

**Hold-out.** The last 15 days are cut off and never touched until final evaluation. Train: 578 days. Test: 15 days. The 15-day horizon is the competition's, and it matches the operational cycle: replenishment is planned for a fortnight, not a year.

**Walk-forward backtesting (rolling origin).** A single hold-out measures one fortnight, and a calm fortnight flatters every model. The backtest sweeps the cutoff backwards through the series:

```
for fold in 0..3:
    cutoff = len(series) − horizon × (folds − fold)
    train  = series[:cutoff]              # only the past
    test   = series[cutoff : cutoff+horizon]
    fit on train, predict test, score
```

Each fold refits the model from scratch on the data available at that cutoff. The **mean and standard deviation** across folds are both reported: the standard deviation measures how much the ranking depends on which period was tested.

### 5.4 The four models, and why each is there

Each model in the progression answers a specific question.

**1. Seasonal naive — the baseline.** Today's forecast equals the same weekday one week ago. It is close to how a good deal of replenishment operates, and it is hard to beat because it captures the strongest signal (weekly seasonality) for free. A model that cannot beat it has no business being deployed.

**2. Prophet.** Decomposes the series into trend, weekly and yearly seasonality, holidays and changepoints, with external regressors added. It is here for the changepoints — it can absorb a level shift like the earthquake without being permanently distorted — and for producing intervals natively. `changepoint_prior_scale=0.05` is Prophet's default and was left alone: raising it makes the trend chase noise.

**3. SARIMAX.** `order=(1,1,1)`, `seasonal_order=(1,0,1,7)`, with promo share, oil price and holiday flag as exogenous regressors. The differencing term `d=1` handles the trend; the seasonal terms at period 7 handle the weekly cycle. The **X** is the reason it is here: unlike a plain SARIMA, it can be told that a promotion is running, which is the difference between forecasting a promo week and being surprised by it.

**4. LightGBM.** Gradient boosting on tabular features at item grain, `objective="tweedie"` with `tweedie_variance_power=1.3`, 200 rounds, learning rate 0.05, 31 leaves. It is here because it is what actually scales: one model can serve thousands of series, whereas SARIMAX needs one fit per series.

### 5.5 Feature engineering and leakage control

Fifteen features: the calendar block (`dow`, `day_of_month`, `month`, `is_payday`, `is_holiday`, `days_to_nearest_holiday`), the macro block (`oil_price`, `oil_price_change`), item attributes (`perishable`, `onpromotion`) and the autoregressive block (`lag_7`, `lag_14`, `lag_28`, `roll_mean_7`, `roll_mean_28`).

The autoregressive block is where leakage happens if you are careless, so the rules are strict:

- Every lag and rolling statistic is computed **within** its own item series, via `groupby(item_nbr)`. Pooling across items would mix one item's history into another's features.
- Lags use `shift(lag)`; rolling means are computed on an already-shifted series (`g.shift(1).rolling(w)`). The shift-then-roll order matters: rolling first would include the current day in its own predictor, a look-ahead that is easy to miss in review.
- Rows without a full 28-day history are dropped rather than imputed.

Lags of 7, 14 and 28 are multiples of the weekly cycle, so each compares like weekday with like weekday.

The resulting feature importances serve as a sanity check: `roll_mean_28` dominates, then `onpromotion`, then `dow`. Recent level, promotion, weekday — the order a planner would give.

### 5.6 Results, and how to read them

| Model | Hold-out WMAPE | RMSE | vs baseline | Walk-forward (4 folds) |
|---|---|---|---|---|
| Seasonal naive | 0.449 | 44.71 | — | 0.407 ± 0.063 |
| Prophet | 0.274 | 27.66 | −39% | 0.262 ± 0.017 |
| SARIMAX | 0.243 | 25.94 | −46% | 0.258 ± 0.028 |
| **LightGBM** | **0.159** | **15.74** | **−65%** | *not run* |

In descending order of confidence:

1. **Every model beats the baseline, on both protocols.** This is the robust claim.
2. **Prophet and SARIMAX are indistinguishable.** On the hold-out SARIMAX wins (0.243 vs 0.274). Across four folds the order flips and the gap collapses to 0.258 vs 0.262 — far inside one standard deviation. The hold-out ranking was noise, which is what the backtest exists to catch.
3. **LightGBM's lead is large but under-validated.** 0.159 is a single fortnight and has not been through the fold sweep. The gap is large enough to be unlikely to be luck, but it is not confirmed.

The constraint behind that gap is specific: a correct LightGBM backtest has to **regenerate the lag and rolling features at every cutoff**. Reusing features computed once over the full series would leak future information into every earlier fold and produce a number that is both flattering and wrong. The `backtest_series` function handles refitting for series models; extending it to regenerate a feature panel per fold is the outstanding work.

### 5.7 Model selection

The lowest WMAPE does not automatically win. Four criteria were weighed:

| Criterion | LightGBM | Prophet / SARIMAX |
|---|---|---|
| Accuracy | Best on the hold-out | Roughly equal to each other, clearly behind |
| Robustness | Not yet established across folds | Established, low fold-to-fold variance |
| Cost at scale | One global model for thousands of series | One fit per series |
| Interpretability | Feature importances, no per-series story | A decomposition per series, and native prediction intervals |

The prediction-interval column has an operational consequence: safety stock needs σ, and a model that produces an interval gives it directly, whereas the tree ensemble requires estimating it from backtest residuals.

The conclusion is an architecture rather than a winner: **a global LightGBM for the long tail, where per-series modeling is uneconomic, and interpretable series models on high-value class-A SKUs**, where a planner will want to know why the number moved and where the interval feeds the buffer directly.

### 5.8 Exporting the forecast error

Notebook 02 ends by computing, for each item:

- `sigma_error` — the standard deviation of `y − ŷ` over the hold-out. This is the σ used throughout the inventory layer.
- `avg_demand` — mean daily demand, which sets the cycle-stock part of the reorder point.
- `perishable` — carried through for the policy rule.

Items with a single observation in the horizon yield an undefined standard deviation; those are filled with the **median** σ across items rather than dropped, a conservative choice that keeps them in the policy with a typical buffer instead of no buffer.

Output: [`outputs/forecast_error_by_item.csv`](outputs/forecast_error_by_item.csv), 13 items.

---

## 6. Statistical traps worked around

### 6.1 Zeros and the choice of metric

Covered in §5.1: on intermittent demand MAPE is not merely imprecise, it is dominated by the smallest actuals.

### 6.2 Aggregation and error cancellation

LightGBM forecasts each item separately, and its predictions are summed to a daily total before being scored against the same daily total the series models predicted directly.

This is a legitimate modeling strategy — bottom-up forecasting is standard — but it is not a controlled comparison. Independent per-item errors partly cancel when summed: some items are over-forecast, others under, and the aggregate is more accurate than any individual series. Part of LightGBM's −65% is the finer grain, not the algorithm.

Stated precisely: the *approach* of modeling at item grain and aggregating up beats the approach of modeling the aggregate directly, on this series. Attributing the whole gap to gradient boosting would credit the algorithm for what is partly the grain.

### 6.3 One hold-out is one sample

The hold-out ranking put SARIMAX ahead of Prophet by 11%. Four folds reversed it and shrank it to 1.5%, with fold-to-fold standard deviations (0.028 and 0.017) larger than the gap itself.

A single test-set number is a sample of size one from a distribution of possible outcomes. Reporting it without a spread invites a conclusion the data does not support.

### 6.4 The perishable volatility trap

This measurement produced a wrong conclusion twice before it produced the right one.

**The claim:** perishables are harder to forecast, so they need proportionally more buffer, and the 1.25× NWRMSLE weight is justified.

**The first measurement** pooled every row and compared coefficients of variation by group:

| | n rows | mean | std | CV |
|---|---|---|---|---|
| Non-perishable | 67,854 | 19.16 | 19.36 | **1.010** |
| Perishable | 42,770 | 12.46 | 11.62 | **0.933** |

Read directly, this says perishables are *less* variable — the opposite of the claim, and the opposite of what the generator injects.

**Why it is wrong.** A pooled CV mixes two different sources of variation: differences **between** items (some items are simply bigger sellers) and variation **within** an item over time (which is what forecast difficulty means). The item mix differs sharply between the groups:

| | items | mean of item means | std of item means | min | max |
|---|---|---|---|---|---|
| Non-perishable | 38 | 15.86 | 13.80 | 2.48 | 76.86 |
| Perishable | 22 | 10.59 | 7.85 | 3.23 | 27.54 |

Non-perishable families span 2.5 to 77 units/day; perishables only 3.2 to 28. That wider spread inflates the pooled non-perishable CV all by itself. The statistic is measuring catalog composition, not predictability.

**The measurement that answers the question** computes a CV for each item-store series over time, then compares the two distributions:

| | series | median CV | mean CV |
|---|---|---|---|
| Non-perishable | 228 | **0.530** | 0.526 |
| Perishable | 132 | **0.557** | 0.554 |

Perishables are more volatile by about 5%. The difference is small but consistent, and the sign matches what the generator injects.

Reproduce it from the committed raw files:

```python
import pandas as pd
tr = pd.read_csv("data/raw/train.csv")
it = pd.read_csv("data/raw/items.csv")
tr["y"] = tr["unit_sales"].clip(lower=0)
df = tr.merge(it[["item_nbr", "perishable"]], on="item_nbr")

# pooled — confounded by item mix
print(df.groupby("perishable")["y"].agg(cv=lambda s: s.std() / s.mean()))

# within series — what forecast difficulty actually means
g = df.groupby(["perishable", "item_nbr", "store_nbr"])["y"].agg(["mean", "std"]).reset_index()
g = g[g["mean"] > 0]
print((g["std"] / g["mean"]).groupby(g["perishable"]).median())
```

**The decision it leads to.** The 1.25× weight stays, but on stated grounds. The volatility gap is real and small, so it is not the main argument. The main argument is the **operational asymmetry**: an over-ordered non-perishable is next week's inventory, while an over-ordered perishable is waste. The two errors are not symmetric even when their variances are.

### 6.5 The linearity that looks like a result

"A 20% better forecast frees 20% of safety stock" reads like an empirical finding. It is not. Safety stock is `z · σ · √L`, which is linear in σ, so the relationship is an identity — true for any dataset, any model, any business.

What is empirical is the σ reduction itself. What is *not* established here is the conversion of the measured accuracy gain into a real buffer reduction, because that needs the baseline model's σ **per item**, and only LightGBM's per-item σ was computed. The figure in the README is therefore presented as a sensitivity ladder (−10/−20/−30%) rather than as a claimed saving.

---

## 7. The inventory layer

Implementations in [`src/forecasting_pipeline.py`](src/forecasting_pipeline.py), applied in [`notebooks/03_inventory.ipynb`](notebooks/03_inventory.ipynb).

### 7.1 Safety stock

```
safety_stock = z(service_level) × σ_error × √lead_time
```

The terms:

- **σ_error** is the standard deviation of the *forecast error*, not of demand. Buffering against demand variability double-counts whatever the model already predicts. If the model knows Saturdays are busy, Saturday variance is not uncertainty. Only the part the model fails to anticipate needs a buffer.
- **√lead_time** because errors over independent days accumulate as variances. Variance scales with L, so standard deviation scales with √L. Multiplying by L instead — a common mistake — over-buffers by a factor of √L.
- **z** is the normal quantile of the target service level: 90% → 1.282, 95% → 1.645, 98% → 2.054, 99% → 2.326. This assumes forecast errors are approximately normal, which is defensible at aggregate level and shakier for slow-moving items (see [§10](#10-decisions-worth-revisiting)).

Note the non-linearity in z: moving from 95% to 99% multiplies the buffer by 2.326/1.645 = 1.41. The last few points of service are the expensive ones, which §7.5 prices.

### 7.2 Reorder point

```
reorder_point = (avg_daily_demand × lead_time) + safety_stock
```

Two components: expected demand during the lead time (cycle stock), plus the buffer. When stock on hand crosses this level, the order is placed.

Lead time is fixed at 3 days throughout.

### 7.3 ABC classification

Computed in dbt (§3.3), not in the notebook, so the EDA, the policy and the BI extracts all read one definition. Items are ranked by total sales; A is the set accumulating to 80% of sales, B to 95%, C the remainder.

At MVP scale: A = 24 items (40% of the catalog, 79% of sales), B = 19 (32%, 16%), C = 17 (28%, 5%).

The 40/79 split is flatter than the textbook 20/80 because the catalog is only 60 items; on the real 4,000-item catalog the concentration would be sharper. The specific ratio is a property of this dataset, not of the method.

### 7.4 Differentiated service levels

```
A → 98%    B → 95%    C → 90%
perishable → +3 points, capped at 99%
```

The logic is capital allocation. Protecting a class-C item at 98% spends buffer on 5% of revenue; the same units spent on class A protect 79% of it. A uniform service level is not neutral: it over-protects the tail and under-protects the head.

The perishable bump encodes the asymmetry from §6.4: a stockout is a lost sale, an overstock is waste, and the second is worse for something with a three-day shelf life.

Applied to the 13 items with a σ estimate, the result is:

| Class | Items | Service level | Mean safety stock |
|---|---|---|---|
| A | 7 | 98% | 24.9 units |
| B | 4 | 95% | 11.9 units |
| C | 2 | 90% | 5.6 units |

All 13 are BEVERAGES, so `perishable = 0` throughout and the perishable rule never fires in the current output. It is implemented but exercised by no row in this data.

### 7.5 The service-level / cost curve

The curve prices the service level instead of assuming one. For a representative class-A item, at each candidate level:

- **Holding cost** = safety stock × $0.50 per unit per cycle. Rises with service level.
- **Expected lost sales** = (1 − service level) × avg demand × $3.00 × lead time. Falls with service level.
- **Total cost** = the sum. U-shaped.

| Service level | Safety stock | Holding | Lost sales | Total |
|---|---|---|---|---|
| 90% | 35.6 | $17.82 | $18.80 | $36.62 |
| **95%** | 45.7 | $22.87 | $9.40 | **$32.27** |
| 98% | 57.1 | $28.55 | $3.76 | $32.31 |
| 99% | 64.7 | $32.34 | $1.88 | $34.22 |

The minimum sits at 95%, but **95% and 98% differ by $0.04, or 0.1%**. Within the precision of the cost assumptions those two options are identical. Declaring 95% the optimum would be false precision. The output is a *band* of economically equivalent choices, and the decision inside that band belongs to grounds the model cannot see — shelf space, supplier order minimums, how visible a stockout is to the customer.

Three limitations of this curve:

1. The unit economics ($0.50 holding, $3.00 price) are assumed, not sourced. Real margin, holding and spoilage rates would calibrate it to the business; the flat bottom would likely survive that calibration.
2. Lost sales are approximated as linear in `(1 − service level)`. The textbook treatment uses the expected shortfall of the demand distribution, which is not linear.
3. It is evaluated on a four-point grid. The curve between those points is interpolation, not measurement.

### 7.6 The sensitivity ladder

Total safety stock across the 13 items is **233 units**. Because safety stock is linear in σ (§6.5), the effect of a better forecast is arithmetic:

| Forecast error reduction | Total safety stock | Units freed |
|---|---|---|
| — | 233 | — |
| 10% | 210 | 23 |
| 20% | 186 | 47 |
| 30% | 163 | 70 |

It is presented as a ladder rather than a single scenario because it is a property of the formula, not a measured saving.

---

## 8. The reporting layer

### 8.1 The extracts

[`dashboard/export_tableau_extracts.py`](dashboard/export_tableau_extracts.py) writes six flat, denormalized CSVs to `dashboard/data/`, one per intended view, with column names aimed at a general audience. They are flat by design: a BI tool should not have to reconstruct the star schema to draw one chart.

| File | Grain |
|---|---|
| `demand_daily.csv` | date × family × store |
| `forecast_vs_actual.csv` | date × model (long format) |
| `forecast_wmape_summary.csv` | one row per model |
| `abc_items.csv` | one row per item |
| `inventory_policy.csv` | one row per item |
| `service_level_curve.csv` | one row per service level |

### 8.2 The figures

[`reports/make_figures.py`](reports/make_figures.py) renders the five README charts **from those same extracts**, not from a live database. That keeps the charts reproducible by anyone who clones the repository, with no database build and no model run.

The script prints every headline number it computes as it runs, so the figures and the README text cannot drift apart.

Chart conventions: titles state the conclusion rather than naming the axes ("Weekends run +37% above weekdays", not "Sales by day of week"); the key finding is annotated on the chart rather than left to a caption; the palette is consistent across all five.

---

## 9. Reproducing the whole thing

```bash
pip install -r requirements.txt
python data/generate_synthetic_favorita.py --scale mvp
```

Generates the six raw CSVs in `data/raw/`.

```bash
cd dbt
dbt run-operation load_raw_sources --profiles-dir .   # register the CSVs as raw.* views
dbt run --profiles-dir .                              # build staging + marts
dbt test --profiles-dir .                             # 21 data-quality tests
cd ..
```

Produces `data/favorita.duckdb` with the star schema. `dbt docs generate && dbt docs serve` gives a browsable lineage graph.

Then the notebooks in order — [`01_eda`](notebooks/01_eda.ipynb) → [`02_forecasting`](notebooks/02_forecasting.ipynb) → [`03_inventory`](notebooks/03_inventory.ipynb). The order is a dependency: 02 writes `outputs/forecast_error_by_item.csv`, which 03 reads.

Optionally, refresh the BI extracts and the README figures:

```bash
python dashboard/export_tableau_extracts.py
python reports/make_figures.py
```

The figure script depends only on the committed CSVs, so it runs standalone without the database.

---

## 10. Decisions worth revisiting

Ordered by how much they would change the conclusions.

1. **Backtest LightGBM properly.** Regenerate the feature panel at each cutoff and run the fold sweep. Until then the −65% rests on one fortnight. This is the largest gap.

2. **Lift the MVP filter.** The forecast covers one family-store and the policy covers 13 items. `FAMILY` and `STORE` are constants at the top of notebook 02, so extending the scope does not require redesign. At full catalog scale the ABC concentration would sharpen and the per-item σ estimates would rest on more observations.

3. **Model lead time as a random variable.** It is fixed at 3 days and treated as certain. Real replenishment has variable lead time, which requires the fuller form `√(L·σ_d² + d²·σ_L²)`. Ignoring lead-time variance systematically under-buffers, and the effect grows with how unreliable the supplier is.

4. **Revisit the normality assumption behind z.** `z · σ` presumes approximately normal forecast errors. That is reasonable for aggregated fast movers and doubtful for slow movers, where the error distribution is skewed and discrete. For class-C intermittent items a distribution-free or bootstrapped quantile would be better calibrated.

5. **Calibrate the cost curve.** Real margin, holding and spoilage rates instead of $0.50 and $3.00, plus a proper expected-shortfall treatment of lost sales.

6. **Estimate σ from the backtest rather than the hold-out.** Currently σ comes from the 15-day hold-out, so it rests on at most 15 residuals per item. Fold residuals would give a more stable estimate, and σ propagates directly into every buffer.

7. **Housekeeping.** The `transactions` source is declared and loaded but never modeled — it is a store-traffic proxy that could be a useful regressor. `dim_date` builds its spine from dates present in sales, so a chain-wide zero-sales day would be missing from the calendar. `abc_classification()` in the pipeline duplicates logic that lives in `mart_item_abc`; the dbt model is the one in use, and the Python version should either be deleted or documented as the BigQuery-path equivalent.
