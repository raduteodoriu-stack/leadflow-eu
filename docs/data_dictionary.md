# LeadFlow EU — Data Dictionary

Input fields, controlled values, validation rules and calculated outputs for the LeadFlow EU MVP.

Business rules are defined in LF-002.

## Document scope and implementation status

This document describes incoming data, its mapping to PostgreSQL storage,
and calculated outputs.

Source-field names may differ from database-column names. The mappings
below identify these differences.

All 20 planned tables have been created, and individual constraint tests
have passed in the development database. Final schema review and
clean-install validation remain pending.

Database constraints enforce selected structural rules. Source validation,
normalisation, scoring, routing, SLA calculations and integration behaviour
still require processing-layer implementation and tests.

Unless explicitly constrained by SQL, suggested source-system names and
reason codes are application conventions rather than database-enforced lists.

## Input design principles

- Preserve the original source payload before standardisation.
- Separate prospect-provided information, CRM information and system-generated values.
- Accept incomplete submissions into ingestion so they can be tracked and reviewed.
- Required for assignment does not mean required for ingestion.
- Missing information remains unknown; it must not silently become a confirmed zero or “no”.
- Use synthetic contact and company information throughout the MVP.
- Collect qualification information progressively; not every field belongs on the first enquiry form.

## 1. Source and ingestion metadata

These fields come from the source system or ingestion service, not the prospect.

| Field | PostgreSQL type | Required in storage? | Definition |
|---|---|---|---|
| source_system | TEXT | Yes; nonblank | Source identifier; intended adapters include synthetic_fixture and hubspot. SQL does not restrict it to these values |
| source_event_id | TEXT | No at ingestion; required for normal processing | Stable identifier for the event or source-record version |
| source_record_id | TEXT | No | Source contact or submission identifier |
| event_type | TEXT | No at ingestion; required for normal processing | lead_created or lead_updated |
| source_occurred_at | TIMESTAMPTZ | No at ingestion; required for normal processing | When the source event occurred |
| received_at | TIMESTAMPTZ | Yes; defaults to CURRENT_TIMESTAMP | When LeadFlow received the event |
| source_channel | TEXT | No | web_form, event, referral, outbound, partner or unknown |
| raw_payload | JSONB | Yes | Original submitted data. The input contract expects an object; the current SQL does not enforce object shape |

The combination of source_system and source_event_id is unique when source_event_id is populated. Events without it remain traceable through ingestion_event_id but are not deduplicated by that constraint.

The database requires source_event_id, source_occurred_at and event_type for processing_status values processing, processed and redirected.

Repeated delivery of the same event must preserve that identity.

For scheduled CRM extraction, the adapter must derive a stable event identity from the source record and its version or modification timestamp.

Malformed input must remain traceable in ingestion with an error status.

## 2. Contact and company identity

| Field | Type | Required for assignment? | Definition |
|---|---|---|---|
| email | Text | Yes | Contact email used for validation and identity matching |
| first_name | Text | No | Contact’s given name |
| last_name | Text | No | Contact’s family name |
| job_title | Text | No | Original job title supplied by the contact or CRM |
| contact_function | Controlled text | No | Standardised professional function |
| company_name | Text | No | Submitted company name |
| company_domain | Text | No | Submitted company website or domain |
| crm_contact_id | Text | When available | Existing HubSpot contact identifier |
| crm_company_id | Text | When available | Existing HubSpot company identifier |
| preferred_language | Controlled text | No | es, pt, fr, en, other or unknown |

Allowed contact_function values:
- research_insights
- fieldwork_sample_operations
- panel_management
- marketing_consumer_insights
- ux_product_research
- technology_integrations
- partnerships
- founder_executive
- other
- unknown

Missing company name or domain does not block assignment when email and country are valid.

A company association must not be invented from an ambiguous name or shared public email domain.

### Storage mapping

- Incoming email is preserved in ingestion_events.raw_payload.
- Validated, normalised email is stored in leads.normalised_email.
- Contact attributes and crm_contact_id are stored in leads.
- Company attributes and crm_company_id are stored in companies.
- leads.company_id is nullable until the company association is resolved.
- The database checks normalised-email presence, lowercase form, trimmed
  outer spaces and uniqueness. Full email syntax validation belongs to
  the processing layer.
- Company-domain normalisation is a processing responsibility.

