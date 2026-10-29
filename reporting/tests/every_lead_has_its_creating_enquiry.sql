-- Each lead's first stored enquiry arrived exactly when the lead was created, and every
-- lead has one. This is what lets fact_lead take channel and priority from that enquiry.
select l.lead_id, l.created_at, o.created_at as first_enquiry_at
from {{ ref('stg_leads') }} as l
left join {{ ref('int_lead_origin') }} as o on o.lead_id = l.lead_id
where o.lead_id is null or o.created_at <> l.created_at or o.creating_decision_id is null
