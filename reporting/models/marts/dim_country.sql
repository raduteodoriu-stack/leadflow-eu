-- Served markets plus every other country seen in the data, and 'unknown'.
with seen as (
    select distinct country_code from {{ ref('stg_leads') }}
)
select country_code, country_name, is_served, sort_order
from {{ ref('served_markets') }}
union all
select s.country_code,
       case when s.country_code = 'unknown' then 'Unknown' else s.country_code end,
       false,
       case when s.country_code = 'unknown' then 99 else 50 end
from seen as s
where s.country_code not in (select country_code from {{ ref('served_markets') }})
