-- One row per call or email logged up to as_of. "Logged late" = a qualifying follow-up made
-- on or before the SLA deadline but logged after it (the engine also flags these as
-- LATE_LOGGED_FOLLOWUP review cases).
select
    a.activity_id,
    a.lead_id,
    a.performed_by_owner_id                                          as owner_id,
    a.activity_type,
    a.activity_outcome,
    a.is_automated,
    a.is_qualifying,
    a.occurred_at,
    {{ madrid_date('a.occurred_at') }}                               as occurred_date,
    a.recorded_at,
    coalesce(a.is_qualifying and a.occurred_at <= s.deadline_at and a.recorded_at > s.deadline_at,
             false)                                                  as is_logged_late
from {{ ref('stg_followups') }} as a
left join {{ ref('stg_sla') }} as s on s.lead_id = a.lead_id
where a.recorded_at <= {{ as_of() }}
