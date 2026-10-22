# LeadFlow EU — Database Design

Operational tables, relationships and history requirements for the LeadFlow EU MVP.

Status: Tables and relationships defined. Keys, constraints and SQL implementation pending.

Operational tables, relationships and history requirements for the LeadFlow EU MVP.

Status: Tables and relationships defined. Keys, constraints and SQL implementation pending.

## Design approach

Separate original source data, canonical business records and operational history.

This allows us to explain:
- What information arrived.
- Which company and lead it belongs to.
- Why a routing or priority decision was made.
- Who owned the lead at a particular time.
- Whether follow-up met its deadline.

Invalid submissions and participant enquiries can be recorded without creating a sales lead.

## Tables

| Table | One row represents | Main purpose |
|---|---|---|
| ingestion_events | One unique source event | Preserve the original payload, source identifiers, timestamps and processing status |
| companies | One canonical company | Store current company identity and company-level qualification attributes |
| leads | One canonical business contact | Store contact identity, business country and relationship classification |
| qualification_evidence | One recorded observation supporting a qualification field | Preserve the value, source, observation time and evidence method and supporting detail |
| engagement_events | One unique prospect action | Support engagement scoring without counting duplicate events |
| engagement_coverage | One extraction coverage record for a source and defined scope | Distinguish complete activity data from partial or failed extraction |
| owners | One sales representative or Sales Manager | Store staff identity and CRM owner mapping |
| owner_eligibility_history | One effective period of an owner's territory and active status | Explain who was eligible for assignment at a historical time |
| routing_state | One country's current round-robin position | Support consistent owner rotation |
| rule_versions | One approved version of the business rules | Preserve the configuration used for routing, scoring and SLA targets |
| processing_decisions | One recorded evaluation of an event or lead | Preserve evaluated inputs, scores, priority, routing outcome and reason codes |
| assignments | One effective period of lead ownership | Preserve initial assignment and subsequent owner changes |
| review_cases | One issue requiring human review | Track data-quality, identity, territory and partnership cases |
| review_actions | One action taken on a review case | Preserve corrections, assignments, reviewer identity and reasons |
| followup_activities | One unique sales activity | Determine the first qualifying follow-up |
| sla_tracking | One first-follow-up obligation for a lead | Store the assignment anchor, current deadline, qualifying activity and outcome |
| sla_history | One change or recorded event affecting an SLA obligation | Preserve deadline changes, priority changes and breaches |
| supplier_redirect_rules | One effective country-specific or default redirect configuration | Identify the designated sample-supplier destination |
| participant_redirects | One simulated redirect attempt | Record the destination, timestamp, status and any failure |
| crm_write_log | One attempted CRM update | Track intended changes, retries, results and errors |

These are operational tables. Reporting views will be designed later to simplify Power BI analysis.

## Main relationships

- One company can have many leads.
- A lead can initially have no resolved company.
- One lead can be linked to many ingestion events.
- An ingestion event may remain unlinked to a lead if invalid, unresolved or identified as a participant enquiry.
- Each engagement event belongs to at most one resolved lead; unresolved events remain available for review.
- One company can have many qualification-evidence records.
- One owner can have many eligibility-history records.
- One owner can have many lead assignments over time.
- One lead can have many assignment-history records, but only one current assignment.
- One rule version can be referenced by many processing decisions.
- One lead can have many processing decisions.
- A processing decision can exist without a lead when processing stops before identity is resolved.
- One ingestion event can have multiple historical decisions if a correction or explicit reassessment occurs.
- A retry of an already completed evaluation must reuse its existing result.
- One ingestion event or lead can have multiple review cases.
- Each review case can have many review actions.
- One lead can have many follow-up activities.
- One lead can have at most one first-follow-up SLA obligation in the MVP.
- One SLA obligation can have many history entries.
- One qualifying follow-up activity can satisfy the lead's first-follow-up obligation.
- One redirect rule can be referenced by many participant redirect attempts.
- Each participant redirect attempt references its originating ingestion event.
- One processing decision can produce multiple CRM write attempts.

