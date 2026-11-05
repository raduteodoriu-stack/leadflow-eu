# Interview preparation: LeadFlow EU

Questions a hiring manager or interviewer is likely to ask about this project, with answers
grounded in the repository. Answer in your own words; the bullets are the facts to hit.
Every answer works best as **situation → what I did → how I know it worked → what I'd do next**.

## The questions every interviewer asks

**"Walk me through the project in two minutes."**
Use [pitch.md](pitch.md). Lead with the problem (slow follow-up nobody can measure), then
the five steps, the proof, the finding (P1 leads: 6 of 12 within the hour), and the next step.

**"What was the hardest part?"**
Pick one and tell it as a story:
- *Working time that matches everywhere.* The SLA is promised in working hours, so the
  Python engine and the SQL reporting layer must count minutes identically, across weekends
  and the October clock change. I wrote one SQL function and tested it against the engine on
  thousands of random pairs of moments (`SQL/006_reporting_support.sql`, `tests/test_lf011_reporting.py`).
- *Safe to rerun.* A restart must not lose or duplicate anything, and a CRM update must never
  be confirmed twice. Every CRM attempt is logged before the call, and a timeout triggers a
  read-back instead of a resend ([engine_lf010.md](engine_lf010.md)).
- *A Power BI refresh that failed only in full.* Every table refreshed alone, but a full refresh
  was cancelled. I isolated it table by table and found the cause: the read-only login allowed
  5 connections and Power BI opens one per table ([dashboard_guide.md](dashboard_guide.md)).

**"How do you know the numbers are right?"**
- An answer key written *before* the code: the expected outcome of 100 events and 69 reviewed scenarios.
- Each layer is checked against it: 268 tests (engine, database), a 28-check reconciliation
  (source vs database), 74 KPI values (dbt), 32 dashboard measures (Power BI QA).
- I broke things on purpose (a rule, a retry, a KPI definition) and confirmed the tests failed.

**"What would you do differently?"**
- Connect a real CRM earlier (LF-010 Phase B) to meet its limits sooner.
- Add holiday calendars from the start; working time without holidays is a known gap (LF-014).
- Use a warehouse and incremental dbt models once volume justifies it; not before.

**"Is this real data?"**
No, synthetic and labelled as such everywhere. The value is the method: rules people can
read, checks at every layer, a dashboard that proves its own numbers. On real data the same
checks run unchanged.

## RevOps Analyst

**"Define SLA attainment. What's in the denominator?"**
Leads first followed up within 8 working hours ÷ leads whose SLA is *decided* (met + breached).
Leads still inside their window are excluded until decided, or the rate would be flattered
early in the day. 58 ÷ 63 = 92.1% ([kpi_definitions.md](kpi_definitions.md)).

**"Why two measures, a promise and a target?"**
One fair promise for every lead (8 working hours) keeps the team accountable; a stricter
target by priority (1 / 4 / 8 h) shows whether urgency is respected. The gap between them
(92% vs 68%) is the coaching insight a single SLA number hides.

**"Which KPIs did you leave out, and why?"**
Conversion, pipeline and revenue (the data stops at first follow-up and is invented), CAC
(needs spend and salaries), score accuracy (needs outcomes), league tables (rankings
without context mislead). I kept 24 of 33 candidates with one test: would someone act
differently because of this number?

**"A rep says the dashboard is wrong about their breach."**
Open the Response page's breach list (lead ref, deadline, first follow-up). Check the
follow-up time and who owned the lead then: only the owner at the time counts, and a call
logged late but made on time counts and is flagged. The reconciliation and QA badges show
whether the data balanced. If the rep is right, it is a rule question for RevOps, not a
dashboard fix.

## GTM Systems Engineer

**"How does a lead get routed?"**
Validate (email, country, repeats) → identity (new, returning, ambiguous) → fit and engagement
scores → priority by the first matching of six rules → owner: same-company owner, else
country round-robin among available salespeople → SLA starts. Anything unclear (country,
supplier, identity) opens a review case for the person who must act
([engine_lf006.md](engine_lf006.md), [engine_lf007.md](engine_lf007.md)).

