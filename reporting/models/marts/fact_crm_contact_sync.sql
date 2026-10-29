-- One row per CRM contact LeadFlow manages: does the CRM show what LeadFlow decided?
-- Same comparison as reconciliation check C19: the intended values (view
-- crm_desired_contact_state) against the latest confirmed value of every property.
--
-- Current state only (the intended values are not kept historically), so as_of does not apply.
with confirmed as (
    select distinct on (w.target_record_id, p.key)
        w.target_record_id, p.key, p.value
    from {{ ref('stg_crm_writes') }} as w
    cross join lateral jsonb_each_text(w.properties) as p
    where w.attempt_status in ('succeeded', 'simulated')
    order by w.target_record_id, p.key, w.completed_at desc, w.logical_update_id desc
),
confirmed_state as (
    select target_record_id,
           coalesce(jsonb_object_agg(key, value) filter (where value <> ''), '{}'::jsonb) as properties
    from confirmed
    group by target_record_id
)
select
    d.target_record_id,
    l.lead_id,
    coalesce(c.properties, '{}'::jsonb) = d.properties   as is_in_sync,
    c.target_record_id is not null                        as has_confirmed_update
from {{ source('leadflow', 'crm_desired_contact_state') }} as d
left join confirmed_state as c on c.target_record_id = d.target_record_id
left join {{ ref('stg_leads') }} as l on l.normalised_email = d.normalised_email
