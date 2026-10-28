# LF-004 Test scenarios

Generated from `tests/fixtures/scenarios/*.json` by `tools/scenario_summary.py`. Do not edit by hand: change the JSON and rerun the script.

Times are Europe/Madrid. Expected outcomes are hand-labelled from LF-001, LF-002 and the 2026-10-23 rule clarifications (rule version LF-RULES-v1.0).

SLA: one deadline of 8 business hours for every assigned lead (breach if missed). Response target: P1 1 h, P2 4 h, P3 8 h, measured for reporting but never a breach.

T- scenarios (LF-009) replay a timeline of steps (follow-ups with the time they were logged, checks, absences, reassignments) against one prior state; decisions of 2026-10-28.

## Scenarios (32)

| ID | Scenario | Evaluated | Outcome | Owner / queue | Priority | Response target | SLA deadline (8 h) | Reason codes | Reviewed |
|---|---|---|---|---|---|---|---|---|---|
| S-01 | Spanish buyer requests a demo; complete high fit | Tue 03 Nov 10:00 | assigned | ES-01 | P1 (rule 2) | Tue 03 Nov 11:00 | Tue 03 Nov 18:00 | PRIORITY_EXPLICIT_REQUEST | yes |
| S-02 | Portuguese buyer with complete high fit and high engagement, no explicit request | Tue 03 Nov 10:00 | assigned | PT-02 | P1 (rule 3) | Tue 03 Nov 11:00 | Tue 03 Nov 18:00 | PRIORITY_HIGH_FIT_HIGH_ENGAGEMENT | yes |
| S-03 | French buyer with high engagement but complete low fit | Tue 03 Nov 10:00 | assigned | FR-01 | P2 (rule 4) | Tue 03 Nov 14:00 | Tue 03 Nov 18:00 | PRIORITY_HIGH_ENGAGEMENT | yes |
| S-04 | Spanish buyer with complete high fit and low engagement | Tue 03 Nov 10:00 | assigned | ES-02 | P2 (rule 5) | Tue 03 Nov 14:00 | Tue 03 Nov 18:00 | PRIORITY_STANDARD_FIT | yes |
| S-05 | Spanish buyer with missing company size and readiness | Tue 03 Nov 10:00 | assigned | ES-01 | P2 (rule 6) | Tue 03 Nov 14:00 | Tue 03 Nov 18:00 | PRIORITY_MISSING_INFO, FIT_INCOMPLETE | yes |
| S-06 | French buyer whose engagement extraction failed | Tue 03 Nov 10:00 | assigned | FR-02 | P2 (rule 6) | Tue 03 Nov 14:00 | Tue 03 Nov 18:00 | PRIORITY_MISSING_INFO, ENGAGEMENT_UNKNOWN | yes |
| S-07 | Portuguese buyer with complete low fit and no engagement | Tue 03 Nov 10:00 | assigned | PT-01 | P3 (rule 7) | Tue 03 Nov 18:00 | Tue 03 Nov 18:00 | PRIORITY_DEFAULT | yes |
| S-08 | Supplier-only enquiry from Spain, handled like a buyer | Tue 03 Nov 10:00 | assigned | ES-01 + SUPPLIER_REVIEW | P2 (rule 6) | Tue 03 Nov 14:00 | Tue 03 Nov 18:00 | SUPPLIER_REVIEW, PRIORITY_MISSING_INFO, FIT_INCOMPLETE | yes |
| S-09 | Paid-survey participant enquiry from Spain | Tue 03 Nov 10:00 | redirected | — | — | — | — | PARTICIPANT_REDIRECT | yes |
| S-10 | Returning contact with different email case and spaces | Tue 03 Nov 10:00 | existing_owner_kept | ES-01 | P3 (rule 7) | — | no new SLA | EXISTING_CONTACT, PRIORITY_DEFAULT | yes |
| S-11 | New email but CRM contact ID belongs to an existing, followed-up contact | Tue 03 Nov 10:00 | attached_to_existing_contact | FR-01 + IDENTITY_REVIEW | P2 (rule 6) | — | no new SLA | IDENTITY_REVIEW, PRIORITY_MISSING_INFO, FIT_INCOMPLETE | yes |
| S-12 | Demo request with no business country | Tue 03 Nov 10:00 | review | unassigned_review | P1 (rule 2) | — | — | COUNTRY_INVALID, PRIORITY_EXPLICIT_REQUEST | yes |
| S-13 | Buyer from Germany (outside ES, PT, FR) | Tue 03 Nov 10:00 | review | unassigned_review | P2 (rule 5) | — | — | UNSUPPORTED_TERRITORY, PRIORITY_STANDARD_FIT | yes |
| S-14 | Event with no source event ID | Tue 03 Nov 10:00 | rejected | unassigned_review | — | — | — | SOURCE_EVENT_INVALID | yes |
| S-15 | Existing P3 lead requests a demo before first follow-up | Tue 03 Nov 11:00 | existing_owner_kept | PT-02 | P1 (rule 2) | Tue 03 Nov 12:00 | Tue 03 Nov 17:00 | DUPLICATE_EVENT_RECONTACT, PRIORITY_EXPLICIT_REQUEST | yes |
| S-16 | New Spanish lead when rotation is at ES-02 | Tue 03 Nov 10:00 | assigned | ES-02 | P3 (rule 7) | Tue 03 Nov 18:00 | Tue 03 Nov 18:00 | PRIORITY_DEFAULT | yes |
| S-17 | Same source event delivered again 30 minutes later | Tue 03 Nov 10:30 | duplicate_event_ignored | ES-01 | P1 (rule 2) | Tue 03 Nov 11:00 | Tue 03 Nov 18:00 | DUPLICATE_EVENT_RECONTACT | yes |
| S-18 | Demo request arrives Friday at 17:55 | Fri 06 Nov 17:55 | assigned | ES-01 | P1 (rule 2) | Mon 09 Nov 09:55 | Mon 09 Nov 16:55 | PRIORITY_EXPLICIT_REQUEST | yes |
| S-19 | Standard lead arrives on Saturday | Sat 07 Nov 11:00 | assigned | FR-01 | P2 (rule 5) | Mon 09 Nov 13:00 | Mon 09 Nov 17:00 | PRIORITY_STANDARD_FIT | yes |
| S-20 | Two pricing visits on the same Madrid day | Tue 03 Nov 10:00 | assigned | PT-01 | P3 (rule 7) | Tue 03 Nov 18:00 | Tue 03 Nov 18:00 | PRIORITY_DEFAULT | yes |
| S-21 | Same person contacts again 2 business hours after first contact | Tue 03 Nov 11:00 | existing_owner_kept | PT-01 | P2 (rule 5) | Tue 03 Nov 13:00 | Tue 03 Nov 17:00 | DUPLICATE_EVENT_RECONTACT, PRIORITY_STANDARD_FIT | yes |
| S-22 | Colleague from the same company contacts 2 business hours later | Tue 03 Nov 11:00 | assigned_to_company_owner | PT-02 | P2 (rule 5) | Tue 03 Nov 15:00 | Wed 04 Nov 10:00 | SAME_COMPANY_RECENT_CONTACT, PRIORITY_STANDARD_FIT | yes |
| S-23 | Two different business countries supplied | Tue 03 Nov 10:00 | review | unassigned_review | P2 (rule 5) | — | — | COUNTRY_CONFLICT, PRIORITY_STANDARD_FIT | yes |
| S-24 | Demo request with an invalid email address | Tue 03 Nov 10:00 | review | unassigned_review | P1 (rule 2) | — | — | EMAIL_INVALID, PRIORITY_EXPLICIT_REQUEST | yes |
| S-25 | Portuguese lead when no Portuguese rep is active | Tue 03 Nov 10:00 | review | unassigned_review | P2 (rule 5) | — | — | NO_ELIGIBLE_OWNER, PRIORITY_STANDARD_FIT | yes |
| S-26 | Existing lead whose owner has become inactive | Tue 03 Nov 10:00 | review | FR-02 | P2 (rule 5) | — | no new SLA | EXISTING_CONTACT, OWNER_REVIEW, PRIORITY_STANDARD_FIT | yes |
| S-27 | Valid lead with no company domain | Tue 03 Nov 10:00 | assigned | ES-01 | P2 (rule 5) | Tue 03 Nov 14:00 | Tue 03 Nov 18:00 | DOMAIN_MISSING, PRIORITY_STANDARD_FIT | yes |
| S-28 | Relationship unknown, low fit and low engagement | Tue 03 Nov 10:00 | assigned | FR-01 | P2 (rule 6) | Tue 03 Nov 14:00 | Tue 03 Nov 18:00 | RELATIONSHIP_UNKNOWN, PRIORITY_MISSING_INFO | yes |
| S-29 | Paid-survey participant from a country with no redirect rule | Tue 03 Nov 10:00 | review | participant_redirect_review | — | — | — | NO_REDIRECT_RULE | yes |
| S-30 | Enquiry with both buying and supply needs | Tue 03 Nov 10:00 | assigned | ES-02 + SUPPLIER_REVIEW | P2 (rule 5) | Tue 03 Nov 14:00 | Tue 03 Nov 18:00 | SUPPLIER_REVIEW, PRIORITY_STANDARD_FIT | yes |
| S-31 | Next Spanish rep in rotation is inactive | Tue 03 Nov 10:00 | assigned | ES-02 | P3 (rule 7) | Tue 03 Nov 18:00 | Tue 03 Nov 18:00 | PRIORITY_DEFAULT | yes |
| S-32 | Already followed-up contact sends a new demo request | Tue 03 Nov 10:00 | existing_owner_kept | PT-01 | P1 (rule 2) | — | no new SLA | EXISTING_CONTACT, PRIORITY_EXPLICIT_REQUEST | yes |

