# LF-008 Restart safety and reconciliation

LeadFlow can now stop and restart without losing its place or repeating work, and the
database totals can be proven against the source batch. Rule version: `LF-RULES-v1.0`.

## Why

While it runs, the engine keeps a working memory: which events it has handled, every
contact with its owner, priority, deadlines and engagement history, the first follow-up,
and whose turn it is in each country's rotation. Before LF-008 that memory existed only
while the program ran. After a restart the engine would have forgotten repeats, owners
and the rotation. That would mean double assignments, skipped salespeople and wrong
recontact decisions.

## What was built

| Part | File | What it does |
|---|---|---|
| Follow-ups saved | `leadflow/postgres.py` (`record_and_save_activity`) | Every follow-up call or email is stored, with `qualifying` (counts as the lead's first follow-up: a human call or individual email by the owner, after assignment). All or nothing, like events. Judging SLA met/breached stays in LF-009 |
| First contact time | `SQL/003_lead_first_contact.sql` | New column `leads.first_contact_at`: when the contact first got in touch. The recontact and same-company windows are measured from it |
| Reload | `leadflow/reload.py` (`load_store`) | Rebuilds the whole working memory from PostgreSQL |
| Batch runner | `leadflow/batch.py` | Runs events and follow-ups in time order, saving each; can stop part-way and continue |
| Reconciliation | `leadflow/reconcile.py`, `SQL/reconciliation/lf008_consistency_checks.sql`, `tools/reconcile.py` | 22 checks comparing source and database, plus internal consistency; writes a dated report to `docs/evidence/` |

### Where each part of the memory comes from

| Memory | Rebuilt from |
|---|---|
| Events already handled (repeats are ignored) | `ingestion_events` (source system + event ID, linked lead) |
| Repeats of events without an ID (DR-016) | Fingerprint of the stored raw payload of rejected events |
| Contact: country, CRM ID, relationship, company | `leads`, `companies` |
| First contact (recontact and same-company windows) | `leads.first_contact_at`; the company's first contact = the earliest-created lead of that domain |
| Owner and assignment time | Open row in `assignments` |
| Initial and current priority, priority rule | First and latest `processing_decisions` for the lead |
| SLA deadline and response target, target changes | `sla_tracking`, `sla_history` (`response_target_shortened`) |
| First qualifying follow-up | `followup_activities` with `qualifying = true` |
| Engagement history | `engagement_events` |
| Round-robin position | `routing_state` (last rep assigned → next rep to try) |

### Smaller changes

- Engagement actions without a source ID are now stored under a stand-in ID (`<event ID>#<position>`, flagged `source_id_missing`), so a reload still counts them.
- `sla_history` rows now get a fixed ID derived from their key, like every other table. The restart test found that they were getting random IDs. Harmless for duplicates (the key already prevented those), but two identical runs were not byte-for-byte identical.

## Reconciliation report

```bash
python tools/reconcile.py --dsn "dbname=leadflow_eu_test user=postgres" --run
```

`--run` rebuilds `leadflow_eu_test`, processes LF-005 and then reconciles. Without it, the
tool only reads. Exit code 0 only when every check balances.

| Check | What it proves | LF-005 result |
|---|---|---|
| S01 | Events received = events stored + repeats ignored | 100 = 97 + 3 |
| S02–S04 | Every source event is stored; nothing stored that is not in the source; events without an ID stored as rejected | 94 with ID + 3 without |
| S05–S06 | Every follow-up stored, nothing extra | 77 |
| S07 | Every engagement action stored on its lead | 206 |
| C01–C03 | One decision per stored event; status matches the decision | 0 problems |
| C04–C08 | Every assignment decision has one assignment; one current owner, one SLA and one SLA-creation entry per assigned lead | 0 problems |
| C09–C10 | Every review or rejection has a review case; every redirection has one simulated referral | 0 problems |
| C11 | Round-robin position matches the latest round-robin assignment | 0 problems |
| C12–C15 | No company without a lead, no lead without an event, no lead without a first-contact time, no unlinked engagement | 0 problems |

## Tests (`tests/test_lf008_reload.py`, 13 tests)

They wipe and rebuild `leadflow_eu_test` (shared set-up in `tests/pg_support.py`) and are
skipped without psycopg or `LEADFLOW_TEST_DSN`.

| Test | What it checks |
|---|---|
| Reloaded memory = live memory | After the full LF-005 run, the memory rebuilt from the database equals the memory of the run, field by field |
| Restart before every item | Stopping and reloading before **each** of the 177 events and follow-ups gives the same 100 decisions and the same rows in every table as one uninterrupted run |
| Answer key | Outcomes and owners still match LF-005 |
| Repeats after restart | A repeated event is ignored and writes nothing; a repeated payload without an ID is flagged as a possible repeat |
| Follow-ups | All 77 stored; the first qualifying follow-up per lead matches the answer key; automated emails never qualify |
| Reconciliation balances | 22 checks, 0 differences |
| Deliberate breaks (7) | Removing an SLA, closing an owner's assignment, moving the rotation, adding an orphan company, removing a review case, a follow-up or an engagement action is each reported by its check |

Sensitivity: leaving any part out of the reload (rotation, follow-ups, payload
fingerprints, engagement, owner, company, priority, target changes, handled events) makes
at least one of these tests fail. Every part except target changes, which are reported but
do not change decisions, also breaks the restart test itself.

## Limits

- The company's first contact is taken from the earliest-created lead of that domain. Two
  leads of the same company received in the same second would be ordered by email.
- An engagement ID that arrives on two different contacts is kept on the first. S07
  reports the second as missing, so it is never silent.
- SLA met/breached, the owner-unavailable alert and linking the qualifying follow-up to
  the SLA record are LF-009.
