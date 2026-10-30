-- Open review cases at the end of each working day (18:00 Madrid, or as_of if earlier),
-- by reason. A case opened after 18:00 first appears the next working day.
-- Rebuilt from timestamps (opened_at, resolved_at), so no daily snapshot job is needed.
with days as (
    select date_day,
           least(((date_day + time '18:00') at time zone 'Europe/Madrid'), {{ as_of() }}) as snapshot_at
    from {{ ref('dim_date') }}
    where is_working_day
      and date_day >= (select min(opened_date) from {{ ref('fact_review_case') }})
      and date_day <= {{ madrid_date(as_of()) }}
),
reasons as (
    select distinct reason_code, action_owner from {{ ref('fact_review_case') }}
)
select
    d.date_day,
    d.snapshot_at,
    r.reason_code,
    r.action_owner,
    count(c.review_case_id)                                     as open_cases,
    coalesce(sum(working_minutes(c.opened_at, d.snapshot_at)), 0) as total_open_age_working_minutes
from days as d
cross join reasons as r
left join {{ ref('fact_review_case') }} as c
       on c.reason_code = r.reason_code
      and c.action_owner is not distinct from r.action_owner
      and c.opened_at <= d.snapshot_at
      and (c.resolved_at is null or c.resolved_at > d.snapshot_at)
group by d.date_day, d.snapshot_at, r.reason_code, r.action_owner
