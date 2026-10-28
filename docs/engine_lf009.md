# LF-009 SLA tracking, response targets and alerts

Every assigned lead's first-follow-up SLA is now tracked as time passes: met, breached or
pending, with its priority response target (met, missed or pending). Follow-ups logged
late are handled, the Sales Manager is alerted when a salesperson becomes unavailable with
leads still waiting, and reassignment keeps the customer's clock. Rule version
`LF-RULES-v1.0`.

## Rules

From LF-002, option C (2026-10-23) and the decisions of 2026-10-28:

| Topic | Rule |
|---|---|
| SLA met | The first qualifying follow-up (a human call or individual email by the lead's owner **at the time**) happened on or before the deadline. The deadline minute counts as on time |
| SLA breached | The deadline passed without one, or the first one came after it. `breached_at` = the deadline. The breach is spotted one minute after the deadline (`breach_detected_at`), as if the check runs every minute. A later follow-up never removes a breach |
| Response target | P1 1 h, P2 4 h, P3 8 h. Met / missed / pending in the same way. Measured and reported, never a breach |
| Late logging | A follow-up counts at the time it happened. Logged after the deadline but made before it: the verdict is corrected (`evidence_corrected` if a breach had been recorded), the first breach detection is kept for audit, and `LATE_LOGGED_FOLLOWUP` is flagged to the Sales Manager |
| Owner unavailable | When a salesperson's absence starts (or when it is recorded, if later), each of their leads that is still pending gets an `OWNER_UNAVAILABLE_PENDING` review case for the Sales Manager. The case suggests the next available salesperson in the country's rotation, or says nobody is available. Nobody is reassigned automatically. Leads already followed up, or already past their deadline, get no alert |
| Reassignment | The Sales Manager moves the lead. The SLA deadline and response target do not change, and the lead's open alerts are resolved. From then on only the new owner's follow-ups count. A call the previous owner made while they still owned the lead still counts, even if it is logged later |

## What was built

| Part | File | What it does |
|---|---|---|
| SLA tracker | `leadflow/sla.py` (`SlaTracker`) | Keeps SLA state current: `advance(moment)` applies breaches, missed targets and alerts due by then; `activity`, `absence`, `reassign` handle each input. Returns a list of changes |
| Owner at the time | `leadflow/decide.py` (`owner_at`) | A follow-up counts only if made by whoever owned the lead when it happened |
| Saving | `leadflow/postgres.py` (`track`, `apply_sla_changes`) | Each tracker action saved in one transaction: follow-ups, SLA status and target outcome, history, review cases, absences (eligibility periods split), reassignments (decision, review action, old assignment closed, new `manual_review` assignment). On failure, memory and the absence list are put back |
| Target outcome column | `SQL/004_sla_tracking.sql` | `sla_tracking.response_target_status`, with a check that the outcome matches the evidence |
| Restart | `leadflow/reload.py` | Also restores SLA status, breach detection, target outcome, ownership history, raised alerts and how far the tracker had got; `load_absences` restores absences recorded at run time |
| Batch | `leadflow/batch.py` | The tracker catches up before every event and follow-up; `until` catches up to a cut-off at the end |
| Reconciliation | `SQL/reconciliation/lf008_consistency_checks.sql` | Three new checks: C16 every met or breached SLA has the history entry that set it; C17 every SLA follow-up qualifies and was made by the owner at the time; C18 every open alert concerns a lead still with that salesperson. 25 checks in total |

### Saved records

| Event | Rows |
|---|---|
| Breach spotted | `sla_tracking` (status, `breach_detected_at`), `sla_history` `status_changed` pending → breached |
| Target passed | `sla_tracking.response_target_status` = missed |
| First qualifying follow-up | `followup_activities`; `sla_tracking` linked to it; `sla_history` `status_changed` (pending → met), `evidence_corrected` (breached → met) or `followup_recorded` (after a breach) |
| Late-logged follow-up | As above, plus a `LATE_LOGGED_FOLLOWUP` review case |
| Absence | `owner_eligibility_history` split (available / away / available again); an `OWNER_UNAVAILABLE_PENDING` review case per pending lead when it starts |
| Reassignment | `processing_decisions` (`MANUAL_REASSIGNMENT`), the alert resolved (or a resolved `MANUAL_REASSIGNMENT` case when there was none), `review_actions` `owner_selected`, the old assignment closed, a new `manual_review` assignment |

Review cases from LF-009 sit in the `sla_review` queue (`case_details.queue`) with the Sales Manager as action owner.

## Tests

| Test file | What it checks |
|---|---|
| `tests/fixtures/scenarios/T-01` to `T-20` | 20 SLA timelines, all reviewed on 2026-10-28 (T-20 added while building, see below) |
| `tests/test_lf009_sla.py` (27) | All 24 SLA scenarios (T-01 to T-20, B-12, B-13, B-16, B-17) in memory; every assigned LF-005 lead's SLA and target outcome at the cut-off (met 58, breached 5, pending 4; target met 44, missed 21, pending 2); no alerts or flags in LF-005 |
| `tests/test_lf009_postgres.py` (28) | LF-005 outcomes saved at the cut-off and reconciliation balanced (25 checks); all 24 scenarios replayed through the database, with the saved statuses, history, alerts and owners matching the answers; the same scenarios with a full restart before every step leave identical rows; an alert raised before a restart is resolved after it; a failed save leaves nothing and memory unchanged |
| `SQL/tests/017_test_response_target_status_constraints.sql` (7 checks) | The target outcome must match the evidence |

Sensitivity (each change made on purpose, then undone): treating the deadline minute as
late, spotting a breach at the deadline itself, dropping the late-log flag, not resolving
alerts on reassignment, suggesting the absent salesperson, alerting only when an absence is
recorded, checking ownership at logging time instead of at the call, never marking a target
missed, not saving history, not resolving alert cases in the database, and leaving SLA
status, raised alerts or absences out of the reload: each makes at least one test fail.

### Scenario added while building

**T-20.** A call made by the owner before a reassignment, but logged after it, still
counts. This follows the approved rules: the owner at the time of the call, and the time
the call happened. No existing scenario covered it, so a mistake there would have gone
unnoticed. Reviewed and agreed on 2026-10-28.

## Limits

- Public and regional holidays are not counted (planned in LF-014). Until then, the Sales
  Manager adds bank holidays to the unavailability list, so routing skips that salesperson.
- Checks are minute-based. A change saved within the minute after a deadline, before the
  breach is spotted, is not modelled.
- An absence can only be recorded inside a period when the salesperson is available. Two
  overlapping absences for the same person are not supported.
- The LF-005 data contains no late-logged follow-ups and no lead waiting on an absent
  salesperson, so those rules are proven by the scenarios only.
