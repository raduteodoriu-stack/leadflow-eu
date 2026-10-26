# LF-007 Routing and decision logging

Second half of the LeadFlow engine (LF-002 steps 6-9). It takes the prepared event from
LF-006, scores it, sets its priority, chooses an owner or queue, sets the SLA and response
target, and returns the decision. Rule version: `LF-RULES-v1.0`.

- **Phase A — decision logic (this release):** pure Python, in memory.
- **Phase B — PostgreSQL:** saving decisions, assignments, review cases and SLA records (next).

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
