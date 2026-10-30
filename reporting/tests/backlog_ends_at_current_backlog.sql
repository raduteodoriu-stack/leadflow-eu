-- The last point of "backlog over time" equals today's backlog, when the last working
-- day's snapshot is taken at as_of itself. Returns a row if they differ.
with last_day as (
    select date_day, snapshot_at, sum(open_cases) as open_cases
    from {{ ref('fact_daily_backlog') }}
    group by date_day, snapshot_at
    order by date_day desc
    limit 1
)
select d.date_day, d.open_cases,
       (select count(*) from {{ ref('fact_review_case') }} where is_open) as open_now
from last_day as d
where d.snapshot_at = {{ as_of() }}
  and d.open_cases <> (select count(*) from {{ ref('fact_review_case') }} where is_open)