## 3. Country and enquiry purpose

| Field | Type | Required for assignment? | Definition |
|---|---|---|---|
| business_country_raw | Text | Yes | Business country explicitly supplied on the enquiry |
| crm_business_country_raw | Text | No | Existing CRM country, retained to detect conflicting information |
| enquiry_type | Controlled text | No | What the contact is requesting |
| enquiry_message | Text | No | Original explanatory message |
| relationship_type_declared | Controlled text | No | buyer, supplier, both or unknown, where explicitly supplied |

Allowed enquiry_type values:
- demo_request
- sales_contact_request
- sample_quote_request
- panel_software_request
- audience_supply_request
- general_enquiry
- survey_participation_request
- unknown

Standardisation rules:
- Convert recognised country names and aliases to two-letter country codes.
- Spain, España and ES map to ES.
- Portugal and PT map to PT.
- France and FR map to FR.
- A recognised country outside ES, PT and FR is unsupported, not invalid.
- Conflicting submitted and CRM business countries require review.
- Do not infer business country from language, email domain or IP address.

Relationship classification:
- Requests to buy software or respondents indicate buyer intent.
- Requests only to supply or monetise an audience indicate supplier intent.
- Explicit buying and supply needs indicate both.
- Ambiguous or conflicting intent remains unknown for qualification.

A survey_participation_request identifies a paid-survey participant enquiry.
Exclude it from sales assignment, buyer scoring and buyer SLA metrics.

The intended business process is an automated reply directing the
participant to the designated supplier's participation page.

The MVP simulates this reply request without sending email or transferring
submitted personal data. participant_redirects records the selected
supplier and destination snapshots, attempt time and outcome.

Report "Participant referrals simulated" using distinct ingestion events,
not attempt counts or claimed unique-person counts.

### Storage mapping

- business_country_raw, crm_business_country_raw, enquiry_type,
  enquiry_message and relationship_type_declared remain in
  ingestion_events.raw_payload.
- The resolved country is stored in leads.business_country_code.
- The resolved relationship is stored in leads.relationship_type.
- The SQL country check enforces two uppercase letters. Country
  recognition, supported-territory checks and conflict handling belong
  to the processing layer.
- Enquiry types are input-contract values; they are not a dedicated
  controlled column in the current schema.

## 4. Company-fit inputs

These fields support scoring. Missing values do not block country-based assignment.

| Field | Type | Allowed values or meaning |
|---|---|---|
| employee_count | Integer | Exact employee count, if known; must be at least 1 |
| employee_band_declared | Controlled text | 1-10, 11-49, 50-249, 250-999, 1000_plus or unknown |
| industry_raw | Text | Original industry description |
| industry_code | Controlled text | Standardised industry classification listed below |
| research_use_case | Controlled text | respondents_fieldwork, panel_management, both, other or unknown |
| research_frequency | Controlled text | monthly_or_more, recurring_less_than_monthly, one_off, none or unknown |
| ongoing_panel_management_need | Boolean or null | Confirmed ongoing need; null means unknown |
| relevant_need_confirmed | Boolean or null | Whether a relevant product need has been established |
| uses_digital_research_tools | Boolean or null | Whether digital research or panel tools are currently used |
| integration_required | Boolean or null | Whether an integration requirement is confirmed |
| technical_resource_available | Boolean or null | Whether a technical implementation resource is available |
| adoption_owner_confirmed | Boolean or null | Whether someone owns self-service adoption |
| onboarding_support_needed | Boolean or null | Whether adoption requires support |
| adoption_interest_confirmed | Boolean or null | Whether interest in adopting the platform is confirmed |
| adoption_unwilling_or_unable | Boolean or null | Explicit inability or unwillingness to adopt |

Company-size rules:
- At least one of exact count or declared band is needed for a complete size assessment.
- Derive the band from an exact count when available.
- If count and declared band conflict, flag the size component for review.
- Do not silently choose whichever value produces the higher score.

Qualification rules:
- An unchecked or absent response must not automatically mean false.
- Contradictory qualification answers make the affected component unknown pending review.
- Do not infer research frequency or technology readiness from company size or industry.
- Free-text interpretation requiring judgement remains a human-review task in the MVP.

## 5. Industry classification

Use one primary industry_code per company.

