-- Salespeople and the Sales Manager, with the country they sell in.
with home_country as (
    select owner_id, min(country_code) as country_code
    from {{ source('leadflow', 'owner_eligibility_history') }}
    group by owner_id
)
select
    o.owner_id,
    o.staff_code,
    o.display_name,
    o.owner_role,
    o.manager_id,
    o.crm_owner_id,
    h.country_code
from {{ source('leadflow', 'owners') }} as o
left join home_country as h on h.owner_id = o.owner_id
