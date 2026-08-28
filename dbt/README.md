# dbt Project — Favorita Demand Forecasting

Star schema (staging + marts) on the Corporación Favorita dataset. Runs
**locally on DuckDB** (zero cost, zero cloud setup). The SQL is nearly identical
to BigQuery; see *Migrate to BigQuery* below.

## Structure

```
dbt/
├── dbt_project.yml           Project config (materializations, vars)
├── profiles.yml              Local DuckDB connection (BigQuery profile commented)
├── macros/
│   └── load_raw_sources.sql  Registers the CSVs in data/raw as raw.* views
└── models/
    ├── staging/              Views: clean and type each source
    │   ├── _sources.yml       Declaration of the 6 raw tables
    │   ├── stg_sales.sql      Normalizes onpromotion, splits returns, clips
    │   ├── stg_stores.sql
    │   ├── stg_items.sql
    │   ├── stg_oil.sql        Forward-fill of oil gaps (window fn)
    │   └── stg_holidays.sql   De-duplicates, excludes Work Days
    └── marts/                Tables: the star schema
        ├── _marts.yml         Docs + tests (uniqueness, FKs, accepted values)
        ├── fct_sales.sql      FACTS: store-item-day grain, dims joined
        ├── dim_date.sql       Calendar: payday, holidays, proximity
        ├── dim_store.sql
        ├── dim_item.sql
        ├── dim_oil.sql        Level + daily change + 7d moving average
        └── mart_item_abc.sql  ABC classification by contribution to sales
```

## How to run it

From the `dbt/` folder:

```bash
# 0. (once) generate the synthetic data if it doesn't exist
python ../data/generate_synthetic_favorita.py --scale mvp

# 1. register the raw CSVs as raw.* views in DuckDB
dbt run-operation load_raw_sources --profiles-dir .

# 2. build staging + marts (the star schema)
dbt run --profiles-dir .

# 3. run the data-quality tests
dbt test --profiles-dir .

# 4. (optional) browsable documentation
dbt docs generate --profiles-dir . && dbt docs serve --profiles-dir .
```

The resulting database lives at `../data/favorita.duckdb`. The notebooks query it
directly with `duckdb.connect()`.

## The dimensional model

```
        dim_date ──┐
        dim_store ─┼──> fct_sales <── (basis for EDA and Python modeling)
        dim_item ──┤
        dim_oil ───┘

        mart_item_abc  (derived from fct_sales; input to the inventory policy)
```

`fct_sales` produces one row per sale (store-item-day grain) with all keys,
measures (`unit_sales`, `unit_sales_clipped`, `is_return`, `onpromotion`) and the
calendar/macro attributes already joined, ready to export to Python.

## Migrate to BigQuery (real Kaggle dataset)

1. Load the CSVs to GCS and then to BigQuery as `raw_*` tables (see
   `../sql/01_bigquery_setup.sql`, section 1, with partitioning by `date` and
   clustering by `store_nbr, item_nbr`).
2. In `profiles.yml`, replace the `favorita:` block with the commented BigQuery
   profile.
3. In `_sources.yml`, remove the `meta.external_location` (in BigQuery the raw
   tables already exist; the `load_raw_sources` macro isn't needed).
4. Minor function adjustments between DuckDB and BigQuery:
   - `extract(dayofweek from date)`: DuckDB returns 0=Sunday; BigQuery
     `EXTRACT(DAYOFWEEK ...)` returns 1=Sunday. Check `dim_date`.
   - `last_day(date)` exists in both.
   - `date_diff('day', a, b)` (DuckDB) → `DATE_DIFF(a, b, DAY)` (BigQuery).
   - `try_cast` (DuckDB) → `SAFE_CAST` (BigQuery).
   The rest of the SQL is portable.
```
