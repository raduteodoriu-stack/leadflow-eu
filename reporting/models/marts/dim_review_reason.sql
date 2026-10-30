select reason_code, reason_label, action_owner, category
from {{ ref('review_reasons') }}
