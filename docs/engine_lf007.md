# LF-007 Routing and decision logging

Second half of the LeadFlow engine (LF-002 steps 6-9). It takes the prepared event from
LF-006, scores it, sets its priority, chooses an owner or queue, sets the SLA and response
target, and returns the decision. Rule version: `LF-RULES-v1.0`.

- **Phase A — decision logic:** pure Python, in memory.
- **Phase B — PostgreSQL:** every decision saved with its evidence, one transaction per event (see below).

## How to use

```python
from leadflow import ContactStore, load_rules
from leadflow.decide import process_event, record_activity

rules, store = load_rules(), ContactStore()
settings = {"representatives": {"ES": ["ES-01", "ES-02"], ...},
            "initial_rotation": {"ES": "ES-01", ...},
            "unavailability": [{"rep": "ES-01", "from": "...", "until": "..."}],
            "supplier_redirect_rules": {"ES": {...}}}
prepared, decision = process_event(raw_event, received_at, store, rules, settings)
record_activity(store, rules, {"lead_email": ..., "owner": ..., "type": "call", "automated": False,
                               "occurred_at": ...})
```

Process events and follow-up activities in time order (an activity at the same minute as an event goes first).

## What it decides

| Part | Module | Rule |
|---|---|---|
| Fit | `scoring.py` | Industry, size, need, readiness from the rules file; unknown components count 0 in the provisional total; band only when complete (high 70+, medium 40+) |
| Engagement | `scoring.py` | Events in exactly 30 x 24 h before the evaluation time, over the contact's whole history, repeated IDs once; request 60 (cap 60), pricing 10 per distinct Madrid day (cap 20), webinar 15 (cap 15), downloads 5 (cap 10), total cap 100; partial or failed data = unknown |
| Priority | `priority.py` | Rules 2-7 in order, one `PRIORITY_` code; shown even when the lead waits in review |
| Owner | `decide.py`, `routing.py` | Returning contact keeps its owner (owner unavailable → `OWNER_REVIEW`, Sales Manager); same-company colleague within 8 business hours → colleague's owner if available; otherwise round-robin among active reps in ID order, advancing only when someone is chosen; nobody available → `NO_ELIGIBLE_OWNER` |
| Queues | `decide.py` | Blocked → `unassigned_review` (RevOps for country/email/event problems, Sales Manager for territory/owner problems); participants without a redirect rule → `participant_redirect_review`; parallel `SUPPLIER_REVIEW` (Sales Manager) and `IDENTITY_REVIEW` (RevOps) |
| SLA and target | `decide.py` | At assignment: SLA 8 business hours; response target P1 1 h, P2 4 h, P3 8 h. Before first follow-up, a priority increase moves the target to the earlier of the current target and now + new allowance; the SLA never moves. Already followed up: no new SLA or target |
| Follow-ups | `decide.py` | `record_activity` keeps the first human call or individual email by the owner; automated emails do not count |

## Tests

| Test file | What it checks |
|---|---|
| `tests/engine/test_scoring.py` | Fit components and bands, unknown vs zero, readiness levels, engagement caps, distinct days, duplicates, 720-hour edge, unknown coverage, all priority rules |
| `tests/engine/test_routing.py` | Round-robin order, skipping inactive reps, no eligible owner, open-ended unavailability |
| `tests/test_lf007_acceptance.py` | Full decisions for all 45 inbound-event LF-004 scenarios and all 100 LF-005 events, plus every lead's owner, deadlines and priorities at the cut-off |

Sensitivity: changing a rule (fit band edge, window length, download cap, P2 target, SLA length, size points) makes the acceptance tests fail. The download cap is caught only by the LF-005 events, which is why both test sets are kept.

## Answer-key corrections made while building (2026-10-26)

Building the engine against both answer keys found two places where the LF-005 generator disagreed with a hand-reviewed LF-004 scenario. The reviewed scenario was followed and the generator corrected:

1. **Already followed-up returning contacts have no response target** (S-32): 7 LF-005 events changed (42, 53, 56, 59, 72, 88, 94), `response_target` only.
2. **A country conflict has no rotation pointer** (S-23): 2 LF-005 events changed (3, 18), `round_robin_next_after` only.

S-17's starting state now also records the priority rule of the earlier decision (rule 2), so a replay can repeat it; its expected outcome is unchanged.

## Phase B: saving decisions to PostgreSQL

`leadflow/postgres.py` records what the engine decided. The engine still decides in memory;
the database is the permanent, auditable record that reporting (LF-011/LF-012) will read.

