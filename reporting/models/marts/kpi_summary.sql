-- One row per KPI value: the KPI, a breakdown (total, week, country, ...) and a member of it.
-- value = numerator / denominator for ratios, otherwise the numerator.
-- Every number on the dashboard comes from the facts the same way; this table is what the
-- tests compare with the LF-005 answer key, and what an export or a quick check reads.
with leads as (select * from {{ ref('fact_lead') }}),
     enquiries as (select * from {{ ref('fact_enquiry') }}),
     cases as (select * from {{ ref('fact_review_case') }}),
     owners as (select owner_id, staff_code from {{ ref('dim_owner') }}),
     assigned as (select * from leads where sla_id is not null),
     dates as (select date_day, iso_week from {{ ref('dim_date') }}),

values_ as (
    -- 1 Enquiries received
    select 1 as kpi_id, 'total' as breakdown, 'all' as member, count(*)::numeric as numerator, null::numeric as denominator
    from enquiries
    union all
    select 1, 'week', d.iso_week, count(*), null
    from enquiries e join dates d on d.date_day = e.received_date group by d.iso_week

    -- 2 New leads
    union all
    select 2, 'total', 'all', count(*), null from leads
    union all
    select 2, 'week', d.iso_week, count(*), null
    from leads l join dates d on d.date_day = l.created_date group by d.iso_week

    -- 3 Leads by country, 4 by source channel
    union all
    select 3, 'country', country_code, count(*), null from leads group by country_code
    union all
    select 4, 'channel', source_channel, count(*), null from leads group by source_channel

    -- 5 Rejected enquiries %
    union all
    select 5, 'total', 'all', count(*) filter (where is_rejected), count(*) from enquiries

    -- 7 Incomplete data %
    union all
    select 7, 'total', 'all', count(*) filter (where has_incomplete_data), count(*) from leads

    -- 9 Auto-assignment rate
    union all
    select 9, 'total', 'all', count(*) filter (where is_auto_assigned), count(*) from leads

    -- 10 Leads waiting for an owner, and the longest wait
    union all
    select 10, 'total', 'all', count(*) filter (where is_waiting_for_owner), null from leads
    union all
    select 10, 'longest_wait_working_minutes', 'all', coalesce(max(waiting_working_minutes), 0), null from leads

    -- 12 Leads per salesperson (first owner)
    union all
    select 12, 'owner', o.staff_code, count(*), null
    from leads l join owners o on o.owner_id = l.first_owner_id group by o.staff_code

    -- 16 Urgency mix of assigned leads (priority when assigned)
    union all
    select 16, 'priority', initial_priority, count(*), (select count(*) from assigned)
    from assigned group by initial_priority

    -- 17 Why leads were urgent (priority rule when created)
    union all
    select 17, 'priority_rule', priority_rule::text, count(*), null
    from leads where priority_rule is not null group by priority_rule

    -- 20 SLA attainment: met / (met + breached); open ones excluded
    union all
    select 20, 'total', 'all', count(*) filter (where sla_status = 'met'),
           count(*) filter (where sla_status in ('met', 'breached'))
    from assigned
    union all
    select 20, 'priority', initial_priority, count(*) filter (where sla_status = 'met'),
           count(*) filter (where sla_status in ('met', 'breached'))
    from assigned group by initial_priority
    union all
    select 20, 'country', country_code, count(*) filter (where sla_status = 'met'),
           count(*) filter (where sla_status in ('met', 'breached'))
    from assigned group by country_code

    -- 21 SLA breaches, 22 at-risk leads
    union all
    select 21, 'total', 'all', count(*) filter (where sla_status = 'breached'), null from assigned
    union all
    select 22, 'total', 'all', count(*) filter (where is_at_risk), null from assigned

    -- 23 Response-target hit rate: met / (met + missed)
    union all
    select 23, 'total', 'all', count(*) filter (where response_target_status = 'met'),
           count(*) filter (where response_target_status in ('met', 'missed'))
    from assigned

    -- 24 Promise kept, target missed
    union all
    select 24, 'total', 'all', count(*) filter (where kept_promise_missed_target), null from assigned

    -- 25 Median working minutes to the first qualifying follow-up, by priority when assigned
    union all
    select 25, 'priority', initial_priority,
           percentile_cont(0.5) within group (order by time_to_first_followup_working_minutes)::numeric, null
    from assigned
    where first_followup_at <= {{ as_of() }}
    group by initial_priority

    -- 26 Late-logged follow-ups (flagged by the engine)
    union all
    select 26, 'total', 'all', count(*), null from cases where reason_code = 'LATE_LOGGED_FOLLOWUP'

    -- 28 Review backlog: open cases, by who must act and by reason
    union all
    select 28, 'total', 'all', count(*), null from cases where is_open
    union all
    select 28, 'action_owner', action_owner, count(*), null from cases where is_open group by action_owner
    union all
    select 28, 'reason', reason_code, count(*), null from cases where is_open group by reason_code

    -- 29 Backlog over time: open cases at the end of each working day
    union all
    select 29, 'day', date_day::text, sum(open_cases), null
    from {{ ref('fact_daily_backlog') }} group by date_day

    -- 30 Absence alerts
    union all
    select 30, 'total', 'all', count(*), null from cases where reason_code = 'OWNER_UNAVAILABLE_PENDING'

    -- 31 CRM in sync
    union all
    select 31, 'total', 'all', count(*) filter (where is_in_sync), count(*) from {{ ref('fact_crm_contact_sync') }}

    -- 32 CRM updates waiting to retry, given up, or not yet confirmed
    union all
    select 32, 'total', 'all', count(*) filter (where update_state in ('waiting_retry', 'given_up', 'unconfirmed')), null
    from {{ ref('fact_crm_update') }}
    union all
    select 32, 'state', update_state, count(*), null
    from {{ ref('fact_crm_update') }} where update_state in ('waiting_retry', 'given_up', 'unconfirmed')
    group by update_state

    -- 33 Reconciliation status: checks balanced / checks run, latest run
    union all
    select 33, 'latest_run', to_char(run_at at time zone 'Europe/Madrid', 'YYYY-MM-DD HH24:MI'),
           check_count - failed_checks, check_count
    from {{ ref('fact_reconciliation_run') }} where is_latest
)
select
    v.kpi_id,
    k.kpi_name,
    k.section,
    k.tier,
    k.unit,
    v.breakdown,
    v.member,
    v.numerator,
    v.denominator,
    case when v.denominator is null then v.numerator
         when v.denominator = 0 then null
         else round(v.numerator / v.denominator, 4) end      as value,
    {{ as_of() }}                                          as as_of
from values_ as v
join {{ ref('kpi_catalog') }} as k on k.kpi_id = v.kpi_id