## Company and contact separation

Company-level attributes:
- Company name and domain.
- Industry.
- Employee count or band.
- Research needs and frequency.
- Technology readiness.

Contact-level attributes:
- Email and name.
- Job title and function.
- Preferred language.
- Routing business country.
- Enquiry relationship classification.

Multiple contacts at the same company share company qualification information but retain their own engagement, assignment and follow-up history.

Company domain is a matching aid, not a guaranteed unique company identifier.

## Qualification evidence

Store current qualification values on the company record.

Preserve supporting observations and corrections in qualification_evidence, including:
- Field name and observed value.
- Evidence source and reference.
- Observation timestamp.
- Evidence method; actor information may be included in evidence_details when available.
- Explanation where needed.

Each processing decision also preserves the input values and evidence references used in that evaluation.

Later corrections must not change the explanation of an earlier decision.

## Engagement coverage

Each engagement_coverage record identifies:
- Source system.
- One covered event type per record.
- Covered population or extraction scope.
- Coverage start and end.
- Extraction status.
- Extraction timestamp.

Use this information to determine whether the relevant 30-day scoring window is fully covered.

A lead's absence from an event extract does not prove zero engagement unless that lead and the relevant event types are within complete coverage.

## Ownership and round-robin state

Preserve owner eligibility as effective periods rather than overwriting historical status.

Maintain one routing_state record per supported country.

Saving a new assignment and advancing the country's rotation must occur together in one database transaction.

Retries and duplicate events must not advance the rotation again.

Assignment records preserve:
- Lead.
- Owner.
- Effective start and end.
- Automatic or manual assignment method.
- Required originating decision and, for manual assignments, a required review action.
- Assignment reason.

## SLA history

sla_tracking stores one first-follow-up obligation per lead, including:

- Initial assignment, rule version and initial priority.
- SLA start time.
- Original and current deadline.
- Latest evaluated status.
- Qualifying activity reference and occurrence time, when available.
- Breach-detection and last-evaluation timestamps.

sla_history records creation, deadline shortening, status changes,
evidence corrections and follow-up recording.

History rows preserve previous and new status and deadline values.
Additional context, such as priority changes and the applicable allowance,
is stored in change_details when relevant.

Ownership changes are preserved in assignments. They do not restart the SLA.

The initial allowances are P1: 60, P2: 240 and P3: 480 business minutes.
The processing layer will calculate deadlines using the agreed calendar.

Reassignment, duplicate submissions and priority downgrades must not
extend the deadline. A priority upgrade may shorten it.

Activity occurrence time determines timeliness. Late-arriving evidence
may correct an assessed outcome, while preserving the earlier assessment
and correction history.

The database validates individual SLA and history records. Automatic
history creation, consistency between history and current state, and
deadline-transition enforcement remain processing-layer responsibilities.

## Participant referrals

Paid-survey participant enquiries are recorded through ingestion_events
and participant_redirects without requiring a sales lead.

supplier_redirect_rules defines effective country-specific destinations
and an optional default. The processing layer will select the country
rule first, then the default.

The intended business process is an automated reply directing the
participant to the selected supplier, which provided the respondent and
handles their questions. referral_method records this process as
automated_reply_panelists. Sending that reply is outside the MVP; only
the referral is simulated, and attempt_status records the outcome.

Each attempt preserves the selected supplier code, supplier name and
destination URL. Outcomes are simulated, review_required or failed.

An enquiry with no usable destination is recorded for review.
Submitted personal data is not transferred to the supplier.

Reporting counts distinct ingestion events rather than attempts.
The metric is "Participant referrals simulated"; it does not represent
emails sent or unique people.

## CRM update attempts

crm_write_log records:
- Target CRM record.
- Originating decision.
- Intended changes.
- Stable logical update identifier.
- Attempt number.
- Attempt timestamp.
- Result and error details.

Retries belong to the same logical update. A retry must not create a new business decision or assignment.

## History and current state

Current records support operational use. History records explain changes over time.

