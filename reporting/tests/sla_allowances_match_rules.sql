-- The working-time function used by every report agrees with the engine: each SLA's
-- original deadline is 8 working hours after it started, and its original response
-- target is 60 / 240 / 480 working minutes for P1 / P2 / P3. Returns the SLAs that disagree.
select s.sla_id, s.initial_priority,
       working_minutes(s.sla_started_at, s.original_deadline_at)        as sla_minutes,
       working_minutes(s.sla_started_at, s.original_response_target_at) as target_minutes
from {{ ref('stg_sla') }} as s
join {{ ref('priority_levels') }} as p on p.priority = s.initial_priority
where working_minutes(s.sla_started_at, s.original_deadline_at) <> p.sla_working_minutes
   or working_minutes(s.sla_started_at, s.original_response_target_at) <> p.response_target_working_minutes
