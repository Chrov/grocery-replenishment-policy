-- Calendar dimension. Grain: one row per date in the sales range.
-- Includes the calendar features the models consume:
--   day of week, day of month, month, payday flag (EC pay day),
--   holiday flag and proximity to the nearest holiday.

with date_spine as (
    -- Date range covered by sales
    select distinct date
    from {{ ref('stg_sales') }}
),

holidays as (
    select date, is_holiday, holiday_type
    from {{ ref('stg_holidays') }}
),

base as (
    select
        d.date,
        extract(dayofweek from d.date)        as dow,          -- 0=Sunday in DuckDB
        extract(day       from d.date)        as day_of_month,
        extract(month     from d.date)        as month,
        extract(year      from d.date)        as year,
        extract(week      from d.date)        as week_of_year,

        -- Payday flag: approximate pay day (15th and month-end)
        case
            when extract(day from d.date) in (15, 30, 31)
              or d.date = last_day(d.date)
            then 1 else 0
        end                                   as is_payday,

        -- Weekend
        case when extract(dayofweek from d.date) in (0, 6) then 1 else 0 end
                                              as is_weekend,

        coalesce(h.is_holiday, false)         as is_holiday,
        h.holiday_type                        as holiday_type
    from date_spine d
    left join holidays h using (date)
),

-- Proximity to the nearest holiday (days to/from). Domain feature: sales tend to
-- move BEFORE a holiday, not just on the exact day.
holiday_dates as (
    select date from holidays where is_holiday
),

proximity as (
    select
        b.date,
        min(abs(date_diff('day', b.date, hd.date))) as days_to_nearest_holiday
    from base b
    cross join holiday_dates hd
    group by b.date
)

select
    b.*,
    coalesce(p.days_to_nearest_holiday, 999) as days_to_nearest_holiday
from base b
left join proximity p using (date)
