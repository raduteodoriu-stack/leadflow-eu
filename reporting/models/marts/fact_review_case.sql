-- One row per review case opened up to as_of, with its age in working minutes.
select
    r.review_case_id,
    r.reason_code,
    r.queue,
    r.action_owner,
    r.lead_id,
    r.enquiry_id,
    r.opened_at,
    {{ madrid_date('r.opened_at') }}                                 as opened_date,
    r.resolved_at,
    r.resolved_at is null or r.resolved_at > {{ as_of() }}          as is_open,
    case when r.resolved_at is null or r.resolved_at > {{ as_of() }}
         then working_minutes(r.opened_at, {{ as_of() }}) end       as open_age_working_minutes,
    case when r.resolved_at <= {{ as_of() }}
         then working_minutes(r.opened_at, r.resolved_at) end       as resolution_working_minutes
from {{ ref('stg_review_cases') }} as r
where r.opened_at <= {{ as_of() }}
