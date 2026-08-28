-- Oil dimension. Grain: one row per date.
-- Adds the daily change (useful as a feature: the change matters, not just the level).
with oil as (
    select date, oil_price
    from {{ ref('stg_oil') }}
)

select
    date,
    oil_price,
    oil_price - lag(oil_price) over (order by date) as oil_price_change,
    -- 7d moving average of oil (smooths noise for the macro effect)
    avg(oil_price) over (
        order by date rows between 6 preceding and current row
    ) as oil_price_ma7
from oil