Do not overwrite:
- Original source payloads.
- Previous processing decisions.
- Previous assignments, except to close their effective period.
- Review actions.
- SLA history.
- CRM write attempts.

Corrections create traceable changes rather than silently replacing evidence.

## Design completion criteria

- Every input from the contract has an identified storage location.
- Invalid and participant records can be retained without creating sales leads.
- Company information is shared across associated contacts.
- Historical decisions remain explainable after data or rules change.
- Owner eligibility and assignment history support historical reconstruction.
- Engagement completeness can be evaluated for a specific assessment time.
- Round-robin updates can be saved atomically with assignments.
- SLA changes preserve previous deadlines and outcomes.
- CRM retries and redirect attempts remain traceable.

## Keys and integrity rules

### Identifier conventions

- Use system-generated UUIDs for internal business and history records.
- Keep external CRM and source identifiers as text.
- Internal identifiers remain stable when names, emails or source values change.
- Primary keys cannot be null.
- A nullable foreign key means the relationship is not yet resolved or does not apply.

### Primary keys and references

| Table | Primary key | Main foreign-key references |
|---|---|---|
| ingestion_events | ingestion_event_id | lead_id → leads, optional |
| companies | company_id | None |
| leads | lead_id | company_id → companies, optional |
| qualification_evidence | evidence_id | company_id → companies; ingestion_event_id → ingestion_events, optional |
| engagement_events | engagement_event_id | lead_id → leads, optional until resolved |
| engagement_coverage | coverage_id | None; extraction scope is recorded explicitly |
| owners | owner_id | manager_id → owners, optional |
| owner_eligibility_history | eligibility_id | owner_id → owners |
| routing_state | country_code | last_assigned_owner_id → owners, optional |
| rule_versions | rule_version | None; readable text identifier such as LF-RULES-v1.0 |
| processing_decisions | decision_id | ingestion_event_id → ingestion_events, optional; lead_id → leads, optional; rule_version → rule_versions; selected_owner_id → owners, optional |
| assignments | assignment_id | lead_id → leads; owner_id → owners; decision_id → processing_decisions; review_action_id → review_actions, optional |
| review_cases | review_case_id | ingestion_event_id → ingestion_events, optional; lead_id → leads, optional |
| review_actions | review_action_id | review_case_id → review_cases; selected_owner_id → owners, optional |
| followup_activities | activity_id | lead_id → leads, optional until resolved; performed_by_owner_id → owners, optional until resolved |
| sla_tracking | sla_id | lead_id → leads; initial_assignment_id → assignments; rule_version → rule_versions; qualifying_activity_id → followup_activities, optional |
| sla_history | sla_history_id | sla_id → sla_tracking; decision_id → processing_decisions, optional; activity_id → followup_activities, optional |
| supplier_redirect_rules | redirect_rule_id | None |
| participant_redirects | redirect_attempt_id | ingestion_event_id → ingestion_events; redirect_rule_id → supplier_redirect_rules, optional |
| crm_write_log | write_attempt_id | decision_id → processing_decisions |

owners also stores a unique readable staff code, such as ES-01 or SALES-MANAGER.

A processing decision must reference an ingestion event, a lead, or both.

A review case must reference an ingestion event, a lead, or both.

Reviewer identifiers are stored as actor references. They are not restricted to owners because RevOps reviewers may not be sales staff.

### Duplicate-prevention rules

| Record | Uniqueness rule |
|---|---|
|| Ingestion event | source_system + source_event_id, when source_event_id is populated |
| Canonical lead | normalised_email |
| CRM contact mapping on leads | crm_contact_id, when populated, within the single HubSpot test account |
| CRM company mapping on companies | crm_company_id, when populated, within the single HubSpot test account |
| Engagement event | source_system + source_event_id |
| Follow-up activity | source_system + source_activity_id |
| Owner | staff_code |
| CRM owner mapping | crm_owner_id, when populated |
| Processing decision | evaluation_key |
| SLA obligation | lead_id |
| CRM update attempt | logical_update_id + attempt_number |
| Participant redirect attempt | ingestion_event_id + attempt_number |
| Qualification evidence | evidence_key |
| Engagement coverage attempt | coverage_key |
| Review case | case_key |
| Review action | action_key |
| Assignment | assignment_key |
| SLA history event | history_key |
| SLA creation history | At most one sla_created event per sla_id |
| Supplier redirect rule version | rule_key |
| Successful participant simulation | At most one simulated attempt per ingestion_event_id |
| Recorded CRM success | At most one succeeded attempt per logical_update_id |

