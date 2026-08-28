-- ABC classification mart per item (cumulative contribution to sales).
--   A = items accumulating up to 80% of sales
--   B = up to 95%,  C = the rest
-- Uses thresholds parameterized in dbt_project.yml (vars).
-- Serves as a direct input to the inventory policy (service level per class).

with item_sales as (
    select
        item_nbr,
        sum(unit_sales_clipped) as total_sales
    from {{ ref('fct_sales') }}
    group by item_nbr
),

ranked as (
    select
        item_nbr,
        total_sales,
        sum(total_sales) over (order by total_sales desc)
            / nullif(sum(total_sales) over (), 0) as cum_pct
    from item_sales
)

select
    item_nbr,
    total_sales,
    cum_pct,
    case
        when cum_pct <= {{ var('abc_a_threshold') }} then 'A'
        when cum_pct <= {{ var('abc_b_threshold') }} then 'B'
        else 'C'
    end as abc_class
from ranked
