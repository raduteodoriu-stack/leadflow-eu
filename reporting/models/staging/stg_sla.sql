-- One SLA per assigned lead: the 8-working-hour promise and the priority response target.
select
    sla_id,
    lead_id,
    initial_priority,
    sla_started_at,
    original_deadline_at,
    current_deadline_at          as deadline_at,
    sla_status,
    qualifying_activity_id,
    qualifying_activity_at,
    breach_detected_at,
    response_target_priority,
    original_response_target_at,
    current_response_target_at   as response_target_at,
    response_target_status,
    last_evaluated_at
from {{ source('leadflow', 'sla_tracking') }}