Ingestion events without a source_event_id remain traceable through
ingestion_event_id. The source-system/event-ID unique constraint does
not deduplicate these records. They require validation or review before
normal idempotent processing.

Canonical email uniqueness is an MVP identity policy. Ambiguous or conflicting source identities remain in ingestion and review until resolved.

Do not apply email-provider-specific transformations such as removing dots or plus-address tags.

Company names and domains are not unique keys.

Duplicate source CRM contacts must not create duplicate canonical leads. Their original identifiers remain preserved in ingestion payloads and review history.

An evaluation_key identifies one intended evaluation. Retries reuse it; an explicit reassessment receives a new key.

When an enquiry and an engagement feed describe the same sales request, link them through a shared submission reference and score the request once.

### Current records and effective periods

- A lead can have at most one current assignment.
- An assignment is effective at a given time when its start has been reached and its end is either absent or later than that time.
- Assignment periods for the same lead must not overlap.
- Owner eligibility periods for the same owner must not overlap in this MVP.
- Effective periods use an inclusive start and exclusive end.
- An end timestamp, when present, must be later than its start.
- Country-specific supplier redirect rules must not overlap for the same country.
- Default supplier redirect rules must not overlap with other default rules.
- A country-specific rule takes precedence over the default rule.

Historical reassignment closes the previous assignment period and creates a new assignment record in the same transaction.

### Value and status checks

- Normalised email must be present and nonblank on canonical leads.
- Invalid emails can remain in ingestion but cannot create assignment-ready canonical leads.
- Exact employee counts must be positive when populated.
- Fit and engagement totals must remain between 0 and 100.
- Priority must be P1, P2, P3 or null when not applicable.
- Unknown qualification values remain null or explicitly unknown according to the data dictionary.
- Missing values must not silently become false.
- Country routing state is restricted to ES, PT and FR.
- Attempt numbers start at 1.
- SLA business-minute allowances are P1: 60, P2: 240 and P3: 480 under the initial policy.
- Extraction coverage end must be later than coverage start.
- Status fields accept only the controlled values defined for that record type.

A known zero score is distinguishable from an incomplete assessment.

### Relationship consistency

- A selected owner on a decision must exist.
- An automatic assignment must select an active representative eligible for that territory at assignment time.
- An assignment's decision and lead must refer to the same lead.
- An SLA's initial assignment must belong to that SLA's lead.
- A qualifying activity linked to an SLA must belong to the same lead.
- SLA history references must be consistent with the obligation's lead.
- A review action used to justify an assignment must belong to a case concerning that lead or its originating event.
- Supplier-only and participant enquiries must not create buyer follow-up SLA obligations.
- Unresolved engagement or follow-up records cannot satisfy scoring or SLA requirements until identity is resolved.

The current schema uses individual foreign keys to verify that referenced
records exist. It does not yet enforce same-lead consistency across
assignments, decisions, SLA records and activities through composite
foreign keys. These relationships require processing-layer validation
and integration tests.

Eligibility and other cross-record business checks are validated within the processing transaction and covered by integration tests.

### Atomic assignment and retry handling

For a new automatic assignment:

1. Lock the country's routing_state record.
2. Check whether the intended evaluation was already completed.
3. Select the next eligible representative.
4. Save the decision and assignment.
5. Advance round-robin state.
6. Commit all changes together.

If the transaction fails, none of these changes should persist.

CRM API calls happen outside this transaction. Their logical update identifiers and attempts are recorded separately.

Database uniqueness prevents duplicate internal operations. CRM retries must also check the desired external state before applying an update again.

### SLA integrity

