-- Salespeople and the Sales Manager. user_principal_name is the sign-in used by
-- Power BI row-level security (LF-012): a salesperson sees only their own leads.
-- Synthetic addresses only (*.example).
select
    o.owner_id,
    o.staff_code,
    o.display_name,
    o.owner_role,
    o.country_code,
    m.staff_code                                          as manager_staff_code,
    lower(o.staff_code) || '@mop-cloud.example'           as user_principal_name,
    coalesce(a.is_eligible, false)                        as is_available_at_as_of
from {{ ref('stg_owners') }} as o
left join {{ ref('stg_owners') }} as m on m.owner_id = o.manager_id
left join {{ ref('stg_owner_availability') }} as a
       on a.owner_id = o.owner_id
      and a.effective_from <= {{ as_of() }}
      and (a.effective_to is null or a.effective_to > {{ as_of() }})
