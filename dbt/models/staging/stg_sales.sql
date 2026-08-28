-- Sales staging: cleans and types the raw.train table.
--   - onpromotion: normalize to boolean (NaN -> false, conservative choice).
--   - unit_sales: keep the real value; split out the return flag.
--   - unit_sales_clipped: non-negative version for demand modeling.
-- Grain: item-store-day (one row per recorded sale).

with source as (
    select * from {{ source('raw', 'train') }}
),

cleaned as (
    select
        id,
        cast(date as date)                        as date,
        cast(store_nbr as integer)                as store_nbr,
        cast(item_nbr as integer)                 as item_nbr,
        cast(unit_sales as double)                as unit_sales,

        -- Explicit return flag (negative unit_sales)
        case when cast(unit_sales as double) < 0 then true else false end
                                                  as is_return,

        -- For demand modeling we use non-negative sales (clip returns)
        greatest(cast(unit_sales as double), 0)   as unit_sales_clipped,

        -- Normalize onpromotion: in DuckDB the CSV NaNs arrive as NULL or
        -- string; convert to boolean and treat the unknown as false.
        coalesce(
            try_cast(onpromotion as boolean),
            false
        )                                         as onpromotion
    from source
)

select * from cleaned
