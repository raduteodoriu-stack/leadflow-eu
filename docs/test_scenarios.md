# LF-004 Test scenarios

Generated from `tests/fixtures/scenarios/*.json` by `tools/scenario_summary.py`. Do not edit by hand: change the JSON and rerun the script.

Times are Europe/Madrid. Expected outcomes are hand-labelled from LF-001, LF-002 and the 2026-10-23 rule clarifications (rule version LF-RULES-v1.0).

## Scenarios (22)

| ID | Scenario | Evaluated | Outcome | Owner / queue | Priority | SLA deadline | Reason codes | Reviewed |
|---|---|---|---|---|---|---|---|---|
| S-01 | Spanish buyer requests a demo; complete high fit | Tue 03 Nov 10:00 | assigned | ES-01 | P1 (rule 2) | Tue 03 Nov 11:00 | PRIORITY_EXPLICIT_REQUEST | no |
| S-02 | Portuguese buyer with complete high fit and high engagement, no explicit request | Tue 03 Nov 10:00 | assigned | PT-02 | P1 (rule 3) | Tue 03 Nov 11:00 | PRIORITY_HIGH_FIT_HIGH_ENGAGEMENT | no |
| S-03 | French buyer with high engagement but complete low fit | Tue 03 Nov 10:00 | assigned | FR-01 | P2 (rule 4) | Tue 03 Nov 14:00 | PRIORITY_HIGH_ENGAGEMENT | no |
| S-04 | Spanish buyer with complete high fit and low engagement | Tue 03 Nov 10:00 | assigned | ES-02 | P2 (rule 5) | Tue 03 Nov 14:00 | PRIORITY_STANDARD_FIT | no |
| S-05 | Spanish buyer with missing company size and readiness | Tue 03 Nov 10:00 | assigned | ES-01 | P2 (rule 6) | Tue 03 Nov 14:00 | PRIORITY_MISSING_INFO, FIT_INCOMPLETE | no |
| S-06 | French buyer whose engagement extraction failed | Tue 03 Nov 10:00 | assigned | FR-02 | P2 (rule 6) | Tue 03 Nov 14:00 | PRIORITY_MISSING_INFO, ENGAGEMENT_UNKNOWN | no |
| S-07 | Portuguese buyer with complete low fit and no engagement | Tue 03 Nov 10:00 | assigned | PT-01 | P3 (rule 7) | Tue 03 Nov 18:00 | PRIORITY_DEFAULT | no |
| S-08 | Supplier-only enquiry from Spain, handled like a buyer | Tue 03 Nov 10:00 | assigned | ES-01 + SUPPLIER_REVIEW | P2 (rule 6) | Tue 03 Nov 14:00 | SUPPLIER_REVIEW, PRIORITY_MISSING_INFO, FIT_INCOMPLETE | no |
| S-09 | Paid-survey participant enquiry from Spain | Tue 03 Nov 10:00 | redirected | — | — | — | PARTICIPANT_REDIRECT | no |
| S-10 | Returning contact with different email case and spaces | Tue 03 Nov 10:00 | existing_owner_kept | ES-01 | P3 (rule 7) | no new SLA | EXISTING_CONTACT, PRIORITY_DEFAULT | no |
| S-11 | New email but CRM contact ID belongs to an existing, followed-up contact | Tue 03 Nov 10:00 | attached_to_existing_contact | FR-01 + IDENTITY_REVIEW | P2 (rule 6) | no new SLA | IDENTITY_REVIEW, PRIORITY_MISSING_INFO, FIT_INCOMPLETE | no |
| S-12 | Demo request with no business country | Tue 03 Nov 10:00 | review | unassigned_review | P1 (rule 2) | — | COUNTRY_INVALID, PRIORITY_EXPLICIT_REQUEST | no |
| S-13 | Buyer from Germany (outside ES, PT, FR) | Tue 03 Nov 10:00 | review | unassigned_review | P2 (rule 5) | — | UNSUPPORTED_TERRITORY, PRIORITY_STANDARD_FIT | no |
| S-14 | Event with no source event ID | Tue 03 Nov 10:00 | rejected | unassigned_review | — | — | SOURCE_EVENT_INVALID | no |
| S-15 | Existing P3 lead requests a demo before first follow-up | Tue 03 Nov 11:00 | existing_owner_kept | PT-02 | P1 (rule 2) | Tue 03 Nov 12:00 | EXISTING_CONTACT, PRIORITY_EXPLICIT_REQUEST | no |
| S-16 | New Spanish lead when rotation is at ES-02 | Tue 03 Nov 10:00 | assigned | ES-02 | P3 (rule 7) | Tue 03 Nov 18:00 | PRIORITY_DEFAULT | no |
| S-17 | Same source event delivered again 30 minutes later | Tue 03 Nov 10:30 | duplicate_event_ignored | ES-01 | P1 (rule 2) | Tue 03 Nov 11:00 | DUPLICATE_EVENT_RECONTACT | no |
| S-18 | Demo request arrives Friday at 17:55 | Fri 06 Nov 17:55 | assigned | ES-01 | P1 (rule 2) | Mon 09 Nov 09:55 | PRIORITY_EXPLICIT_REQUEST | no |
| S-19 | Standard lead arrives on Saturday | Sat 07 Nov 11:00 | assigned | FR-01 | P2 (rule 5) | Mon 09 Nov 13:00 | PRIORITY_STANDARD_FIT | no |
| S-20 | Two pricing visits on the same Madrid day | Tue 03 Nov 10:00 | assigned | PT-01 | P3 (rule 7) | Tue 03 Nov 18:00 | PRIORITY_DEFAULT | no |
| S-21 | Same person contacts again 2 business hours after first contact | Tue 03 Nov 11:00 | existing_owner_kept | PT-01 | P2 (rule 5) | Tue 03 Nov 13:00 | DUPLICATE_EVENT_RECONTACT, PRIORITY_STANDARD_FIT | no |
| S-22 | Colleague from the same company contacts 2 business hours later | Tue 03 Nov 11:00 | assigned_to_company_owner | PT-02 | P2 (rule 5) | Tue 03 Nov 15:00 | SAME_COMPANY_RECENT_CONTACT, PRIORITY_STANDARD_FIT | no |

