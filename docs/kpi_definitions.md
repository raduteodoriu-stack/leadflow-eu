# KPI definitions (LF-011)

The KPIs kept in the LF-011 decision sheet (2026-10-29), each defined once. The
reporting layer (`reporting/`, dbt) computes every one of them from the facts in the same
way, and `reporting.kpi_summary` holds one row per KPI value. Power BI (LF-012) uses the
same facts and definitions.

**Conventions**

- **Working time:** Monday to Friday, 09:00–18:00, Europe/Madrid, no public holidays
  (holidays come with LF-014). Measured with the database function `working_minutes(a, b)`,
  which gives the same result as the engine (tested on 3,000 pairs of moments).
- **As of:** every number describes one moment, the dbt variable `as_of` (default: the
  LF-005 cut-off, Friday 6 November 2026 18:00). Ages, waits and "at risk" are measured to
  it. SLA and target statuses are the engine's, so the database must have been processed up
  to that moment.
- **Enquiry** = a stored inbound event (repeats of the same event are never stored).
  **New lead** = a new contact created by an enquiry.
- **Ratios** show numerator and denominator, so a percentage is never shown without its base.
- **LF-005 value** is the result on the synthetic dataset, checked against the answer key
  by the dbt test `kpi_summary_matches_expected`.

## Headline (first dashboard page)

| # | KPI | Definition | LF-005 value | Who acts, and how |
|---|---|---|---|---|
| 20 | SLA attainment | Leads followed up within 8 working hours ÷ leads whose SLA is decided (met + breached). Still-open SLAs are excluded until decided | 58 ÷ 63 = 92.1% | Sales Manager: coaching by salesperson, urgency and country |
| 23 | Response-target hit rate | Leads first followed up within their priority target (P1 1 h, P2 4 h, P3 8 h) ÷ leads whose target is decided (met + missed) | 44 ÷ 65 = 67.7% | Sales Manager: are urgent leads answered at the speed they need? |
| 10 | Leads waiting for an owner | New leads with no owner yet (in review), with the longest wait in working minutes | 9 leads; longest wait 10,488 working minutes (19.4 working days) | Sales Manager and RevOps: clear the queue |
| 9 | Auto-assignment rate | New leads given an owner automatically by the decision on the enquiry that created them (round-robin or same-company owner) ÷ new leads | 67 ÷ 76 = 88.2% | RevOps: a drop means rules or data need fixing |
| 22 | At-risk leads | Open SLAs due within the next 2 working hours (120 working minutes, variable `at_risk_working_minutes`) | 1 | Salespeople and Sales Manager: the list to act on today |

## Detail (drill-down pages)

| # | KPI | Definition | LF-005 value | Who acts, and how |
|---|---|---|---|---|
| 1 | Enquiries received | Stored enquiries, by ISO week of arrival (Madrid) | 97 | Sales Manager: plans capacity |
| 2 | New leads | Leads created, by ISO week | 76 | Sales Manager: context for every rate |
| 3 | Leads by country | New leads by business country; no usable country = `unknown` | ES 28, PT 21, FR 19, unknown 5, DE/GB/IT 1 each | Sales Manager: balances territories |
| 4 | Leads by source | New leads by the channel of the enquiry that created them | web form 35, event 12, outbound 12, referral 7, partner 6, unknown 4 | Marketing: where to invest |
| 5 | Rejected enquiries % | Enquiries rejected (could not be identified) ÷ enquiries | 3 ÷ 97 = 3.1% | RevOps: fixes the form or integration |
| 7 | Incomplete data % | New leads whose company data was incomplete or whose interest was unknown when created ÷ new leads | 24 ÷ 76 = 31.6% | RevOps and Marketing: improve form questions |
| 12 | Leads per salesperson | Leads by first owner, per week | ES-01 12, ES-02 16, PT-01 10, PT-02 10, FR-01 14, FR-02 5 | Sales Manager: rotation fairness, overload |
| 16 | Urgency mix | Assigned leads by priority when assigned ÷ assigned leads | P1 12, P2 36, P3 19 of 67 | Sales Manager: a P1 spike needs more hands |
| 17 | Why leads were urgent | New leads by the LF-002 rule that set their priority | rule 2: 10, 3: 7, 4: 6, 5: 15, 6: 18, 7: 20 | Marketing and Sales Manager: which signals drive urgency |
| 21 | SLA breaches | Leads whose SLA was breached, with the list | 5 | Sales Manager: follows up each one |
| 24 | Promise kept, target missed | Leads followed up within 8 working hours but slower than their priority target | 14 | Sales Manager: the coaching gap the SLA alone hides |
| 25 | Time to first follow-up | Median working minutes from assignment to the first qualifying follow-up, by priority when assigned | P1 126, P2 138, P3 348 | Sales Manager: speed trend per salesperson |
| 26 | Late-logged follow-ups | Follow-ups made on time but logged after the deadline (`LATE_LOGGED_FOLLOWUP` cases) | 0 | Sales Manager: makes back-dating visible |
| 28 | Review backlog | Open review cases, by reason and by who must act, with their age | 25 (RevOps 13, Sales Manager 12) | Sales Manager and RevOps: clear their own queue |
| 29 | Backlog over time | Open review cases at the end of each working day (18:00 Madrid), rebuilt from opening and resolution times | 1 case on 12 Oct, 25 by 5 Nov | Sales Manager: is the queue growing or shrinking? |
| 30 | Absence alerts | `OWNER_UNAVAILABLE_PENDING` cases, and how fast they were resolved | 0 | Sales Manager: cover planning |
| 31 | CRM in sync | CRM contacts showing exactly what LeadFlow decided ÷ contacts (same rule as reconciliation check C19) | 76 ÷ 76 = 100% | RevOps: below 100% means updates are waiting or failed |
| 32 | CRM update failures | Intended CRM updates waiting to retry, given up (sent to RevOps) or not yet confirmed | 0 | RevOps: fix the cause |
| 33 | Reconciliation status | Checks balanced ÷ checks run, in the latest reconciliation run | 28 ÷ 28 | RevOps: any difference is investigated before numbers are shared |

## Later and dropped

| # | KPI | Decision | Why |
|---|---|---|---|
| 11 | Time to assignment | Later | No review is ever completed in the test data, so it would be empty. The column `fact_lead.time_to_assignment_working_minutes` is already there |
| 19 | Urgency changes | Later | One case in the test data |
| 6, 8, 13, 14, 15, 18, 27 | Repeats ignored, participants redirected, rotation skips, same-company assignments, returning contacts, fit and interest bands, follow-up mix | Dropped | Nobody would act differently because of them, or another KPI already covers them |

Deliberately left out: conversion, pipeline value, revenue and win rate (LeadFlow's data
stops at the first follow-up, and the data is invented), cost per lead and CAC (needs spend
and salary data), lead-score accuracy (needs real outcomes), and salesperson league tables
(rankings without context mislead; per-salesperson numbers stay in the detail pages).
