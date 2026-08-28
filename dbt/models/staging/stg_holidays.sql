-- Holidays/events staging. A day can have several rows (national + local +
-- event). For the calendar flag we just need "there was a holiday that day", so
-- we de-duplicate at the date level, excluding 'Work Day' entries (transferred
-- holidays that are actually worked) and 'transferred' ones.

with source as (
    select * from {{ source('raw', 'holidays_events') }}
),

typed as (
    select
        cast(date as date)                     as date,
        trim(type)                             as holiday_type,
        trim(locale)                           as locale,
        trim(description)                      as description,
        coalesce(try_cast(transferred as boolean), false) as transferred
    from source
),

effective as (
    -- An "effective" holiday is one people actually don't work
    select date, holiday_type, locale, description
    from typed
    where holiday_type <> 'Work Day'
      and transferred = false
)

select distinct
    date,
    true as is_holiday,
    -- keep the dominant type in case the EDA wants to distinguish Holiday vs Event
    first_value(holiday_type) over (partition by date order by locale) as holiday_type
from effective
