-- Item dimension. Grain: one row per item_nbr.
-- perishable is exposed in both forms for downstream convenience.
select
    item_nbr,
    family,
    class,
    perishable,
    is_perishable
from {{ ref('stg_items') }}
