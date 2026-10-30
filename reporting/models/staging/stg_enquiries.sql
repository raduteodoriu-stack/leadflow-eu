-- One row per stored inbound enquiry.
select
    ingestion_event_id                         as enquiry_id,
    source_system,
    source_event_id,
    event_type,
    source_channel,
    received_at,
    {{ madrid_date('received_at') }}           as received_date,
    processing_status,
    error_code,
    lead_id
from {{ source('leadflow', 'ingestion_events') }}
