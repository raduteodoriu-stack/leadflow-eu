-- Nothing is lost or doubled between the operational tables and the facts.
-- Returns one row per fact whose row count differs from its source.
with checks as (
    select 'fact_enquiry' as fact,
           (select count(*) from {{ ref('fact_enquiry') }}) as in_fact,
           (select count(*) from {{ source('leadflow', 'ingestion_events') }} where received_at <= {{ as_of() }}) as in_source
    union all
    select 'fact_lead',
           (select count(*) from {{ ref('fact_lead') }}),
           (select count(*) from {{ source('leadflow', 'leads') }} where created_at <= {{ as_of() }})
    union all
    select 'fact_review_case',
           (select count(*) from {{ ref('fact_review_case') }}),
           (select count(*) from {{ source('leadflow', 'review_cases') }} where opened_at <= {{ as_of() }})
    union all
    select 'fact_followup',
           (select count(*) from {{ ref('fact_followup') }}),
           (select count(*) from {{ source('leadflow', 'followup_activities') }} where recorded_at <= {{ as_of() }})
    union all
    select 'fact_crm_update (attempts)',
           (select coalesce(sum(attempts), 0) from {{ ref('fact_crm_update') }}),
           (select count(*) from {{ source('leadflow', 'crm_write_log') }} where started_at <= {{ as_of() }})
    union all
    select 'fact_crm_contact_sync',
           (select count(*) from {{ ref('fact_crm_contact_sync') }}),
           (select count(*) from {{ source('leadflow', 'crm_desired_contact_state') }})
)
select * from checks where in_fact <> in_source
