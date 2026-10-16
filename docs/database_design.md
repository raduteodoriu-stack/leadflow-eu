# LeadFlow EU — Database Design

Operational tables, relationships and history requirements for the LeadFlow EU MVP.

Status: Tables and relationships defined. Keys, constraints and SQL implementation pending.

# LeadFlow EU — Database Design

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
| qualification_evidence | One recorded observation supporting a qualification field | Preserve the value, source, observation time and reviewer |
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
- Recording actor.
- Explanation where needed.

Each processing decision also preserves the input values and evidence references used in that evaluation.

Later corrections must not change the explanation of an earlier decision.

## Engagement coverage

Each engagement_coverage record identifies:
- Source system.
- Covered event types.
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
- Originating decision or review action.
- Assignment reason.

## SLA history

sla_tracking stores the current first-follow-up obligation.

sla_history preserves:
- Initial priority, allowance and deadline.
- Priority upgrades and resulting deadline changes.
- Owner changes relevant to the audit.
- Recorded breaches.
- Qualifying follow-up and completion.
- Corrections, including late-arriving activity evidence.

Reassignment and duplicate submissions do not create another first-follow-up obligation.

Priority downgrades do not extend the deadline.

Preserve both activity occurrence time and recording time. If late-arriving evidence changes the assessed outcome, retain the earlier assessment and correction history.

## Participant redirects

Participant enquiries are recorded through ingestion_events and participant_redirects without requiring a sales lead.

supplier_redirect_rules contains country-specific destinations and an optional default destination.

Each attempt records the destination actually selected so configuration changes do not rewrite history.

If no usable destination exists, record a redirect exception for review.

Redirects are simulated in the MVP. Submitted personal data is not transferred to the supplier.

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

Primary keys, foreign keys, uniqueness constraints and PostgreSQL data types will be defined in the next step.
