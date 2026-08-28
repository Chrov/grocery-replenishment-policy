-- Store staging: typing and light normalization.
with source as (
    select * from {{ source('raw', 'stores') }}
)

select
    cast(store_nbr as integer) as store_nbr,
    trim(city)                 as city,
    trim(state)                as state,
    trim(type)                 as store_type,
    cast(cluster as integer)   as store_cluster
from source
