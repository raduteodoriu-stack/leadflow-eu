select priority, priority_label, response_target_working_minutes, sla_working_minutes, sort_order
from {{ ref('priority_levels') }}
