-- ================================================================
-- Central fact table of the star schema.
-- Grain: store-item-day (one row per recorded sale).
-- Joins sales with the dimensions (date, store, item, oil) to produce a table
-- ready for EDA and for exporting to Python (feature engineering).
-- ================================================================

with sales as (
    select * from {{ ref('stg_sales') }}
),

d_date as (
    select * from {{ ref('dim_date') }}
),

d_item as (
    select item_nbr, family, class, perishable
    from {{ ref('dim_item') }}
),

d_store as (
    select store_nbr, city, state, store_type, store_cluster
    from {{ ref('dim_store') }}
),

d_oil as (
    select date, oil_price, oil_price_change, oil_price_ma7
    from {{ ref('dim_oil') }}
)

select
    -- Keys
    s.id,
    s.date,
    s.store_nbr,
    s.item_nbr,

    -- Measures
    s.unit_sales,               -- real value (can be negative = return)
    s.unit_sales_clipped,       -- non-negative version (for demand modeling)
    s.is_return,
    s.onpromotion,

    -- Item attributes
    i.family,
    i.class,
    i.perishable,

    -- Store attributes
    st.city,
    st.state,
    st.store_type,
    st.store_cluster,

    -- Calendar attributes (from dim_date)
    dd.dow,
    dd.day_of_month,
    dd.month,
    dd.year,
    dd.is_payday,
    dd.is_weekend,
    dd.is_holiday,
    dd.days_to_nearest_holiday,

    -- Macro (oil)
    o.oil_price,
    o.oil_price_change,
    o.oil_price_ma7

from sales s
left join d_date  dd on s.date = dd.date
left join d_item  i  on s.item_nbr = i.item_nbr
left join d_store st on s.store_nbr = st.store_nbr
left join d_oil   o  on s.date = o.date
