-- Actions people took on review cases (the audit trail of the review workflow).
select
    review_action_id,
    review_case_id,
    action_type,
    performed_at,
    performed_by
from {{ source('leadflow', 'review_actions') }}
