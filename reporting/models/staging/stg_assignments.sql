-- Who owned a lead, from when to when. effective_to null = current owner.
select
    assignment_id,
    lead_id,
    owner_id,
    decision_id,
    assignment_method,
    assignment_method in ('round_robin', 'same_company_owner') as is_automatic,
    effective_from,
    effective_to
from {{ source('leadflow', 'assignments') }}
