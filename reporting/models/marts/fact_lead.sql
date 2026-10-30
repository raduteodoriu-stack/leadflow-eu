-- One row per lead created up to as_of: where it came from, how it was routed, and how
-- the response promise (SLA) and the priority response target went.
--
-- Statuses (met / breached / pending) are the engine's, as saved; the database must be
-- processed up to as_of. Ages and "at risk" are measured to as_of in working minutes.
with first_assignment as (
    select distinct on (lead_id)
        lead_id, owner_id, effective_from, assignment_method, is_automatic, decision_id
    from {{ ref('stg_assignments') }}
    where effective_from <= {{ as_of() }}
    order by lead_id, effective_from, assignment_id
),
current_assignment as (
    select lead_id, owner_id
    from {{ ref('stg_assignments') }}
    where effective_from <= {{ as_of() }}
      and (effective_to is null or effective_to > {{ as_of() }})
)
select
    l.lead_id,
    l.created_at,
    l.created_date,
    l.country_code,
    l.relationship_type,
    o.source_channel,
    o.creating_enquiry_id,
    o.priority_at_creation,
    o.priority_rule,
    o.has_incomplete_data,

    -- Routing
    f.owner_id                                                   as first_owner_id,
    c.owner_id                                                   as current_owner_id,
    f.effective_from                                             as first_assigned_at,
    f.assignment_method                                          as first_assignment_method,
    case when f.lead_id is null then 'waiting'
         when f.is_automatic and f.decision_id = o.creating_decision_id then 'automatic'
         else 'manual' end                                       as assignment_route,
    coalesce(f.is_automatic and f.decision_id = o.creating_decision_id, false) as is_auto_assigned,
    f.lead_id is null                                            as is_waiting_for_owner,
    case when f.lead_id is null
         then working_minutes(l.created_at, {{ as_of() }}) end   as waiting_working_minutes,
    working_minutes(l.created_at, f.effective_from)              as time_to_assignment_working_minutes,

    -- Response promise (SLA) and response target
    s.sla_id,
    s.initial_priority,
    s.sla_started_at,
    s.deadline_at                                                as sla_deadline_at,
    s.sla_status,
    s.response_target_priority,
    s.response_target_at,
    s.response_target_status,
    s.qualifying_activity_at                                     as first_followup_at,
    working_minutes(s.sla_started_at, s.qualifying_activity_at)  as time_to_first_followup_working_minutes,
    coalesce(s.sla_status = 'met' and s.response_target_status = 'missed', false) as kept_promise_missed_target,
    coalesce(s.sla_status = 'pending'
             and s.deadline_at > {{ as_of() }}
             and working_minutes({{ as_of() }}, s.deadline_at) <= {{ var('at_risk_working_minutes') }},
             false)                                              as is_at_risk,
    case when s.sla_status = 'pending' and s.deadline_at > {{ as_of() }}
         then working_minutes({{ as_of() }}, s.deadline_at) end  as working_minutes_to_deadline
from {{ ref('stg_leads') }} as l
left join {{ ref('int_lead_origin') }} as o on o.lead_id = l.lead_id
left join first_assignment as f on f.lead_id = l.lead_id
left join current_assignment as c on c.lead_id = l.lead_id
left join {{ ref('stg_sla') }} as s on s.lead_id = l.lead_id
where l.created_at <= {{ as_of() }}