- One lead has at most one first-follow-up obligation in the MVP.
- Reassignment and duplicate submissions do not create a new obligation.
- The initial deadline is calculated from first successful assignment using the applicable priority and working calendar.
- A priority upgrade can shorten but never extend the deadline.
- A priority downgrade cannot extend the deadline.
- A qualifying activity must occur at or after first assignment.
- An activity at the deadline qualifies as on time.
- Late follow-up preserves the breach.
- Late-arriving evidence can correct the assessed outcome, with the previous assessment and correction preserved in history.

Business-hour calculations and deadline-transition rules will be implemented and tested in the processing layer. They are not implemented by the current schema.

### Raw data and rejected records

- Apply strict business constraints to canonical and operational records.
- Preserve invalid source values in the original payload.
- Missing source identifiers or malformed timestamps must produce a traceable ingestion error.
- Use the internal ingestion identifier to track rejected records.
- Only events with valid source identities are eligible for normal idempotent processing.
- Future-dated engagement events do not contribute before their occurrence time.

### Deletion policy

- Do not cascade-delete operational history when a company, lead or owner is removed.
- Referenced records are restricted from deletion.
- Retain referenced records. Use owner eligibility history to stop new assignments to unavailable representatives. General archival fields are not currently implemented across all tables.
- Destructive database resets are permitted only in the disposable development environment.

### Enforcement responsibilities

| Mechanism | Implemented responsibility |
|---|---|
| Primary and foreign keys | Stable identity and existence of referenced records |
| Unique constraints and indexes | Unique event and operation keys, one SLA per lead, and selected duplicate-success protections |
| Check constraints | Controlled statuses, score ranges, required evidence and valid time boundaries |
| Exclusion constraints | Non-overlapping assignment, eligibility and supplier-rule periods |

### Processing and access controls still to implement

- Validate email syntax and field-specific qualification values.
- Resolve identities and conflicting evidence.
- Enforce same-lead relationships across linked records.
- Check owner roles and historical eligibility.
- Lock routing state and save assignments atomically.
- Calculate scores, priorities and business-hour deadlines.
- Preserve the initial SLA anchor and prevent deadline extensions.
- Update operational state and its audit history in one transaction.
- Maintain updated_at timestamps; their defaults only apply on insertion.
- Protect historical records and approved rule versions against unauthorised edits.
- Select effective supplier rules and copy destination snapshots.
- Reconcile uncertain CRM outcomes and enforce retry limits.
- Prevent duplicate external updates; local uniqueness alone cannot guarantee this.

These controls require implementation and integration tests in later work.

## Known limitations and open decisions

Recorded 2026-10-22. These are deliberate gaps in what the database
enforces today. Each needs a decision before it is closed; until then
the proposed handling applies.

| ID | Limitation | Current behaviour | Proposed handling | Status |
|---|---|---|---|---|
| DR-016 | Ingestion events without a `source_event_id` are not deduplicated | They are stored (so malformed input is kept), and repeats are allowed because the `(source_system, source_event_id)` unique key ignores NULLs. Documented by test 26 in `SQL/tests/001_test_core_constraints.sql` | Keep storing them. Detect repeats in the Python ingestion layer, e.g. by a hash of the raw payload, and send them to review | **Decided 2026-10-22**: Python dedupe; to implement in Gate 3 |
| DR-017 | Lead email format is not validated | `leads.normalised_email` must be non-empty, trimmed and lower-case, but a value such as `abc` is accepted | Validate email format in the Python ingestion layer. Optionally add a minimal SQL check that the value contains `@` | **Decided 2026-10-22**: SQL now requires text@text (`LIKE '%_@_%'`); full validation in Python (Gate 3) |
| DR-018 | "Unknown" has two representations | Allowed-value columns (e.g. `industry_code`, `research_frequency`, `preferred_language`) accept both `NULL` and `'unknown'` | Choose one policy before reporting work, so Power BI never shows unknown as zero or as two different categories (see DR-012) | **Resolved 2026-10-22**: always `'unknown'`. The 7 affected columns are now `NOT NULL DEFAULT 'unknown'` |

