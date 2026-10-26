-- LeadFlow EU: LF-008 database consistency checks (reconciliation, part 1)
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
    SELECT 'C02', 'Every decision belongs to a stored event',
           count(*), string_agg(evaluation_key, ', ')
    FROM processing_decisions WHERE ingestion_event_id IS NULL

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
)
SELECT check_id, description, problems,
       -- first three examples only
       array_to_string((string_to_array(examples, ', '))[1:3], ', ') AS examples
FROM checks
ORDER BY check_id;
