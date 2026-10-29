-- The enquiry that created each lead, and what was decided for it at that moment.
-- A lead's first stored enquiry is the one that created it (tested: its time equals leads.created_at).
with first_enquiry as (
    select distinct on (lead_id)
        lead_id, enquiry_id, received_at, source_channel
    from {{ ref('stg_enquiries') }}
    where lead_id is not null
    order by lead_id, received_at, enquiry_id
)
select
    f.lead_id,
    f.enquiry_id                     as creating_enquiry_id,
    f.received_at                    as created_at,
    f.source_channel,
    d.decision_id                    as creating_decision_id,
    d.decision_outcome               as creating_outcome,
    d.priority                       as priority_at_creation,
    d.priority_rule,
    not (d.fit_data_complete and d.engagement_data_complete) as has_incomplete_data
from first_enquiry as f
left join {{ ref('stg_decisions') }} as d on d.enquiry_id = f.enquiry_id
