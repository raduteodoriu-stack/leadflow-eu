# LeadFlow EU — Data Dictionary

Input fields, controlled values, validation rules and calculated outputs for the LeadFlow EU MVP.

Business rules are defined in LF-002.

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

| Field | Type | Required? | Definition |
|---|---|---|---|
| source_system | Controlled text | Yes | Origin of the record: synthetic_fixture or hubspot |
| source_event_id | Text | Yes | Stable identifier for this event or source-record version |
| source_record_id | Text | When available | Identifier of the contact or submission in the source |
| event_type | Controlled text | Yes | lead_created or lead_updated |
| source_occurred_at | Timestamp with timezone | Yes for processing | When the submission or source change occurred |
| received_at | Timestamp with timezone | Yes; system-generated | When LeadFlow received the event |
| source_channel | Controlled text | No | web_form, event, referral, outbound, partner or unknown |
| raw_payload | JSON object | Yes | Original submitted data, preserved before transformation |

The combination of source_system and source_event_id identifies a unique event.

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

A survey_participation_request triggers an automatic redirect to the designated sample supplier. Record the redirect destination, timestamp and outcome. Exclude the enquiry from sales assignment, scoring and buyer SLA metrics.

For the MVP, simulate the redirect. A redirect sends the person to the supplier’s participation page; it does not transfer their submitted personal data.

## 4. Company-fit inputs

These fields support scoring. Missing values do not block country-based assignment.

| Field | Type | Allowed values or meaning |
|---|---|---|
| employee_count | Integer | Exact employee count, if known; must be at least 1 |
| employee_band_declared | Controlled text | 1–10, 11–49, 50–249, 250–999, 1000_plus or unknown |
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

Store evidence for each fit input used in scoring.

| Field | Type | Definition |
|---|---|---|
| field_name | Text | Qualification field supported by the evidence |
| evidence_source | Controlled text | form_submission, crm_record, manual_review or synthetic_fixture |
| source_reference | Text | Event, record or fixture identifier |
| observed_at | Timestamp with timezone | When the information was obtained |
| recorded_by | Text | System or reviewer identifier |
| evidence_note | Text | Optional explanation supporting the classification |

Original evidence must remain available when values are corrected.

## 7. Engagement-event inputs

Engagement is supplied as individual events, not a manually entered total score.

| Field | Type | Required? | Definition |
|---|---|---|---|
| source_system | Controlled text | Yes | System providing the event |
| source_event_id | Text | Yes | Stable engagement-event identifier |
| source_contact_id | Text | If available | Source contact identifier |
| contact_email | Text | If no source contact ID | Contact identity used to resolve the event |
| event_type | Controlled text | Yes | Prospect action |
| occurred_at | Timestamp with timezone | Yes | When the action happened |
| received_at | Timestamp with timezone | Yes; system-generated | When the event was ingested |
| asset_id | Text | When relevant | Page, webinar or content identifier |
| related_submission_id | Text | When relevant | Links a request event to its enquiry submission |

Scored engagement_event_type values:
- demo_request
- sales_contact_request
- sample_quote_request
- pricing_page_visit
- product_webinar_attended
- case_study_download
- product_guide_download

Rules:
- Link each event to one canonical lead.
- Preserve unresolved events for review.
- One request must not score twice because it appears in both a form submission and an activity extract.
- Apply the caps and 30-day window defined in LF-002.
- Webinar registration alone does not count as attendance.
- Future-dated events do not contribute until valid for the assessment time.

## 8. Engagement-data availability

Store data-availability metadata separately from engagement events.

| Field | Type | Definition |
|---|---|---|
| coverage_start_at | Timestamp with timezone | Start of the period covered by the extract |
| coverage_end_at | Timestamp with timezone | End of the covered period |
| extraction_status | Controlled text | complete, partial or failed |
| last_successful_extract_at | Timestamp with timezone | Last successful extraction |

A zero engagement score requires complete coverage of the relevant assessment window.

Partial or failed coverage produces an unknown engagement status.

Known explicit sales requests can still trigger P1 according to LF-002, even if other engagement sources are incomplete.

## 9. Representative and assignment-reference inputs

These are maintained by the simulated sales organisation.

| Field | Type | Definition |
|---|---|---|
| owner_id | Text | Internal representative identifier |
| crm_owner_id | Text | Corresponding CRM owner identifier, when available |
| country_code | Controlled text | ES, PT or FR |
| active | Boolean | Whether the representative can receive new assignments |
| manager_id | Text | Sales Manager responsible for fallback decisions |
| effective_at | Timestamp with timezone | When an owner-status or territory change takes effect |

Initial representatives:
- ES-01 and ES-02.
- PT-01 and PT-02.
- FR-01 and FR-02.

Preserve status changes so historical assignments can be explained.

Round-robin position is system-managed state, not a source input.

## 10. Follow-up activity inputs

Follow-up activities are separate from prospect engagement.

| Field | Type | Required? | Definition |
|---|---|---|---|
| source_system | Controlled text | Yes | Origin of the activity |
| source_activity_id | Text | Yes | Stable activity identifier |
| source_contact_id or contact_email | Text | Yes | Identity needed to associate the activity |
| performed_by_owner_id | Text | Yes for qualifying follow-up | Representative who performed the activity |
| activity_type | Controlled text | Yes | Type of sales activity |
| occurred_at | Timestamp with timezone | Yes | When the activity occurred |
| recorded_at | Timestamp with timezone | Yes | When it was recorded |
| outcome | Controlled text | Yes for qualification | What happened |
| is_automated | Boolean | Yes | Whether it was performed automatically |

Activity types:
- call_attempt
- individual_sales_email
- meeting_invitation
- automated_email
- internal_note
- task_created

Example outcomes:
- connected
- no_answer
- voicemail
- invalid_number
- sent
- draft
- failed

Apply LF-001’s qualifying-follow-up definition.

Use occurred_at to evaluate timeliness; retain recorded_at to identify late logging.

A draft, failed send, automated message or administrative activity does not satisfy the first-follow-up SLA.

A meeting invitation counts only when it represents an individual outreach message actually sent to the lead.

## 11. Manual review and override inputs

| Field | Type | Definition |
|---|---|---|
| review_case_id | Text | Case being resolved |
| action_type | Controlled text | correct_data, confirm_identity, assign_owner, reassign_owner, classify_relationship or exclude_non_sales |
| actor_id | Text | Reviewer making the decision |
| action_at | Timestamp with timezone | When the action occurred |
| reason_code | Text | Structured reason |
| reason_note | Text | Explanation |
| corrected_values | JSON object | Proposed field corrections or new owner |

The system retrieves and preserves previous values. Reviewers must not overwrite the original history.

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
