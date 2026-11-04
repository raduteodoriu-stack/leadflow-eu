-- One row per review case opened up to as_of, with readable references, its status and
-- its age in working minutes.
--   case_ref     short reference to quote (RC- + the first 8 characters of the case id)
--   enquiry_ref  the source system's id of the enquiry that opened the case, if any
--   lead_ref     the source id of the enquiry that created the lead, if the case concerns a lead
--   case_status  New (nobody has acted), In progress, Reopened or Resolved, at as_of,
--                from the review actions (the audit trail)
with actions as (
    select review_case_id,
           count(*)                                              as actions,
           count(*) filter (where action_type = 'case_reopened')  as times_reopened
    from {{ ref('stg_review_actions') }}
    where performed_at <= {{ as_of() }}
    group by review_case_id
)
select
    r.review_case_id,
    'RC-' || upper(left(replace(r.review_case_id::text, '-', ''), 8))  as case_ref,
    e.source_event_id                                                as enquiry_ref,
    o.lead_ref,
    r.reason_code,
    r.queue,
    r.action_owner,
    r.lead_id,
    r.enquiry_id,
    r.opened_at,
    {{ madrid_date('r.opened_at') }}                                 as opened_date,
    r.resolved_at,
    r.resolved_at is null or r.resolved_at > {{ as_of() }}          as is_open,
    case when r.resolved_at <= {{ as_of() }} then 'Resolved'
         when coalesce(a.times_reopened, 0) > 0 then 'Reopened'
         when coalesce(a.actions, 0) > 0 then 'In progress'
         else 'New' end                                              as case_status,
    coalesce(a.times_reopened, 0)                                    as times_reopened,
    case when r.resolved_at is null or r.resolved_at > {{ as_of() }}
         then working_minutes(r.opened_at, {{ as_of() }}) end       as open_age_working_minutes,
    case when r.resolved_at <= {{ as_of() }}
         then working_minutes(r.opened_at, r.resolved_at) end       as resolution_working_minutes
from {{ ref('stg_review_cases') }} as r
left join {{ ref('stg_enquiries') }} as e on e.enquiry_id = r.enquiry_id
left join {{ ref('int_lead_origin') }} as o on o.lead_id = r.lead_id
left join actions as a on a.review_case_id = r.review_case_id
where r.opened_at <= {{ as_of() }}
