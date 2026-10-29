-- One row per decision. Rule number and bands come from the decision the engine saved.
select
    decision_id,
    ingestion_event_id                                      as enquiry_id,
    lead_id,
    evaluated_at,
    rule_version,
    priority,
    decision_outcome,
    decision_details ->> 'outcome'                          as engine_outcome,
    selected_owner_id,
    reason_codes,
    nullif(decision_details ->> 'priority_rule', '')::int   as priority_rule,
    fit_score,
    engagement_score,
    decision_details -> 'fit' ->> 'band'                    as fit_band,
    decision_details -> 'engagement' ->> 'band'             as engagement_band,
    fit_data_complete,
    engagement_data_complete
from {{ source('leadflow', 'processing_decisions') }}