**"How do you handle duplicates and replays?"**
Ingestion is idempotent on `(source_system, source_event_id)`: a repeated delivery is
ignored. An event without an ID is stored as rejected and opens a review case for RevOps. One lead per normalised email; ambiguous
matches go to review, never auto-merged.

**"What happens when the CRM is down?"**
Retry 429 and 5xx after 1, 5, 15 and 60 minutes, at most 5 attempts, then a `CRM_WRITE_FAILED`
case for RevOps. Validation errors are not retried. A timeout leaves the result unknown, so
the next run reads the contact back before deciding to resend. Only changed values are sent,
and a newer change supersedes an update waiting to retry ([engine_lf010.md](engine_lf010.md)).

**"How is access controlled?"**
Power BI reads only the `reporting` schema through a read-only login (no access to engine
tables, read-only transactions, 20 connections, password never in a file, one network
range allowed). Row-level security: salespeople see their own leads. Reports carry
references, not names or emails.

**"How would you scale it?"**
Webhooks or a queue instead of batch files, a warehouse with incremental dbt models, the
HubSpot API with its documented rate limits, scheduled refresh through a gateway. The
rules, audit trail and quality gates stay as they are ([architecture.md](architecture.md)).

## AI Operations

**"Why didn't you use AI or machine learning?"**
There is no outcome data to train a lead score on, and sales managers must be able to
explain every routing decision. Rules first, versioned and audited. An AI model earns its
place only when it beats the rules on real outcomes, measured the same way.

**"Where would AI add value here?"**
- Enrichment: filling missing company size or country from public sources, with a
  confidence score and human review below a threshold, never overwriting CRM data silently.
- Classifying free-text enquiries (buyer, supplier, job seeker) as a *suggestion* into the
  existing review queue.
- Drafting first-response emails for the salesperson to edit and send.
Each one logged, measured against the current rules, and reversible.

**"How would you guard against a model being wrong?"**
The same pattern as LeadFlow: an answer key of reviewed cases, a test that fails when the
model disagrees beyond a set rate, a human review queue for low-confidence outputs, and
every suggestion stored with its inputs so a mistake can be traced.

## Stakeholder pushback (practise these out loud)

| Pushback | Answer |
|---|---|
| **VP Sales:** "My team is at 92%. Why do you say we have a problem?" | The promise is kept, but P1 leads, mostly demo requests, get a call within the hour only half the time. Those are the leads most likely to buy. Let's test routing P1 to whoever is free for four weeks and measure the same way. |
| **Sales Manager:** "Eight working hours is too strict for Fridays." | Working time already pauses at 18:00 Friday and resumes Monday 09:00, so a Friday 17:55 lead is 5 minutes old on Monday. If the promise itself should change, it is one versioned rule, and history keeps the old version. |
| **CMO:** "Where's conversion by source?" | LeadFlow stops at the first follow-up, so conversion needs deal data from the CRM. Leads by source is already there. Connecting deals is the next step, and I didn't want to show a number the data can't support. |
| **Salesperson:** "Why do I only see my own leads?" | Row-level security: each person sees their own leads and follow-ups; team totals are on the manager's view. It protects you as much as the customer. |
| **CFO:** "Why not just use HubSpot's built-in reports?" | They show what the CRM holds. LeadFlow adds what it doesn't: working-time SLAs, the reason behind every priority and route, a review queue, and a proof that every number reconciles. And it is built to write the results back into HubSpot (simulated in this version). |

## Numbers to know by heart

| | |
|---|---|
| Test data | 100 synthetic enquiries, 12 Oct – 6 Nov 2026, 76 leads, 6 salespeople in ES, PT, FR |
| Promise / target | 8 working hours; P1 1 h, P2 4 h, P3 8 h; Mon–Fri 09:00–18:00 Madrid |
| Headline results | SLA 92.1% (58/63), target 67.7% (44/65), 9 waiting, auto-assignment 88.2% (67/76), 1 at risk |
| Finding | P1: 6 of 12 within the hour; median first follow-up 2 h 6 min |
| Proof | 69 scenarios, 268 tests, 28 reconciliation checks, 74 KPI values, 145 dbt checks, 32 dashboard measures |
| Stack | Python, PostgreSQL, dbt, Power BI (DAX, TMDL, RLS), pytest; HubSpot-ready write-back |