```python
import psycopg
from leadflow import ContactStore, load_rules, postgres

conn = psycopg.connect("dbname=leadflow_eu user=postgres", autocommit=True)
postgres.seed_reference_data(conn, rules, settings, "2026-10-01T00:00:00+02:00")  # once
prepared, decision = postgres.process_and_record(conn, raw_event, received_at, store, rules, settings)
```

### What one event writes

| Situation | Rows written (all in one transaction) |
|---|---|
| Every stored event | `ingestion_events` (raw payload, status, error code), `processing_decisions` (input snapshot, scores, priority, outcome, reason codes, full decision) |
| New contact | `leads`, `companies` (one per domain), `engagement_events` |
| Assigned (round-robin or same-company owner) | `assignments`, `sla_tracking` (8-hour deadline + response target), `sla_history` (`sla_created`), `routing_state` (round-robin only) |
| Priority up before first follow-up | `sla_tracking` target moved earlier + `sla_history` (`response_target_shortened`); the SLA deadline never moves |
| Waiting for a person | `review_cases` (queue and action owner in `case_details`), plus a parallel case for `SUPPLIER_REVIEW` / `IDENTITY_REVIEW` |
| Paid-survey participant | `participant_redirects` (simulated only; no reply sent, no personal data transferred) |
| Replayed event (same ID) | Nothing. The decision is `duplicate_event_ignored` |

Outcome mapping to `decision_outcome`: assigned → `assignment_required`, review → `review_required`,
redirected → `redirection_required`, rejected → `rejection_required`, owner kept / attached to existing
contact → `no_change`.

### Safeguards

- **All or nothing.** If any write fails, the transaction rolls back and the in-memory store is restored,
  so the round-robin does not advance for a lead that was not saved and a retry is not treated as a repeat.
- **No duplicates on retry.** Every row has a fixed ID or key derived from the event (same event → same
  IDs), and inserts skip rows that already exist. Running the whole batch twice adds nothing.
- **Reproducible times.** Every timestamp comes from the event's received time, never the database clock.
- **Reference data** (`seed_reference_data`): rule version `LF-RULES-v1.0` (approved by Radu Teodoriu,
  2026-10-23), six reps and the Sales Manager, eligibility periods built from the unavailability list,
  the starting round-robin position, and the supplier redirect rules. Safe to run again: it never rewinds
  a rotation already in use.

### Schema changes (migration `SQL/002_response_targets.sql`)

| Change | Why |
|---|---|
| `sla_tracking`: `response_target_priority`, `original_response_target_at`, `current_response_target_at` | Option C: one SLA, plus a measured response target. Set together; after the start; never after the SLA deadline; can only move earlier |
| `sla_history`: event type `response_target_shortened` | Audit trail for a target change; must keep the SLA deadline and status and point at the decision that caused it |
| `assignments`: method `same_company_owner` | LF-002 same-company assignment is automatic but not round-robin |

`001` now also accepts the throwaway database `leadflow_eu_test`. `SQL/tests/run_all_tests.sh --rebuild`
applies every `SQL/NNN_*.sql` migration in order. `SQL/tests/016_test_response_target_constraints.sql`
checks the new constraints (11 checks).

### Tests (`tests/test_lf007_postgres.py`)

They wipe and rebuild the database, so they run only against `leadflow_eu_test` (set
`LEADFLOW_TEST_DSN`), and are skipped when psycopg or the database is not available.

| Test | What it checks |
|---|---|
| Every event saved once | 97 events and decisions (the 3 replays are not stored), leads, assignments by method, SLA rows, SLA history, participant referrals |
| Processing status | `processed` / `review_required` / `redirected` / `rejected` match the outcomes; rejected events carry `SOURCE_EVENT_INVALID` |
| Decisions match answer key | Outcome, priority, reason codes and owner for every saved event |
| Lead ownership, SLA and target | Owner, assignment time, initial priority, SLA deadline and current response target for every assigned lead at the cut-off; status still `pending` (LF-009 evaluates met/breached) |
| Round-robin position | Last rep assigned per country, and the engine's next pointer follows it |
| Review cases | One case per queue entry, plus parallel cases by reason code |
| Participant referrals | Simulations only, never personal data transferred |
| Running again adds nothing | Same row counts and rotation after a second full run |
| Failed save | A forced failure leaves no partial rows and no rotation change; the retry gives the expected decision |

Sensitivity (each change made on purpose, then undone): removing the store restore, the routing update,
the target history, the skip-if-exists on decisions, the same-company method, or the parallel cases, or
storing the deadline as the target, each makes at least one of these tests fail.

### Not in Phase B

Follow-up activities and SLA met/breached (LF-009); loading the store back from the database and
reconciling totals (LF-008); CRM writes (LF-010); review actions (done by people).
