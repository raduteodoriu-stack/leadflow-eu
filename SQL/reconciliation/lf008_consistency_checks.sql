-- LeadFlow EU: database consistency checks (reconciliation, part 1): LF-008, extended in LF-009 and LF-010
--
-- One row per check: how many records break it (0 = OK) and up to three examples.
-- Read-only. Run on its own:
--   psql -d leadflow_eu -f SQL/reconciliation/lf008_consistency_checks.sql
-- tools/reconcile.py runs the same query and adds the source-vs-database checks.

WITH
decision_count AS (
    SELECT e.ingestion_event_id, e.source_event_id, count(d.decision_id) AS n
    FROM ingestion_events e
    LEFT JOIN processing_decisions d ON d.ingestion_event_id = e.ingestion_event_id
    GROUP BY e.ingestion_event_id, e.source_event_id
),
assigned_leads AS (
    SELECT DISTINCT lead_id FROM assignments
),
crm_confirmed AS (
    -- The value each CRM contact is known to show per property: the latest confirmed one.
    SELECT DISTINCT ON (w.target_record_id, p.key) w.target_record_id, p.key, p.value
    FROM crm_write_log AS w
    CROSS JOIN LATERAL jsonb_each_text(w.request_payload -> 'properties') AS p
    WHERE w.attempt_status IN ('succeeded', 'simulated')
    ORDER BY w.target_record_id, p.key, w.completed_at DESC, w.logical_update_id DESC
),
crm_confirmed_state AS (
    SELECT target_record_id,
           coalesce(jsonb_object_agg(key, value) FILTER (WHERE value <> ''), '{}'::JSONB) AS properties
    FROM crm_confirmed GROUP BY target_record_id
),
latest_round_robin AS (
    SELECT DISTINCT ON (l.business_country_code)
           l.business_country_code AS country_code, a.owner_id
    FROM assignments a
    JOIN leads l ON l.lead_id = a.lead_id
    WHERE a.assignment_method = 'round_robin'
    ORDER BY l.business_country_code, a.effective_from DESC, a.recorded_at DESC
),
checks (check_id, description, problems, examples) AS (
    SELECT 'C01', 'Every stored event has exactly one decision',
           count(*) FILTER (WHERE n <> 1),
           string_agg(coalesce(source_event_id, ingestion_event_id::TEXT), ', ') FILTER (WHERE n <> 1)
    FROM decision_count

    UNION ALL
    SELECT 'C02', 'Every decision belongs to a stored event (or is a Sales Manager reassignment)',
           count(*), string_agg(evaluation_key, ', ')
    FROM processing_decisions
    WHERE ingestion_event_id IS NULL
      AND NOT ('MANUAL_REASSIGNMENT' = ANY (reason_codes) AND decision_outcome = 'assignment_required')

    UNION ALL
    SELECT 'C03', 'Stored event status matches its decision',
           count(*), string_agg(coalesce(e.source_event_id, e.ingestion_event_id::TEXT), ', ')
    FROM ingestion_events e
    JOIN processing_decisions d ON d.ingestion_event_id = e.ingestion_event_id
    WHERE (e.processing_status, d.decision_outcome) NOT IN (
        ('processed', 'assignment_required'), ('processed', 'no_change'),
        ('review_required', 'review_required'), ('redirected', 'redirection_required'),
        ('rejected', 'rejection_required'))

    UNION ALL
    SELECT 'C04', 'Every assignment decision has exactly one assignment',
           count(*), string_agg(d.evaluation_key, ', ')
    FROM processing_decisions d
    WHERE d.decision_outcome = 'assignment_required'
      AND (SELECT count(*) FROM assignments a WHERE a.decision_id = d.decision_id) <> 1

    UNION ALL
    SELECT 'C05', 'Every automatic assignment comes from an assignment decision',
           count(*), string_agg(a.assignment_key, ', ')
    FROM assignments a
    JOIN processing_decisions d ON d.decision_id = a.decision_id
    WHERE a.assignment_method IN ('round_robin', 'same_company_owner')
      AND d.decision_outcome <> 'assignment_required'

    UNION ALL
    SELECT 'C06', 'Every assigned lead has exactly one current owner',
           count(*), string_agg(l.normalised_email, ', ')
    FROM assigned_leads x JOIN leads l ON l.lead_id = x.lead_id
    WHERE (SELECT count(*) FROM assignments a
           WHERE a.lead_id = x.lead_id AND a.effective_to IS NULL) <> 1

    UNION ALL
    SELECT 'C07', 'Every assigned lead has an SLA record',
           count(*), string_agg(l.normalised_email, ', ')
    FROM assigned_leads x JOIN leads l ON l.lead_id = x.lead_id
    WHERE NOT EXISTS (SELECT 1 FROM sla_tracking s WHERE s.lead_id = x.lead_id)

    UNION ALL
    SELECT 'C08', 'Every SLA record has exactly one creation entry in its history',
           count(*), string_agg(s.sla_id::TEXT, ', ')
    FROM sla_tracking s
    WHERE (SELECT count(*) FROM sla_history h
           WHERE h.sla_id = s.sla_id AND h.event_type = 'sla_created') <> 1

    UNION ALL
    SELECT 'C09', 'Every review or rejection decision opened a review case',
           count(*), string_agg(d.evaluation_key, ', ')
    FROM processing_decisions d
    WHERE d.decision_outcome IN ('review_required', 'rejection_required')
      AND NOT EXISTS (SELECT 1 FROM review_cases c WHERE c.decision_id = d.decision_id)

    UNION ALL
    SELECT 'C10', 'Every redirection decision has one simulated referral',
           count(*), string_agg(d.evaluation_key, ', ')
    FROM processing_decisions d
    WHERE d.decision_outcome = 'redirection_required'
      AND (SELECT count(*) FROM participant_redirects p
           WHERE p.ingestion_event_id = d.ingestion_event_id
             AND p.attempt_status = 'simulated') <> 1

    UNION ALL
    SELECT 'C11', 'Round-robin position matches the latest round-robin assignment',
           count(*), string_agg(r.country_code, ', ')
    FROM routing_state r
    JOIN latest_round_robin x ON x.country_code = r.country_code
    WHERE r.last_assigned_owner_id IS DISTINCT FROM x.owner_id

    UNION ALL
    SELECT 'C12', 'Every company has at least one lead',
           count(*), string_agg(coalesce(c.company_domain, c.company_id::TEXT), ', ')
    FROM companies c
    WHERE NOT EXISTS (SELECT 1 FROM leads l WHERE l.company_id = c.company_id)

    UNION ALL
    SELECT 'C13', 'Every lead came from a stored event',
           count(*), string_agg(l.normalised_email, ', ')
    FROM leads l
    WHERE NOT EXISTS (SELECT 1 FROM ingestion_events e WHERE e.lead_id = l.lead_id)

    UNION ALL
    SELECT 'C14', 'Every lead has a first-contact time',
           count(*), string_agg(normalised_email, ', ')
    FROM leads WHERE first_contact_at IS NULL

    UNION ALL
    SELECT 'C15', 'Every engagement event is linked to a lead',
           count(*), string_agg(source_event_id, ', ')
    FROM engagement_events WHERE lead_id IS NULL

    -- LF-009: SLA tracking
    UNION ALL
    SELECT 'C16', 'Every met or breached SLA has the history entry that set it',
           count(*), string_agg(l.normalised_email, ', ')
    FROM sla_tracking s JOIN leads l ON l.lead_id = s.lead_id
    WHERE s.sla_status <> 'pending'
      AND s.sla_status IS DISTINCT FROM (
          SELECT h.new_status FROM sla_history h WHERE h.sla_id = s.sla_id
          ORDER BY h.recorded_at DESC, h.history_key DESC LIMIT 1)

    UNION ALL
    SELECT 'C17', 'Every SLA follow-up is a qualifying one by the owner at the time',
           count(*), string_agg(l.normalised_email, ', ')
    FROM sla_tracking s
    JOIN leads l ON l.lead_id = s.lead_id
    JOIN followup_activities f ON f.activity_id = s.qualifying_activity_id
    WHERE NOT coalesce((f.activity_details ->> 'qualifying')::boolean, FALSE)
       OR f.lead_id IS DISTINCT FROM s.lead_id
       OR NOT EXISTS (SELECT 1 FROM assignments a
                      WHERE a.lead_id = s.lead_id AND a.owner_id = f.performed_by_owner_id
                        AND a.effective_from <= f.occurred_at
                        AND (a.effective_to IS NULL OR a.effective_to > f.occurred_at))

    UNION ALL
    SELECT 'C18', 'Every open owner-unavailable alert is about a lead still with that salesperson',
           count(*), string_agg(c.case_key, ', ')
    FROM review_cases c
    JOIN assignments a ON a.lead_id = c.lead_id AND a.effective_to IS NULL
    JOIN owners o ON o.owner_id = a.owner_id
    WHERE c.reason_code = 'OWNER_UNAVAILABLE_PENDING' AND c.review_status <> 'resolved'
      AND o.staff_code IS DISTINCT FROM c.case_details ->> 'absent_owner'

    -- LF-010: CRM write-back
    UNION ALL
    SELECT 'C19', 'Every CRM contact shows what LeadFlow decided (confirmed values = intended values)',
           count(*), string_agg(d.normalised_email, ', ')
    FROM crm_desired_contact_state AS d
    LEFT JOIN crm_confirmed_state AS c ON c.target_record_id = d.target_record_id
    WHERE coalesce(c.properties, '{}'::JSONB) <> d.properties

    UNION ALL
    SELECT 'C20', 'No intended CRM update is confirmed more than once',
           count(*), string_agg(logical_update_id::TEXT, ', ')
    FROM (SELECT logical_update_id FROM crm_write_log
          WHERE attempt_status IN ('succeeded', 'simulated')
          GROUP BY logical_update_id HAVING count(*) > 1) AS twice

    UNION ALL
    SELECT 'C21', 'Every CRM update given up on has a RevOps review case',
           count(*), string_agg(w.logical_update_id::TEXT, ', ')
    FROM crm_write_log AS w
    WHERE w.attempt_status = 'failed'
      AND w.is_retryable IS NOT TRUE
      AND NOT (w.response_details ? 'superseded_at')
      AND NOT EXISTS (SELECT 1 FROM crm_write_log AS later
                      WHERE later.logical_update_id = w.logical_update_id
                        AND later.attempt_number > w.attempt_number)
      AND NOT EXISTS (SELECT 1 FROM review_cases AS c
                      WHERE c.case_key = 'CRM_WRITE_FAILED:' || w.logical_update_id::TEXT)
)
SELECT check_id, description, problems,
       -- first three examples only
       array_to_string((string_to_array(examples, ', '))[1:3], ', ') AS examples
FROM checks
ORDER BY check_id;
