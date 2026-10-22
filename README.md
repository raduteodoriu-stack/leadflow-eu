# LeadFlow EU

Lead validation, prioritisation and routing for a simulated B2B research-technology vendor (**MoP Cloud**) selling in Spain, Portugal and France.

**Business problem:** inconsistent lead data and manual assignment delay sales follow-up.
**Objective:** validate, prioritise and route leads with explainable, deterministic decisions and a full audit trail.

> All company and contact data is synthetic. No real customer information is used.

## Status (2026-10-22)

| Area | Status |
|---|---|
| LF-001 scope, LF-002 business rules | Documented (GitHub issues #1, #3) |
| LF-003 PostgreSQL data foundation | **Built and tested**: 20 tables, 15 constraint test files, 174 checks passing on a clean rebuild ([evidence](docs/evidence/)) |
| Python ingestion and routing engine | Planned |
| HubSpot test-account integration | Planned |
| Power BI reporting | Planned |

## Repository layout

```
SQL/001_create_schema.sql   Full schema (20 tables) + post-install table check
SQL/tests/NNN_test_*.sql    Constraint tests; each runs in a transaction and rolls back
SQL/tests/run_all_tests.sh  Test runner; writes a log to docs/evidence/
docs/data_dictionary.md     Source data contract, allowed values, change log
docs/database_design.md     Relational model and integrity rules
docs/evidence/              Dated test-run logs (git commit, server version, results)
```

## Build and test locally

Requires PostgreSQL (tested on 18.1) and bash. The database must be named `leadflow_eu`; the scripts refuse to run anywhere else.

```bash
export PGUSER=postgres
# Drops and recreates leadflow_eu, installs the schema, runs all tests
SQL/tests/run_all_tests.sh --rebuild
```

Expected result: `Summary: 15 passed, 0 failed`. Without `--rebuild`, tests run against the existing database.

## Key design rules

- Territories ES, PT, FR; country round-robin across active eligible reps.
- First follow-up SLA in business minutes (Mon–Fri 09:00–18:00 Europe/Madrid): P1 60, P2 240, P3 480.
- One lead per normalised email; ambiguous duplicates go to review, never auto-merged.
- Idempotent ingestion on `(source_system, source_event_id)`.
- Supplier-only and participant enquiries are kept out of buyer scoring and SLAs; participant referrals are simulated only.
- Decisions are rule-based and versioned; no LLM decision-making in the MVP.

## Tools

PostgreSQL, SQL, bash; planned: Python, pytest, HubSpot test account, Power BI.
