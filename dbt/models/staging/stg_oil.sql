-- Oil staging: the real file has gaps (NaN) on weekends and holidays.
-- We fill them with forward-fill (last known price), and for leading NaNs we
-- use backward-fill.
--
-- Portability note: `ignore nulls` in window functions works in DuckDB and in
-- BigQuery. If you migrate to another engine without support, see the self-join
-- variant commented in the README.

with source as (
    select
        cast(date as date)           as date,
        try_cast(dcoilwtico as double) as oil_price_raw
    from {{ source('raw', 'oil') }}
),

filled as (
    select
        date,
        oil_price_raw,
        -- forward-fill: last non-null price up to the date
        last_value(oil_price_raw ignore nulls) over (
            order by date
            rows between unbounded preceding and current row
        ) as oil_ffill
    from source
),

backfilled as (
    select
        date,
        -- if a NULL still remains at the start, take the first known value forward
        coalesce(
            oil_ffill,
            first_value(oil_price_raw ignore nulls) over (
                order by date
                rows between current row and unbounded following
            )
        ) as oil_price
    from filled
)

select
    date,
    oil_price
from backfilled
