-- One row per intended CRM update (logical update), with where it stands now.
--   confirmed      the CRM shows it (succeeded, or simulated in Phase A)
--   superseded     replaced by a newer update before it got through
--   waiting_retry  failed with a temporary error; will be tried again
--   given_up       refused, or 5 attempts used: a CRM_WRITE_FAILED case is with RevOps
--   unconfirmed    no answer yet (in progress, or no reply): the next run checks the CRM first
with attempts as (
    select *,
           row_number() over (partition by logical_update_id order by attempt_number desc) as recency
    from {{ ref('stg_crm_writes') }}
    where started_at <= {{ as_of() }}
),
per_update as (
    select
        logical_update_id,
        min(target_record_id)                                                  as target_record_id,
        count(*)                                                               as attempts,
        min(started_at)                                                        as first_attempt_at,
        max(completed_at)                                                      as last_completed_at,
        bool_or(attempt_status in ('succeeded', 'simulated'))                  as is_confirmed,
        bool_or(attempt_status = 'simulated')                                  as is_simulated,
        bool_or(is_superseded)                                                 as is_superseded,
        max(attempt_status) filter (where recency = 1)                         as last_status,
        bool_or(coalesce(is_retryable, false)) filter (where recency = 1)      as last_retryable,
        max(next_retry_at) filter (where recency = 1)                          as next_retry_at,
        max(error_code) filter (where recency = 1)                             as last_error_code
    from attempts
    group by logical_update_id
)
select
    p.*,
    case when is_confirmed then 'confirmed'
         when is_superseded then 'superseded'
         when last_status = 'failed' and last_retryable then 'waiting_retry'
         when last_status = 'failed' then 'given_up'
         else 'unconfirmed' end                                                as update_state,
    l.lead_id
from per_update as p
left join {{ ref('stg_leads') }} as l
       on l.crm_contact_id = p.target_record_id or l.normalised_email = p.target_record_id