## Boundary tests (15)

| ID | Scenario | Evaluated | Outcome | Owner / queue | Priority | SLA deadline | Reason codes | Reviewed |
|---|---|---|---|---|---|---|---|---|
| B-01 | Fit 65 (top of medium) with low engagement | Tue 03 Nov 10:00 | assigned | ES-01 | P3 (rule 7) | Tue 03 Nov 18:00 | PRIORITY_DEFAULT | no |
| B-02 | Fit 70 (bottom of high) with low engagement | Tue 03 Nov 10:00 | assigned | ES-01 | P2 (rule 5) | Tue 03 Nov 14:00 | PRIORITY_STANDARD_FIT | no |
| B-03 | Engagement 10 (top of low) with complete medium fit | Tue 03 Nov 10:00 | assigned | ES-01 | P3 (rule 7) | Tue 03 Nov 18:00 | PRIORITY_DEFAULT | no |
| B-04 | Engagement 15 (bottom of medium) with complete medium fit | Tue 03 Nov 10:00 | assigned | ES-01 | P2 (rule 5) | Tue 03 Nov 14:00 | PRIORITY_STANDARD_FIT | no |
| B-05 | Engagement 35 (top of medium) with complete low fit | Tue 03 Nov 10:00 | assigned | ES-01 | P3 (rule 7) | Tue 03 Nov 18:00 | PRIORITY_DEFAULT | no |
| B-06 | Engagement 40 (bottom of high) with complete low fit | Tue 03 Nov 10:00 | assigned | ES-01 | P2 (rule 4) | Tue 03 Nov 14:00 | PRIORITY_HIGH_ENGAGEMENT | no |
| B-07 | Webinar exactly 30 x 24 hours before evaluation (included) | Tue 03 Nov 10:00 | assigned | ES-01 | P2 (rule 5) | Tue 03 Nov 14:00 | PRIORITY_STANDARD_FIT | no |
| B-08 | Webinar one minute before the 30-day edge (excluded) | Tue 03 Nov 10:00 | assigned | ES-01 | P3 (rule 7) | Tue 03 Nov 18:00 | PRIORITY_DEFAULT | no |
| B-09 | P2 assigned Friday 16:00 before the clock-change weekend | Fri 23 Oct 16:00 | assigned | ES-01 | P2 (rule 5) | Mon 26 Oct 11:00 | PRIORITY_STANDARD_FIT | no |
| B-10 | P1 assigned at exactly 18:00 | Tue 03 Nov 18:00 | assigned | ES-01 | P1 (rule 2) | Wed 04 Nov 10:00 | PRIORITY_EXPLICIT_REQUEST | no |
| B-11 | P1 assigned at 08:30, before working hours | Tue 03 Nov 08:30 | assigned | ES-01 | P1 (rule 2) | Tue 03 Nov 10:00 | PRIORITY_EXPLICIT_REQUEST | no |
| B-12 | Automated email does not stop the SLA; late call cannot erase the breach | Tue 03 Nov 10:31 | SLA breached | follow-up Tue 03 Nov 10:30 | — | — | — | no |
| B-13 | Call at exactly the deadline meets the SLA | Tue 03 Nov 10:01 | SLA met | follow-up Tue 03 Nov 10:00 | — | — | — | no |
| B-14 | Same person again after 7 h 59 business minutes (recontact) | Mon 02 Nov 17:59 | existing_owner_kept | ES-02 | P3 (rule 7) | no new SLA | DUPLICATE_EVENT_RECONTACT, PRIORITY_DEFAULT | no |
| B-15 | Same person again after 8 h 30 business minutes (not a recontact) | Tue 03 Nov 09:30 | existing_owner_kept | ES-02 | P3 (rule 7) | no new SLA | EXISTING_CONTACT, PRIORITY_DEFAULT | no |

**Review status:** 0 of 37 labels independently reviewed.
