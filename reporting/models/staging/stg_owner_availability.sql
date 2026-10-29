-- Periods when a salesperson could (or could not) receive new leads. effective_to null = still running.
select
    eligibility_id,
    owner_id,
    country_code,
    is_eligible,
    effective_from,
    effective_to,
    change_reason
from {{ source('leadflow', 'owner_eligibility_history') }}
