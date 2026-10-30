-- Calls and emails logged against leads. "Qualifying" = counts as a real first follow-up (LF-002).
select
    activity_id,
    lead_id,
    performed_by_owner_id,
    activity_type,
    activity_outcome,
    is_automated,
    coalesce((activity_details ->> 'qualifying')::boolean, false) as is_qualifying,
    occurred_at,
    recorded_at
from {{ source('leadflow', 'followup_activities') }}
