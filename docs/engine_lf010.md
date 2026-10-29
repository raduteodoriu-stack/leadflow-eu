# LF-010 CRM write-back (Phase A: simulated)

LeadFlow now keeps each lead's CRM contact up to date with what it decided: owner,
priority, SLA deadline and status, response target and outcome, and open review reasons.
Phase A does everything except contact a real CRM: each update is built, compared, logged
and confirmed as `simulated`, with the exact payload that would be sent. Phase B swaps in a
HubSpot client with the same two methods (`send`, `read`); nothing else changes.

## How it works

1. **What the contact should show:** the view `crm_desired_contact_state` (migration
   `005`), with fields mapped in [`crm_field_mapping.md`](crm_field_mapping.md).
2. **What the CRM is known to show:** every confirmed update (`succeeded` or `simulated`)
   in `crm_write_log`, applied in order.
3. **The difference** becomes one *logical update* (`logical_update_id`) holding only the
   changed values. Each try is one row in `crm_write_log` (attempt 1, 2, ...).
4. **Each try in three steps:**
   - the attempt is recorded as `in_progress` before the CRM is called;
   - the CRM is called, outside any database transaction;
   - the result is recorded.

   A crash in between leaves `in_progress`, and the next run checks the contact before
   doing anything else.
5. **When:** after every event and every SLA change, for the contacts it touched, in its
   own transaction, after the business data is saved. `CrmWriter.sync_all` updates every
   contact that differs, for example after an outage.

| Situation | What the writer does |
|---|---|
| Contact unchanged | Nothing |
| Change detected | Sends only the changed values; empty value clears a field |
| 429 rate limit, 5xx server error | `failed`, retryable; waits 1, 5, 15, 60 minutes; after 5 attempts gives up and opens a `CRM_WRITE_FAILED` review case for RevOps |
| Other 4xx (validation) | `failed`, not retried, `CRM_WRITE_FAILED` case for RevOps; the same update is not sent again |
| No answer (timeout) | `unknown`; next run reads the contact back: already shows the values → recorded `succeeded` (`verified_by_read`), otherwise sent again |
| Crash mid-call | Row left `in_progress`; next run marks it `unknown` and reads back as above |
| New change while an update waits to retry | Old update stops retrying (`superseded_at`); the new one carries every value not yet confirmed |
| Responses | Only safe fields kept (`status`, `category`, `message`, `correlationId`, `errorType`, `policyName`); never headers or tokens |

The database rules from LF-003 back this up: at most one recorded success per logical
update, a retry time only on a retryable failure, an error code on every failure or
unknown result, and no HTTP code on a simulation.

## Results on LF-005

- 163 updates for the 76 contacts, all `simulated`, one attempt each.
- Every contact shows exactly what LeadFlow decided (reconciliation C19).
- Running the whole batch again after a restart writes nothing new.

## Reconciliation (28 checks)

| Check | What it proves |
|---|---|
| C19 | Every CRM contact shows what LeadFlow decided (confirmed values = intended values) |
| C20 | No intended update is confirmed more than once |
| C21 | Every update given up on has a RevOps review case |

A contact whose update is still waiting or was refused is reported by C19. That is
intended: the report shows the CRM is not yet up to date, instead of hiding it.

## Tests (`tests/test_lf010_crm.py`, 11)

| Test | What it checks |
|---|---|
| Every contact shows what LeadFlow decided | All 76 contacts updated, all simulated, one attempt per update, reconciliation balanced |
| Only changed values are sent | No value is ever sent twice in a row |
| Running again sends nothing | Restart + whole batch again: no new rows anywhere |
| Rate limit | Waits, sends nothing early, retries the same update, succeeds |
| Validation error | Not retried, RevOps case, never sent again |
| No answer, already applied | Read back, recorded as success, sent only once |
| No answer, not applied | Sent again |
| Crash mid-call | Recovered on the next run without a double write |
| Newer change | Waiting update superseded; new update carries all unconfirmed values |
| Retries exhausted | 5 attempts with growing waits, then RevOps; C19 honestly reports the contact as not up to date |
| Nothing secret stored | Tokens and headers from a CRM response never reach the database |

A fake CRM in the tests answers from a script (200, 429, 400, 500, no answer, crash).
Sensitivity: sending every field, skipping the read-back, retrying validation errors,
not superseding, no attempt limit, not sanitising, resending a refused update, or ignoring
the wait each make at least one test fail.

## Phase B: live HubSpot (optional)

Needs the developer test account (created 2026-10-28), a private app token kept in a
`.env` file outside git, the `leadflow_*` custom properties, the six salespeople as users
(`owners.crm_owner_id`), and the synthetic contacts created in the test account. Only the
transport changes: a HubSpot client implementing `send` and `read`, with endpoints and
limits taken from HubSpot's current documentation.
