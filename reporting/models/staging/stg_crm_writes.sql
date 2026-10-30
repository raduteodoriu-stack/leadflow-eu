-- Every CRM update attempt. One logical update can take several attempts.
select
    write_attempt_id,
    logical_update_id,
    attempt_number,
    target_record_id,
    attempt_status,
    is_retryable,
    next_retry_at,
    error_code,
    started_at,
    completed_at,
    response_details ? 'superseded_at'  as is_superseded,
    request_payload -> 'properties'     as properties
from {{ source('leadflow', 'crm_write_log') }}
