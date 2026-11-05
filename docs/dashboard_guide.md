# LF-012 Power BI dashboard guide

The LeadFlow dashboard shows lead response health at a glance, then the detail behind it.
It reads only the tested reporting layer (LF-011, schema `reporting`), so every number on
screen equals `reporting.kpi_summary`, which dbt checks against the LF-005 answer key.

- **Project:** `reporting/powerbi/LeadFlow.pbip` (Power BI project format: the model and
  pages are text files in git).
- **Model:** 15 tables imported from `reporting`, 15 relationships, 46 measures in
  `_Measures`, two security roles.
- **Data:** synthetic LF-005 data, as of Fri 6 Nov 2026 18:00 (dbt variable `as_of`).

## Pages

| Page | Question it answers | Who uses it |
|---|---|---|
| **Overview** | Is lead response healthy? The trust strip (data as of, reconciliation), the five headline KPIs, at-risk leads, promise vs. target by priority, new leads per week, review backlog | Sales Manager, CRO, everyone |
| **Response** | Where is the promise kept or broken, and how fast are we? Promise and target cards, by salesperson (coaching), median time to first follow-up vs. target, broken promises list, by country, by week | Sales Manager |
| **Intake & Routing** | Where do leads come from and how are they routed? Enquiries and new leads per week, by source, by country, leads waiting for an owner, leads per salesperson, urgency mix, why leads got their priority | Sales Manager, Marketing, RevOps |
| **Exceptions** | What is stuck and who must act? Open cases, oldest case, backlog over time by who must act, open cases by reason, the list of open cases | Sales Manager, RevOps |
| **System health** | Can the data be trusted? CRM in sync, CRM updates by state and attempts, reconciliation runs | RevOps |
| **QA** | Do the dashboard's measures equal the tested KPI layer? QA status (must read "All 32 checked values match kpi_summary") and the full `kpi_summary` | Reviewers |

Colours mean the same everywhere: **dark blue** is the main measure (and the 8-hour promise),
**amber** is the comparison (the urgency target, or RevOps' share of the backlog).

## How to read the headline KPIs

Definitions are in [`kpi_definitions.md`](kpi_definitions.md); the short version:

| KPI | Definition | LF-005 |
|---|---|---|
| SLA attainment | Leads followed up within 8 working hours ÷ leads whose SLA is decided (met + breached) | 58 ÷ 63 = 92.1% |
| Response-target hit rate | Leads followed up within their priority target (P1 1 h, P2 4 h, P3 8 h) ÷ decided targets | 44 ÷ 65 = 67.7% |
| Leads waiting for an owner | New leads in review with no salesperson | 9 |
| Auto-assignment rate | New leads given an owner automatically ÷ new leads | 67 ÷ 76 = 88.2% |
| At-risk leads | Open SLAs due within the next 2 working hours | 1 |

Working time is Monday to Friday, 09:00–18:00, Madrid time, without public holidays (LF-014).

## Security (row-level security)

| Role | Sees | How |
|---|---|---|
| **Salesperson** | Only the leads they currently own, their follow-ups, and those leads' CRM status | `Owner[user_principal_name] = USERPRINCIPALNAME()`; the filter flows from `Owner` to `Lead` and `Follow-up`, and from `Lead` to the CRM tables |
| **Sales Manager and RevOps** | Everything | No filter |

Sign-ins are synthetic (`es-01@mop-cloud.example` and so on). Review cases, the backlog and
reconciliation runs carry no personal data and are not filtered.

Test in Power BI Desktop: **Modeling › View as**, tick **Other user** =
`es-01@mop-cloud.example` and role **Salesperson**: New Leads shows 12 (ES-01's leads) and
the QA page shows differences by design. Role **Sales Manager and RevOps**: New Leads 76,
QA status all matching.

## Set-up (once per machine)

Power BI Desktop runs on Windows (here: Parallels on the Mac, network "Shared"; the Mac is
`10.211.55.2`, Windows `10.211.55.x`). PostgreSQL 18 runs on the Mac.

1. **Read-only login** (SELECT on schema `reporting` only, read-only transactions, at most 20
   connections; no password in the file):
   ```
   psql -U postgres -d leadflow_eu_test -f SQL/admin/powerbi_reader.sql
   psql -U postgres -d leadflow_eu_test -c "\password powerbi_reader"
   ```
2. **Allow the Windows machine only**: one line in `pg_hba.conf`
   (`/Library/PostgreSQL/18/data/pg_hba.conf`), then reload:
   ```
   host  leadflow_eu_test  powerbi_reader  10.211.55.0/24  scram-sha-256
   psql -U postgres -c "SELECT pg_reload_conf()"
   ```
3. **Share the project with Windows**: Parallels › Configure › Options › Sharing › custom
   folder `/Users/<you>/leadflow-eu`. In Windows it appears under **Network › Mac**.
4. **Open** `reporting\powerbi\LeadFlow.pbip`, sign in to the database as `powerbi_reader`
   (Basic, privacy level Organizational). The connection is not encrypted: it stays between
   Windows and the Mac. A server reachable over a real network would use TLS.

The refresh opens one connection per table at the same time; the login allows 20. With the
first limit of 5, a full refresh was cancelled (`0x80040E4E` on every table) while single
tables refreshed fine.

## Refresh after new data

```
python tools/reconcile.py --dsn "dbname=leadflow_eu_test user=postgres" --run
cd reporting
dbt build
```

Then in Power BI: **Home › Refresh**, check that the QA page reads "All 32 checked values
match kpi_summary", and save.

## Working with the project in git

- Committed: `LeadFlow.pbip`, `LeadFlow.Report/` (pages and visuals as JSON) and
  `LeadFlow.SemanticModel/` (tables, measures, relationships and roles as TMDL).
- Not committed (`.gitignore`): `.pbi/localSettings.json` and `.pbi/cache.abf` (local settings
  and the imported data). No credentials are stored in the project.
- Close Power BI before changing the files outside it; if Power BI shows "files were changed
  externally", apply the changes or close without saving.

## Limits

- Power BI Desktop only. Publishing to Power BI Service needs a work or school account and,
  for scheduled refresh from this database, an on-premises data gateway (optional, LF-013).
- Synthetic data: the numbers show that the system works, not how a real team performs.
- Public holidays are not counted (LF-014).
- KPI 11 (time to assignment) and KPI 19 (urgency changes) are not shown yet (see
  `kpi_definitions.md`).
