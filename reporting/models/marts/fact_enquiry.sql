-- One row per stored inbound enquiry received up to as_of (repeats are never stored).
select
    e.enquiry_id,
    e.source_event_id,
    e.received_at,
    e.received_date,
    e.source_channel,
    e.event_type,
    e.processing_status,
    d.decision_outcome,
    d.priority,
    e.lead_id,
    o.lead_id is not null                       as created_lead,
    e.processing_status = 'rejected'            as is_rejected
from {{ ref('stg_enquiries') }} as e
left join {{ ref('stg_decisions') }} as d on d.enquiry_id = e.enquiry_id
left join {{ ref('int_lead_origin') }} as o on o.creating_enquiry_id = e.enquiry_id
where e.received_at <= {{ as_of() }}
