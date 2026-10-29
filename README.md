# LeadFlow EU

Lead validation, prioritisation and routing for a simulated B2B research-technology vendor (**MoP Cloud**) selling in Spain, Portugal and France.

**Business problem:** inconsistent lead data and manual assignment delay sales follow-up.
**Objective:** validate, prioritise and route leads with explainable, deterministic decisions and a full audit trail.

> All company and contact data is synthetic. No real customer information is used.

## Status (2026-10-26)

| Area | Status |
|---|---|
| LF-001 scope, LF-002 business rules | Documented (GitHub issues #1, #3) |
| LF-003 PostgreSQL data foundation | **Built and tested**: 20 tables, constraint tests on a clean rebuild ([evidence](docs/evidence/)) |
| LF-004 test scenarios, LF-005 synthetic dataset | 49 reviewed scenarios; 100 events with expected outcomes ([summary](docs/synthetic_dataset.md)) |
| LF-006 / LF-007 Python engine | **Built and tested**: validation, identity, scoring, priority, routing, SLA; every decision saved to PostgreSQL ([LF-006](docs/engine_lf006.md), [LF-007](docs/engine_lf007.md)) |
| LF-008 restart and reconciliation | **Built and tested**: memory rebuilt from the database; source-vs-database reconciliation report ([LF-008](docs/engine_lf008.md)) |
| LF-009 SLA tracking | **Built and tested**: SLA met/breached, response targets, late-logged follow-ups, owner-unavailable alerts, reassignment ([LF-009](docs/engine_lf009.md)) |
| LF-010 CRM write-back | **Phase A built and tested**: every contact kept up to date with owner, priority, SLA and review reason; only changes sent; safe retries; simulated ([LF-010](docs/engine_lf010.md), [field mapping](docs/crm_field_mapping.md)). Phase B (live HubSpot test account): optional |
| Reporting model, Power BI, portfolio | Planned (LF-011 to LF-013) |
| Per-salesperson holiday calendars | Planned post-MVP (LF-014); public holidays are not counted yet |

## Repository layout

```
leadflow/                   Python engine (standard library) + PostgreSQL recording (psycopg)
leadflow/rules/             Versioned business rules (LF-RULES-v1.0.json)
SQL/NNN_*.sql               Schema (001) and migrations (002 to 005), applied in number order
SQL/tests/                  Constraint tests (each rolls back) and run_all_tests.sh
SQL/reconciliation/         Database consistency checks (LF-008 to LF-010)
tests/                      pytest: unit, answer-key and PostgreSQL integration tests
tools/                      Synthetic data generator, reconciliation report
data/synthetic/             LF-005 dataset and expected outcomes
docs/                       Data dictionary, database design, engine notes, evidence
```

## Build and test locally

Requires PostgreSQL (tested on 18.1), bash and Python 3.9+.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export PGUSER=postgres
SQL/tests/run_all_tests.sh --rebuild
createdb leadflow_eu_test
export LEADFLOW_TEST_DSN="dbname=leadflow_eu_test user=postgres"
python -m pytest
python tools/reconcile.py --dsn "$LEADFLOW_TEST_DSN" --run
```

`run_all_tests.sh --rebuild` drops and recreates `leadflow_eu` and applies every migration. The PostgreSQL
tests and `reconcile.py --run` wipe `leadflow_eu_test` and refuse any other database; without
`LEADFLOW_TEST_DSN` they are skipped.

## Key design rules

- Territories ES, PT, FR; country round-robin across active eligible reps.
- One first follow-up SLA of 8 business hours (Mon–Fri 09:00–18:00 Europe/Madrid) for every assigned lead; priority sets a response target (P1 60, P2 240, P3 480 business minutes) that is measured but never a breach.
- One lead per normalised email; ambiguous duplicates go to review, never auto-merged.
- Idempotent ingestion on `(source_system, source_event_id)`.
- Supplier-only and participant enquiries are kept out of buyer scoring and SLAs; participant referrals are simulated only.
- Decisions are rule-based and versioned; no LLM decision-making in the MVP.

## Tools

PostgreSQL, SQL, bash, Python, pytest, psycopg; planned: HubSpot API (test account), Power BI.
