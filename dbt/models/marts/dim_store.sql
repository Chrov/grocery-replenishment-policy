-- Store dimension. Grain: one row per store_nbr.
select
    store_nbr,
    city,
    state,
    store_type,
    store_cluster
from {{ ref('stg_stores') }}
