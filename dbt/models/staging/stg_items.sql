-- Item staging: typing. `perishable` is kept as 0/1 and as a boolean.
with source as (
    select * from {{ source('raw', 'items') }}
)

select
    cast(item_nbr as integer)          as item_nbr,
    trim(family)                       as family,
    cast(class as integer)             as class,
    cast(perishable as integer)        as perishable,          -- 0/1 (metric compat.)
    case when cast(perishable as integer) = 1 then true else false end
                                       as is_perishable
from source