## Boundary tests (17)

| ID | Scenario | Evaluated | Outcome | Owner / queue | Priority | Response target | SLA deadline (8 h) | Reason codes | Reviewed |
|---|---|---|---|---|---|---|---|---|---|
| B-01 | Fit 65 (top of medium) with low engagement | Tue 03 Nov 10:00 | assigned | ES-01 | P3 (rule 7) | Tue 03 Nov 18:00 | Tue 03 Nov 18:00 | PRIORITY_DEFAULT | yes |
| B-02 | Fit 70 (bottom of high) with low engagement | Tue 03 Nov 10:00 | assigned | ES-01 | P2 (rule 5) | Tue 03 Nov 14:00 | Tue 03 Nov 18:00 | PRIORITY_STANDARD_FIT | yes |
| B-03 | Engagement 10 (top of low) with complete medium fit | Tue 03 Nov 10:00 | assigned | ES-01 | P3 (rule 7) | Tue 03 Nov 18:00 | Tue 03 Nov 18:00 | PRIORITY_DEFAULT | yes |
| B-04 | Engagement 15 (bottom of medium) with complete medium fit | Tue 03 Nov 10:00 | assigned | ES-01 | P2 (rule 5) | Tue 03 Nov 14:00 | Tue 03 Nov 18:00 | PRIORITY_STANDARD_FIT | yes |
| B-05 | Engagement 35 (top of medium) with complete low fit | Tue 03 Nov 10:00 | assigned | ES-01 | P3 (rule 7) | Tue 03 Nov 18:00 | Tue 03 Nov 18:00 | PRIORITY_DEFAULT | yes |
| B-06 | Engagement 40 (bottom of high) with complete low fit | Tue 03 Nov 10:00 | assigned | ES-01 | P2 (rule 4) | Tue 03 Nov 14:00 | Tue 03 Nov 18:00 | PRIORITY_HIGH_ENGAGEMENT | yes |
| B-07 | Webinar exactly 30 x 24 hours before evaluation (included) | Tue 03 Nov 10:00 | assigned | ES-01 | P2 (rule 5) | Tue 03 Nov 14:00 | Tue 03 Nov 18:00 | PRIORITY_STANDARD_FIT | yes |
| B-08 | Webinar one minute before the 30-day edge (excluded) | Tue 03 Nov 10:00 | assigned | ES-01 | P3 (rule 7) | Tue 03 Nov 18:00 | Tue 03 Nov 18:00 | PRIORITY_DEFAULT | yes |
| B-09 | P2 assigned Friday 16:00 before the clock-change weekend | Fri 23 Oct 16:00 | assigned | ES-01 | P2 (rule 5) | Mon 26 Oct 11:00 | Mon 26 Oct 15:00 | PRIORITY_STANDARD_FIT | yes |
| B-10 | P1 assigned at exactly 18:00 | Tue 03 Nov 18:00 | assigned | ES-01 | P1 (rule 2) | Wed 04 Nov 10:00 | Wed 04 Nov 17:00 | PRIORITY_EXPLICIT_REQUEST | yes |
| B-11 | P1 assigned at 08:30, before working hours | Tue 03 Nov 08:30 | assigned | ES-01 | P1 (rule 2) | Tue 03 Nov 10:00 | Tue 03 Nov 17:00 | PRIORITY_EXPLICIT_REQUEST | yes |
| B-12 | Automated email does not count; call at 10:30 misses the P1 target but meets the SLA | Tue 03 Nov 10:31 | SLA met, target missed | follow-up Tue 03 Nov 10:30 | — | Tue 03 Nov 10:00 | — | — | yes |
| B-13 | Call exactly at the P1 target time meets the target | Tue 03 Nov 10:01 | SLA met, target met | follow-up Tue 03 Nov 10:00 | — | Tue 03 Nov 10:00 | — | — | yes |
| B-14 | Same person again after 7 h 59 business minutes (recontact) | Mon 02 Nov 17:59 | existing_owner_kept | ES-02 | P3 (rule 7) | — | no new SLA | DUPLICATE_EVENT_RECONTACT, PRIORITY_DEFAULT | yes |
| B-15 | Same person again after 8 h 30 business minutes (not a recontact) | Tue 03 Nov 09:30 | existing_owner_kept | ES-02 | P3 (rule 7) | — | no new SLA | EXISTING_CONTACT, PRIORITY_DEFAULT | yes |
| B-16 | No follow-up within 8 business hours; late call cannot erase the breach | Tue 03 Nov 17:31 | SLA breached, target missed | follow-up Tue 03 Nov 17:30 | — | Tue 03 Nov 10:00 | — | — | yes |
| B-17 | Call exactly at the SLA deadline meets the SLA | Tue 03 Nov 17:01 | SLA met, target missed | follow-up Tue 03 Nov 17:00 | — | Tue 03 Nov 10:00 | — | — | yes |

