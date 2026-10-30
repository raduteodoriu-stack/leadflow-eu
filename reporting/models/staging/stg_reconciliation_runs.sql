select
    run_id,
    run_at,
    database_name,
    source_name,
    rule_version,
    check_count,
    failed_checks,
    is_balanced,
    report_path
from {{ source('leadflow', 'reconciliation_runs') }}
