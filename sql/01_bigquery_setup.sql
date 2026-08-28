-- =====================================================================
-- Demand Forecasting & Inventory Optimization — Corporación Favorita
-- BigQuery analysis queries for the real-data path.
-- =====================================================================
-- Replace `your_project.favorita` with your BigQuery project.dataset.
-- These queries are written to run on BigQuery Standard SQL.

-- ---------------------------------------------------------------------
-- 1. LOAD (reference)
-- ---------------------------------------------------------------------
-- Upload the CSVs to a GCS bucket and load them with `bq load` or the console.
-- Example (bash) for the sales table, partitioned by date:
--
--   bq load \
--     --source_format=CSV \
--     --skip_leading_rows=1 \
--     --time_partitioning_field=date \
--     --clustering_fields=store_nbr,item_nbr \
--     your_project:favorita.raw_train \
--     gs://your-bucket/train.csv \
--     id:INTEGER,date:DATE,store_nbr:INTEGER,item_nbr:INTEGER,unit_sales:FLOAT,onpromotion:BOOLEAN
--
-- Repeat (without partitioning) for stores, items, transactions, oil, holidays_events.
-- Partitioning by `date` + clustering by store/item reduces cost and latency:
-- a query with a date filter only scans the necessary partitions.

-- ---------------------------------------------------------------------
-- 2. LOAD VERIFICATION
-- ---------------------------------------------------------------------
SELECT
  COUNT(*)            AS rows,
  MIN(date)           AS min_date,
  MAX(date)           AS max_date,
  COUNT(DISTINCT store_nbr) AS stores,
  COUNT(DISTINCT item_nbr)  AS items,
  COUNTIF(unit_sales < 0)   AS negative_sales  -- returns: decide how to treat them
FROM `your_project.favorita.raw_train`;

-- ---------------------------------------------------------------------
-- 3. SEASONALITY BY DAY OF WEEK
-- ---------------------------------------------------------------------
SELECT
  FORMAT_DATE('%A', date) AS day_of_week,
  EXTRACT(DAYOFWEEK FROM date) AS dow,
  AVG(unit_sales) AS avg_sales,
  SUM(unit_sales) AS total_sales
FROM `your_project.favorita.raw_train`
WHERE unit_sales > 0
GROUP BY day_of_week, dow
ORDER BY dow;

-- ---------------------------------------------------------------------
-- 4. PAYDAY EFFECT (pay days: 15th and month-end)
--    Hypothesis: sales rise around the 15th and the last day of the month.
-- ---------------------------------------------------------------------
SELECT
  EXTRACT(DAY FROM date) AS day_of_month,
  AVG(unit_sales) AS avg_sales
FROM `your_project.favorita.raw_train`
WHERE unit_sales > 0
GROUP BY day_of_month
ORDER BY day_of_month;
-- When plotting, look for spikes near the 15th and the 30th/31st. If they show up,
-- it's a strong calendar feature and a signal of domain understanding.

-- ---------------------------------------------------------------------
-- 5. PROMO LIFT BY FAMILY (how much the promotion lifts)
-- ---------------------------------------------------------------------
SELECT
  it.family,
  AVG(CASE WHEN t.onpromotion THEN t.unit_sales END) AS sales_with_promo,
  AVG(CASE WHEN NOT t.onpromotion THEN t.unit_sales END) AS sales_without_promo,
  SAFE_DIVIDE(
    AVG(CASE WHEN t.onpromotion THEN t.unit_sales END),
    AVG(CASE WHEN NOT t.onpromotion THEN t.unit_sales END)
  ) AS lift_ratio
FROM `your_project.favorita.raw_train` t
JOIN `your_project.favorita.raw_items` it USING (item_nbr)
WHERE t.unit_sales > 0
GROUP BY it.family
ORDER BY lift_ratio DESC;

-- ---------------------------------------------------------------------
-- 6. ABC ANALYSIS (item contribution to total sales)
--    A = items accumulating up to 80% of sales
--    B = up to 95%, C = the rest
-- ---------------------------------------------------------------------
WITH sales_per_item AS (
  SELECT item_nbr, SUM(unit_sales) AS total_sales
  FROM `your_project.favorita.raw_train`
  WHERE unit_sales > 0
  GROUP BY item_nbr
),
cumulative AS (
  SELECT
    item_nbr,
    total_sales,
    SUM(total_sales) OVER (ORDER BY total_sales DESC)
      / SUM(total_sales) OVER () AS cum_pct
  FROM sales_per_item
)
SELECT
  CASE
    WHEN cum_pct <= 0.80 THEN 'A'
    WHEN cum_pct <= 0.95 THEN 'B'
    ELSE 'C'
  END AS abc_class,
  COUNT(*) AS n_items,
  SUM(total_sales) AS class_total_sales
