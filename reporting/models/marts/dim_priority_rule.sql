select priority_rule, reason_code, priority, rule_label
from {{ ref('priority_rules') }}