## SLA tracking and alerts (LF-009) (20)

| ID | Scenario | Evaluated | Outcome | Owner / queue | Priority | Response target | SLA deadline (8 h) | Reason codes | Reviewed |
|---|---|---|---|---|---|---|---|---|---|
| T-01 | Nothing done yet, before the target: SLA and target both pending | Mon 09 Nov 17:00 | SLA pending, target pending | ES-01 | P2 (rule None) | Mon 09 Nov 18:00 | Tue 10 Nov 13:00 | — | yes |
| T-02 | Target passed with no follow-up: target missed, SLA still pending | Tue 10 Nov 09:30 | SLA pending, target missed | ES-01 | P2 (rule None) | Mon 09 Nov 18:00 | Tue 10 Nov 13:00 | — | yes |
| T-03 | Evaluated exactly at the SLA deadline with no follow-up: still pending | Tue 10 Nov 13:00 | SLA pending, target missed | ES-01 | P2 (rule None) | Mon 09 Nov 18:00 | Tue 10 Nov 13:00 | — | yes |
| T-04 | One minute after the deadline with no follow-up: breached | Tue 10 Nov 13:01 | SLA breached, target missed | ES-01 | P2 (rule None) | Mon 09 Nov 18:00 | Tue 10 Nov 13:00 | — | yes |
| T-05 | Checking twice at the same moment records the breach once | Tue 10 Nov 13:01 | SLA breached, target missed | ES-01 | P2 (rule None) | Mon 09 Nov 18:00 | Tue 10 Nov 13:00 | — | yes |
| T-06 | A call by a colleague does not count for the owner's lead | Tue 10 Nov 13:01 | SLA breached, target missed | ES-01 | P2 (rule None) | Mon 09 Nov 18:00 | Tue 10 Nov 13:00 | — | yes |
| T-07 | Owner calls before the deadline: SLA met, target missed | Tue 10 Nov 11:00 | SLA met, target missed | ES-01, follow-up Tue 10 Nov 11:00 | P2 (rule None) | Mon 09 Nov 18:00 | Tue 10 Nov 13:00 | — | yes |
| T-08 | Call made on time but logged after the deadline: corrected to met and flagged | Tue 10 Nov 14:30 | SLA met, target missed | ES-01, follow-up Tue 10 Nov 12:50 + 1 LATE_LOGGED_FOLLOWUP | P2 (rule None) | Mon 09 Nov 18:00 | Tue 10 Nov 13:00 | — | yes |
| T-09 | Call logged late and made after the deadline: breach stays, nothing flagged | Tue 10 Nov 14:30 | SLA breached, target missed | ES-01, follow-up Tue 10 Nov 13:30 | P2 (rule None) | Mon 09 Nov 18:00 | Tue 10 Nov 13:00 | — | yes |
| T-10 | Call logged late but before the deadline: met, no flag | Tue 10 Nov 12:30 | SLA met, target missed | ES-01, follow-up Tue 10 Nov 11:00 | P2 (rule None) | Mon 09 Nov 18:00 | Tue 10 Nov 13:00 | — | yes |
| T-11 | Owner's absence starts while a lead is pending: Sales Manager alerted, colleague suggested | Tue 10 Nov 09:00 | SLA pending, target missed | ES-01 + 1 OWNER_UNAVAILABLE_PENDING | P2 (rule None) | Mon 09 Nov 18:00 | Tue 10 Nov 13:00 | — | yes |
| T-12 | Absence starts after the lead was already followed up: no alert | Tue 10 Nov 09:00 | SLA met, target met | ES-01, follow-up Mon 09 Nov 16:00 | P2 (rule None) | Mon 09 Nov 18:00 | Tue 10 Nov 13:00 | — | yes |
| T-13 | Absence recorded after it started: alert when it is recorded | Tue 10 Nov 10:31 | SLA pending, target missed | ES-01 + 1 OWNER_UNAVAILABLE_PENDING | P2 (rule None) | Mon 09 Nov 18:00 | Tue 10 Nov 13:00 | — | yes |
| T-14 | Absence recorded after the deadline passed: no alert, the breach stands | Tue 10 Nov 14:00 | SLA breached, target missed | ES-01 | P2 (rule None) | Mon 09 Nov 18:00 | Tue 10 Nov 13:00 | — | yes |
| T-15 | Next salesperson is away too: alert with no suggestion | Tue 10 Nov 09:00 | SLA pending, target missed | ES-01 + 1 OWNER_UNAVAILABLE_PENDING | P2 (rule None) | Mon 09 Nov 18:00 | Tue 10 Nov 13:00 | — | yes |
| T-16 | Reassigned to a colleague: original deadline kept, new owner calls in time | Tue 10 Nov 12:00 | SLA met, target missed | ES-02, follow-up Tue 10 Nov 12:00 + 1 OWNER_UNAVAILABLE_PENDING | P2 (rule None) | Mon 09 Nov 18:00 | Tue 10 Nov 13:00 | — | yes |
| T-17 | Reassigned, but the new owner calls after the original deadline: breached | Tue 10 Nov 15:00 | SLA breached, target missed | ES-02, follow-up Tue 10 Nov 15:00 + 1 OWNER_UNAVAILABLE_PENDING | P2 (rule None) | Mon 09 Nov 18:00 | Tue 10 Nov 13:00 | — | yes |
| T-18 | After reassignment, the previous owner's call no longer counts | Tue 10 Nov 13:01 | SLA breached, target missed | ES-02 | P2 (rule None) | Mon 09 Nov 18:00 | Tue 10 Nov 13:00 | — | yes |
| T-19 | Salesperson leaves the team (no end date): one alert per pending lead | Tue 10 Nov 09:00 | SLA pending, target pending | FR-02 + 2 OWNER_UNAVAILABLE_PENDING | P3 (rule None) | Tue 10 Nov 13:00 | Tue 10 Nov 13:00 | — | yes |
| T-20 | Call made by the owner before a reassignment but logged after it still counts | Tue 10 Nov 10:00 | SLA met, target met | ES-02, follow-up Mon 09 Nov 17:00 | P2 (rule None) | Mon 09 Nov 18:00 | Tue 10 Nov 13:00 | — | yes |

**Review status:** 69 of 69 labels independently reviewed.