| industry_code | Description | LF-002 industry points |
|---|---|---:|
| market_research | Market-research and insights agency | 40 |
| polling | Polling and opinion-research organisation | 40 |
| research_consultancy | Consultancy whose primary activity is research | 40 |
| panel_sample_provider | Panel or sample provider | 40 |
| research_technology | Research software or technology provider | 30 |
| advertising_media_pr_agency | Advertising, media or PR agency | 30 |
| ux_research_agency | Specialist UX research agency | 30 |
| management_consultancy | Broader management consultancy | 30 |
| consumer_goods | Consumer goods, food, beverages, beauty or household products | 20 |
| retail_ecommerce | Retail or e-commerce | 20 |
| technology_telecoms | Technology or telecommunications | 20 |
| financial_services | Banking, insurance or fintech | 20 |
| automotive_mobility | Automotive or mobility | 20 |
| healthcare_pharma | Healthcare or pharmaceuticals | 20 |
| travel_hospitality | Travel, hospitality or leisure | 20 |
| media_entertainment_gaming | Media owner, entertainment or gaming business | 20 |
| energy_utilities | Energy or utilities | 20 |
| public_academic_nonprofit | Public body, university or nonprofit conducting research | 20 |
| other | Other known industry | 0 |
| unknown | Insufficient information | Unknown |

Classification is based on primary business activity.

A research technology company is classified as research_technology rather than generic technology_telecoms.

A media agency is distinguished from a media owner.

The points are calculated from versioned rules, not supplied by the prospect.

## 6. Evidence for qualification fields

## 6. Evidence for qualification fields

qualification_evidence stores one observation supporting a company
qualification field.

| Column | PostgreSQL type | Definition |
|---|---|---|
| evidence_id | UUID | Generated primary key |
| evidence_key | TEXT | Required unique key for one field observation; reused on retries |
| company_id | UUID | Required reference to companies |
| ingestion_event_id | UUID | Optional reference to the originating ingestion event |
| field_name | TEXT | Supported qualification field |
| observed_value | JSONB | String, number or boolean; SQL NULL means explicitly unknown |
| source_system | TEXT | Required nonblank source identifier |
| source_reference | TEXT | Required source record, URL or other traceable reference |
| evidence_method | TEXT | self_reported, sales_confirmed, external_source or rule_derived |
| observed_at | TIMESTAMPTZ | Required observation timestamp |
| recorded_at | TIMESTAMPTZ | Database recording timestamp |
| evidence_details | JSONB | Required object containing supporting context |

The current schema has no dedicated evidence_source, recorded_by or evidence_note columns. Actor information and explanatory notes may be stored in evidence_details.

observed_value accepts JSON scalars but rejects JSON null, objects and arrays. Use SQL NULL for an unknown observation.

Field-specific type and controlled-value validation belongs to the processing layer before updating companies.

New observations receive new evidence keys. Preserve earlier evidence when information changes.

Derived evidence should identify its original input and mapping rule in evidence_details.

## 7. Engagement-event inputs

engagement_events stores individual prospect actions.

| Column | PostgreSQL type | Definition |
|---|---|---|
| engagement_event_id | UUID | Generated primary key |
| source_system | TEXT | Required nonblank source identifier |
| source_event_id | TEXT | Required nonblank event identifier; unique with source_system |
| lead_id | UUID | Optional resolved lead reference |
| source_contact_id | TEXT | Source contact identifier; required when lead_id is absent |
| event_type | TEXT | Required canonical event type |
| occurred_at | TIMESTAMPTZ | When the action happened |
| recorded_at | TIMESTAMPTZ | When the event was stored |
| related_content_id | TEXT | Optional page, webinar or resource identifier |
| event_details | JSONB | Required object containing additional source context |

Canonical event_type values:

- demo_requested
- sales_contact_requested
- quote_requested
- pricing_page_visited
- webinar_attended
- guide_downloaded
- case_study_downloaded

### Input-to-storage mapping

| Earlier input value or field | Stored value or location |
|---|---|
| demo_request | demo_requested |
| sales_contact_request | sales_contact_requested |
| sample_quote_request | quote_requested |
| pricing_page_visit | pricing_page_visited |
| product_webinar_attended | webinar_attended |
| product_guide_download | guide_downloaded |
| case_study_download | case_study_downloaded |
| asset_id | related_content_id |
| related_submission_id | event_details.related_submission_id |
| contact_email | Used for identity resolution; may be preserved in event_details |
| received_at | Source receipt time may be preserved in event_details; recorded_at is database storage time |

