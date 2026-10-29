-- Everything waiting for a person, with the queue and who must act.
select
    review_case_id,
    ingestion_event_id                   as enquiry_id,
    lead_id,
    decision_id,
    reason_code,
    case_details ->> 'queue'             as queue,
    case_details ->> 'action_owner'      as action_owner,
    review_status,
    opened_at,
    resolved_at
from {{ source('leadflow', 'review_cases') }}