FROM cumulative
GROUP BY abc_class
ORDER BY abc_class;

-- ---------------------------------------------------------------------
-- 7. EARTHQUAKE WINDOW (April 16, 2016)
--    Aggregate daily demand around the event.
-- ---------------------------------------------------------------------
SELECT
  date,
  SUM(unit_sales) AS total_sales_day
FROM `your_project.favorita.raw_train`
WHERE date BETWEEN DATE '2016-04-01' AND DATE '2016-05-15'
  AND unit_sales > 0
GROUP BY date
ORDER BY date;
-- Extension: break down by family to see what reacted (water, supplies).

-- ---------------------------------------------------------------------
-- 8. PERISHABLES VS NON-PERISHABLES
-- ---------------------------------------------------------------------
SELECT
  it.perishable,
  COUNT(DISTINCT it.item_nbr) AS n_items,
  AVG(t.unit_sales) AS avg_sales,
  STDDEV(t.unit_sales) AS volatility
FROM `your_project.favorita.raw_train` t
JOIN `your_project.favorita.raw_items` it USING (item_nbr)
WHERE t.unit_sales > 0
GROUP BY it.perishable;

-- ---------------------------------------------------------------------
-- 9. CORRELATION: AGGREGATE DEMAND vs OIL PRICE
--    (Ecuador is oil-dependent: a proxy for macro purchasing power)
-- ---------------------------------------------------------------------
WITH daily_demand AS (
  SELECT date, SUM(unit_sales) AS total_sales
  FROM `your_project.favorita.raw_train`
  WHERE unit_sales > 0
  GROUP BY date
)
SELECT
  CORR(d.total_sales, o.dcoilwtico) AS oil_demand_correlation
FROM daily_demand d
JOIN `your_project.favorita.raw_oil` o USING (date)
WHERE o.dcoilwtico IS NOT NULL;

-- ---------------------------------------------------------------------
-- 10. BASE MODELING TABLE (item-store-day grain with features joined)
--     Export the result to Python via pandas-gbq for the forecasting.
-- ---------------------------------------------------------------------
SELECT
  t.date,
  t.store_nbr,
  t.item_nbr,
  it.family,
  it.class,
  it.perishable,
  s.city,
  s.state,
  s.type   AS store_type,
  s.cluster AS store_cluster,
  GREATEST(t.unit_sales, 0) AS unit_sales,  -- clip negatives (returns)
  t.onpromotion,
  o.dcoilwtico AS oil_price,
  EXTRACT(DAYOFWEEK FROM t.date) AS dow,
  EXTRACT(DAY FROM t.date)       AS day_of_month,
  EXTRACT(MONTH FROM t.date)     AS month,
  -- payday flag (approximate pay day)
  CASE WHEN EXTRACT(DAY FROM t.date) IN (15, 30, 31)
       OR t.date = LAST_DAY(t.date) THEN 1 ELSE 0 END AS is_payday,
  -- holiday flag
  CASE WHEN h.date IS NOT NULL THEN 1 ELSE 0 END AS is_holiday
FROM `your_project.favorita.raw_train` t
JOIN `your_project.favorita.raw_items`  it USING (item_nbr)
JOIN `your_project.favorita.raw_stores` s  USING (store_nbr)
LEFT JOIN `your_project.favorita.raw_oil`  o USING (date)
LEFT JOIN (
  SELECT DISTINCT date FROM `your_project.favorita.raw_holidays_events`
  WHERE type != 'Work Day'   -- 'Work Day' are transferred holidays that are worked
) h USING (date)
-- For the MVP, filter to a manageable subset:
WHERE t.store_nbr IN (1, 2, 3, 44, 45)          -- example top stores
  AND it.family IN ('GROCERY I', 'PRODUCE', 'BEVERAGES')  -- includes perishables and not
  AND t.date >= DATE '2016-01-01';