An event must have a resolved lead_id or a nonblank source_contact_id.
An email-only event must resolve to a lead before insertion, or remain
in the source ingestion/error workflow until it can meet this requirement.
Do not invent a source contact identifier.

### Processing rules

- Resolve each event to at most one canonical lead.
- Preserve unresolved events with source contact identifiers.
- Deduplicate the same request across enquiry and engagement feeds using
  a shared submission reference.
- Apply the 30-day window and caps defined in LF-002.
- Webinar registration alone does not count as attendance.
- Future-dated events do not contribute before their occurrence time.
- Separate same-day pricing visits remain evidence records, but scoring
  awards points only once per distinct day under the agreed rule.

Cross-feed deduplication and scoring are processing-layer responsibilities.

## 8. Engagement-data availability

engagement_coverage stores one collection attempt for a source, event
type, population and time window.

| Column | PostgreSQL type | Definition |
|---|---|---|
| coverage_id | UUID | Generated primary key |
| coverage_key | TEXT | Required unique collection-attempt key |
| source_system | TEXT | Required source identifier |
| event_type | TEXT | One canonical engagement event type from section 7 |
| population_key | TEXT | Stable identifier for the covered population |
| population_details | JSONB | Required nonempty object defining the population or snapshot |
| window_start_at | TIMESTAMPTZ | Inclusive start |
| window_end_at | TIMESTAMPTZ | Exclusive end; later than start |
| coverage_status | TEXT | complete, partial or failed |
| collected_event_count | INTEGER | Nonnegative count; nullable when unknown |
| checked_at | TIMESTAMPTZ | When coverage was checked; cannot precede window end |
| error_code | TEXT | Required for failed coverage |
| error_detail | TEXT | Optional error explanation |
| coverage_details | JSONB | Required object containing collection evidence |

Complete coverage requires a known count and no error fields.
A complete result with zero events is valid.

Overlapping windows and later collection attempts are allowed.
A new attempt receives a new coverage_key.

The earlier names coverage_start_at, coverage_end_at and extraction_status map to window_start_at, window_end_at and coverage_status.

There is no last_successful_extract_at column. Successful collection times can be obtained from complete coverage records for the relevant scope.

A definitive zero engagement score requires complete coverage of the relevant sources, event types, population and assessment window.

Incomplete coverage must remain distinguishable from confirmed zero.
Any provisional score is accompanied by engagement_data_complete = FALSE.

Known explicit sales requests can still trigger P1 according to LF-002, even when other engagement sources are incomplete.

## 9. Representative and assignment-reference inputs

### owners

| Column | PostgreSQL type | Definition |
|---|---|---|
| owner_id | UUID | Generated internal identifier |
| staff_code | TEXT | Required unique readable code |
| display_name | TEXT | Required fictional staff name |
| owner_role | TEXT | sales_rep or sales_manager |
| crm_owner_id | TEXT | Optional unique CRM owner identifier |
| manager_id | UUID | Optional reference to another owner |
| created_at | TIMESTAMPTZ | Creation timestamp |

ES-01, ES-02, PT-01, PT-02, FR-01 and FR-02 are staff_code values, not owner_id values. Initial staff records will be seeded separately.

### owner_eligibility_history

| Column | PostgreSQL type | Definition |
|---|---|---|
| eligibility_id | UUID | Generated primary key |
| owner_id | UUID | Required owner reference |
| country_code | TEXT | ES, PT or FR |
| is_eligible | BOOLEAN | Whether the owner can receive new assignments during this period |
| effective_from | TIMESTAMPTZ | Inclusive start |
| effective_to | TIMESTAMPTZ | Exclusive end; NULL means open-ended |
| change_reason | TEXT | Required explanation |
| recorded_at | TIMESTAMPTZ | Recording timestamp |

The earlier input names active and effective_at map to is_eligible and effective_from.

Periods cannot overlap for the same owner. The processing layer must also check the owner's role and territory when assigning leads.

### routing_state

One row per supported country stores country_code, last_assigned_owner_id and updated_at.

The routing position is system-managed. It must be advanced in the same transaction as a successful automatic assignment.

## 10. Follow-up activity inputs

