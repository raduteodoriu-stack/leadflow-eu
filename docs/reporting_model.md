# LF-011 Reporting model

The reporting layer turns LeadFlow's operational tables into a small star schema that
answers the KPIs in [`kpi_definitions.md`](kpi_definitions.md). It is a dbt project in
`reporting/`, built inside the same PostgreSQL database. Power BI (LF-012) connects only to
the `reporting` schema.

## Why a separate reporting layer

- **One definition per KPI.** "SLA attainment" is computed once, in SQL that is versioned,
  reviewed and tested, not re-invented in each dashboard measure or spreadsheet.
- **Tested against the answer key.** Every KPI is compared with values worked out
  independently from the LF-005 answer key (`tools/expected_kpis.py`). If a model, a join
  or a definition drifts, `dbt build` fails.
- **The operational schema stays free to change.** Dashboards depend on the facts, not on
  engine tables; a column renamed in `public` is fixed once, in staging.

## Layers

```
public (engine, read only)          reporting_staging (views)       reporting (tables)
-----------------------------       -------------------------       ------------------------------
ingestion_events          ------->  stg_enquiries         ------->  fact_enquiry
processing_decisions      ------->  stg_decisions          \        fact_lead
leads                     ------->  stg_leads               +---->  fact_review_case
owners, eligibility       ------->  stg_owners, ...         |       fact_followup
assignments, sla_tracking ------->  stg_assignments, stg_sla|       fact_crm_update
followup_activities       ------->  stg_followups           |       fact_crm_contact_sync
review_cases              ------->  stg_review_cases        |       fact_daily_backlog
crm_write_log             ------->  stg_crm_writes          |       fact_reconciliation_run
crm_desired_contact_state ------------------------------------>     dim_date, dim_owner, dim_country,
reconciliation_runs       ------->  stg_reconciliation_runs         dim_priority, dim_priority_rule,
                                    int_lead_origin                 dim_review_reason
seeds (reporting_reference): served markets, priorities, rules,     kpi_summary
review reasons, KPI catalogue, expected KPIs
```

## Star schema

| Table | Grain | Main columns | KPIs |
|---|---|---|---|
| `fact_enquiry` | One stored enquiry | received date, channel, outcome, created a lead?, rejected? | 1, 5 |
| `fact_lead` | One lead | country, channel, priority rule, incomplete data; first and current owner, route (automatic / manual / waiting), wait; SLA status, response-target status, first follow-up, working minutes to it, at risk | 2–4, 7, 9–10, 12, 16–17, 20–25 |
| `fact_review_case` | One review case | reason, who must act, opened / resolved, open age in working minutes | 26, 28, 30 |
| `fact_followup` | One call or email | type, outcome, qualifying, logged late | detail |
| `fact_crm_update` | One intended CRM update | attempts, state (confirmed, superseded, waiting to retry, given up, unconfirmed) | 32 |
| `fact_crm_contact_sync` | One CRM contact | shows what LeadFlow decided? (same rule as check C19) | 31 |
| `fact_daily_backlog` | Working day × reason | open cases at 18:00 that day | 29 |
| `fact_reconciliation_run` | One reconciliation | checks run, checks failed, balanced, latest | 33 |
| `kpi_summary` | KPI × breakdown × member | numerator, denominator, value | all |

Dimensions: `dim_date` (working-day flag, ISO week), `dim_owner` (with the sign-in used for
row-level security), `dim_country` (served or not), `dim_priority` (response targets),
`dim_priority_rule` (the LF-002 rules in plain words), `dim_review_reason` (what each review
reason means and who acts).

## Design decisions

| Decision | Why |
|---|---|
| **dbt inside PostgreSQL**, no separate warehouse | 100 synthetic enquiries; a warehouse would add cost and moving parts without changing a number. The models are plain SQL and move to Snowflake or BigQuery with few changes (the `working_minutes` function would be rewritten in that dialect) |
| **No daily snapshot table** for the backlog | Every case has `opened_at` and `resolved_at`, so the open count at any past moment can be rebuilt exactly. A snapshot job would be needed only for values that are overwritten in place (none of the KPIs kept) |
| **Ages in working minutes**, via one database function | The SLA is promised in working hours, so a lead received Friday 17:55 is 5 minutes old on Monday 09:00, not 63 hours. The function is the engine's arithmetic in SQL, checked against it |
| **`as_of` variable** | Every number describes one stated moment. The default is the LF-005 cut-off, so the dashboard matches the answer key; in production it would be the run time |
| **Lead's channel and priority from the enquiry that created it** | A returning contact's later enquiries do not change where the lead came from. A test proves each lead's first stored enquiry arrived exactly when the lead was created |
| **Backlog at 18:00** each working day | "End of the working day" in the business's own terms; a case opened in the evening counts from the next working day |
| **CRM sync is current state only** | The intended CRM values are a view of the current decisions, not kept historically. Reported as of now, and labelled so |
| **`kpi_summary` in long form** (KPI × breakdown × member) | One table any tool can read, and one comparison with the answer key covers every KPI |
| **Row-level security keys** in `dim_owner` (`user_principal_name`, synthetic `*.example`) | Salespeople see their own leads; the Sales Manager and RevOps see everything. Applied in Power BI (LF-012) |

## Tests (`dbt build`)

- **Schema tests:** unique and not-null keys, relationships from every fact to its
  dimensions, accepted values for statuses, channels and routes.
- **`kpi_summary_matches_expected`:** every KPI value equals the LF-005 answer key
  (`reporting/seeds/expected_kpis.csv`, generated by `tools/expected_kpis.py` from
  `data/synthetic/expected_outcomes.json` with its own working-time arithmetic). Any missing,
  extra or different value fails.
- **`facts_reconcile_to_source`:** row counts of every fact equal their source tables
  (nothing lost or doubled).
- **`sla_allowances_match_rules`:** for every SLA, the deadline is 480 working minutes after
  the start and the response target 60 / 240 / 480 for P1 / P2 / P3, measured with
  `working_minutes`.
- **`every_lead_has_its_creating_enquiry`**, **`backlog_ends_at_current_backlog`**,
  **`every_kpi_is_reported`.**

Outside dbt, `tests/test_lf011_reporting.py` checks the working-time function against the
engine on 3,000 random pairs of moments, that every enquiry keeps its source channel, that a
reconciliation run is recorded, and that the answer-key seed is up to date.

## How to run

From the repository root, with the virtual environment active (dbt needs Python 3.10 or
later; see the README):

```bash
python tools/reconcile.py --dsn "dbname=leadflow_eu_test user=postgres" --run
cd reporting
dbt build
dbt docs generate
```

`reconcile.py --run` rebuilds the test database, processes LF-005 up to the cut-off and
records the reconciliation. `dbt build` loads the seeds, builds the models and runs every
test. `pytest` wipes the `public` schema, so run `reconcile.py --run` and `dbt build` again
after it.

The dbt connection lives in `~/.dbt/profiles.yml`, outside the repository
(`reporting/profiles.example.yml` shows the format). The password is read from the
environment variable `DBT_PG_PASSWORD`, never written in a file.

## Limits

- Public and regional holidays are not counted (LF-014). When they are, `working_minutes`
  and `dim_date.is_working_day` change in one place each.
- KPI 11 (time to assignment) and 19 (urgency changes) are not reported yet; the data has no
  completed review and one urgency change.
- The LF-005 data has no late logs, absences or CRM failures, so KPIs 26, 30 and 32 are 0;
  the engine tests (LF-009, LF-010) prove those cases are recorded, and the facts read them
  directly.