followup_activities stores sales activity evidence separately from prospect engagement.

| Column | PostgreSQL type | Definition |
|---|---|---|
| activity_id | UUID | Generated primary key |
| source_system | TEXT | Required source identifier |
| source_activity_id | TEXT | Required activity identifier; unique with source_system |
| lead_id | UUID | Optional until the contact is resolved |
| performed_by_owner_id | UUID | Optional until the performer is resolved |
| source_contact_id | TEXT | Optional source contact reference |
| source_owner_id | TEXT | Optional source performer reference |
| activity_type | TEXT | call, email, administrative or other |
| activity_outcome | TEXT | Outcome permitted for the activity type |
| is_automated | BOOLEAN | TRUE, FALSE or NULL when not established |
| occurred_at | TIMESTAMPTZ | Required activity occurrence time |
| recorded_at | TIMESTAMPTZ | Database recording time |
| activity_details | JSONB | Required object containing supporting context |

### Allowed outcomes

| activity_type | Allowed activity_outcome values |
|---|---|
| call | connected, no_answer, voicemail, busy, failed, cancelled, unknown |
| email | sent, draft, failed, unknown |
| administrative | completed, failed, cancelled, unknown |
| other | completed, failed, cancelled, unknown |

### Input mapping

- call_attempt maps to call.
- individual_sales_email maps to email with is_automated = FALSE.
- automated_email maps to email with is_automated = TRUE.
- internal_note and task_created map to administrative.
- invalid_number maps to failed, preserving the original outcome in activity_details.
- Incoming outcome maps to activity_outcome.
- An incoming contact_email is used for identity resolution and may be preserved in activity_details.

A meeting invitation can be represented as email/sent only when source evidence confirms an individually sent outreach message. Calendar-record creation alone does not qualify.

Apply LF-001's qualifying-follow-up definition in the processing layer.
Unknown automation status or unresolved identities cannot establish qualifying follow-up.

Use occurred_at to evaluate timeliness. recorded_at identifies when the database received the evidence.

Drafts, failed sends, automated messages and administrative activities do not satisfy the first-follow-up SLA.

## 11. Manual review and override inputs

review_cases stores the review subject, reason, current status and
responsible reviewer.

review_actions stores each action taken on a case.

| review_actions column | PostgreSQL type | Definition |
|---|---|---|
| review_action_id | UUID | Generated primary key |
| action_key | TEXT | Required unique action identifier |
| review_case_id | UUID | Required case reference |
| performed_by | TEXT | Required stable reviewer identifier |
| performed_at | TIMESTAMPTZ | Action timestamp |
| action_type | TEXT | Controlled action type |
| action_reason | TEXT | Required explanation |
| action_details | JSONB | Required object containing action context |
| selected_owner_id | UUID | Required only for owner_selected; otherwise NULL |

Allowed action_type values:

- review_started
- information_requested
- data_corrected
- owner_selected
- reprocessing_requested
- case_resolved
- case_reopened
- note_added

### Input mapping

- actor_id maps to performed_by.
- action_at maps to performed_at.
- reason_note maps to action_reason.
- reason_code may be preserved in action_details.reason_code.
- corrected_values may be preserved in action_details.corrected_values.
- correct_data and classify_relationship map to data_corrected when
  an actual field correction is made.
- assign_owner and reassign_owner map to owner_selected; actual ownership
  is recorded separately in assignments.
- Identity confirmation and non-sales exclusion are described in
  action_details and represented by the action actually performed,
  such as data_corrected or case_resolved.

The processing layer retrieves and preserves previous values.
Actions and corresponding case-state changes must be saved atomically.
Historical actions must not be silently overwritten.

## 12. System-calculated fields

These are outputs, not prospect inputs:

- Canonical lead ID and company ID.
- Normalised email and company domain.
- Standardised country code.
- Resolved relationship type.
- Fit component points and total.
- Fit completeness status and band.
- Engagement score, band and availability status.
- P1, P2 or P3 priority.
- Assigned owner or review queue.
- Assignment timestamp and round-robin state.
- SLA allowance and deadline.
- Priority and deadline-change history.
- First qualifying follow-up and SLA outcome.
- Exception and decision reason codes.
- Rule version.

## 13. Initial enquiry form

Keep the initial form short.

Required:
- Email.
- Business country.
- Enquiry type.

Optional:
- Name.
- Company name.
- Company website.
- Employee band.
- Industry.
- Job title.
- Enquiry message.

Detailed research needs and technology-readiness fields can come from subsequent qualification or CRM information.

Missing optional qualification data must not prevent a valid enquiry from reaching a representative.

## 14. Timestamp conventions

- Require a timezone or UTC offset for incoming timestamps.
- Store timestamps as timezone-aware instants.
- Use Europe/Madrid for business-calendar calculations.
- Account for daylight-saving changes through the named timezone.
- Do not guess a timezone for ambiguous source timestamps; flag them for review.
- Preserve source occurrence, ingestion and processing timestamps separately.

## 15. Operational statuses and action types

These values match the current SQL constraints.

| Table.column | Allowed values |
|---|---|
| ingestion_events.processing_status | received, processing, processed, review_required, redirected, rejected, failed |
| processing_decisions.decision_outcome | assignment_required, review_required, redirection_required, rejection_required, no_change |
| review_cases.review_status | open, in_progress, resolved |
| review_actions.action_type | review_started, information_requested, data_corrected, owner_selected, reprocessing_requested, case_resolved, case_reopened, note_added |
| assignments.assignment_method | round_robin, manual_review |
| sla_tracking.sla_status | pending, met, breached |
| sla_history.event_type | sla_created, deadline_shortened, status_changed, evidence_corrected, followup_recorded |
| engagement_coverage.coverage_status | complete, partial, failed |
| participant_redirects.attempt_status | simulated, review_required, failed |
| crm_write_log.attempt_status | in_progress, succeeded, failed, unknown, simulated |

### Interpretation

- Decision outcomes describe intended actions. They do not confirm that
  an assignment, referral or CRM update has been executed.
- In the MVP, ingestion status redirected represents completion of the
  simulated participant-referral workflow. It does not mean email was sent.
- Participant referrals are recorded as simulated, never sent.
- CRM status unknown means the external outcome is uncertain and must
  be reconciled before scheduling another attempt.
- SLA status describes the result as of last_evaluated_at. The database
  does not automatically change pending records when time passes.
- A late qualifying follow-up leaves the SLA breached. Late-arriving
  evidence of an on-time activity may support an auditable correction.

## 16. Calculated outputs and storage

| Output | Storage |
|---|---|
| Canonical company and contact identity | companies and leads |
| Normalised email | leads.normalised_email |
| Standardised company domain | companies.company_domain |
| Resolved country | leads.business_country_code |
| Resolved relationship | leads.relationship_type |
| Inputs used in an evaluation | processing_decisions.input_snapshot |
| Fit and engagement totals | processing_decisions.fit_score and engagement_score |
| Assessment completeness | processing_decisions.fit_data_complete and engagement_data_complete |
| Priority | processing_decisions.priority |
| Intended action | processing_decisions.decision_outcome |
| Selected owner | processing_decisions.selected_owner_id |
| Decision reason codes | processing_decisions.reason_codes |
| Component scores, bands, missing fields and evidence references | processing_decisions.decision_details; JSON structure to be defined with processing logic |
| Actual ownership and effective periods | assignments |
| Round-robin position | routing_state |
| Review queue and current case state | review_cases |
| Reviewer actions and explanations | review_actions |
| Approved scoring, routing and SLA configuration | rule_versions.rule_config |
| Initial SLA priority and assignment anchor | sla_tracking.initial_priority and initial_assignment_id |
| SLA start, original deadline and current deadline | sla_tracking.sla_started_at, original_deadline_at and current_deadline_at |
| Qualifying follow-up and latest SLA outcome | sla_tracking |
| SLA changes and corrections | sla_history |
| Selected participant-referral supplier and destination | participant_redirects snapshot columns |
| CRM update payloads, attempts and outcomes | crm_write_log |

The initial SLA allowances are P1: 60, P2: 240 and P3: 480 business
minutes. Allowances are part of versioned rule configuration; there is
no dedicated allowance column in sla_tracking.

JSON object constraints validate the outer structure only. Required
keys and their meaning must be defined and validated by the processing
layer.

Timestamp defaults apply on insertion. The application must maintain
updated_at on subsequent changes.

Status checks restrict allowed values and selected field combinations.
They do not implement the complete workflow or authorise transitions.