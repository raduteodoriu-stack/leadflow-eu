# LeadFlow EU: the 3-minute pitch

For hiring managers. About 366 words: spoken at an easy pace with pauses it runs about
2 minutes 40 seconds, leaving room for a breath. The slide deck follows the same order;
each slide's speaker notes hold its part of this script.

| Time | Part |
|---|---|
| 0:00 | Opening |
| 0:10 | The problem |
| 0:35 | What I built |
| 1:05 | How I proved it |
| 1:35 | What it revealed |
| 2:00 | The dashboard |
| 2:15 | What I'd do next |

## Script

**(0:00) Opening.** Hi, I'm Radu. LeadFlow is a lead-routing system I built end to end, and in three minutes I'll show you what it does and how I proved it works.

**(0:10) The problem.** Every sales team says it answers leads fast; few can prove it. In the company I modelled, a B2B software vendor selling in Spain, Portugal and France, leads arrived with messy data and waited to be routed by hand. Nobody knew how long a lead waited for its first call, so slow follow-up stayed invisible.

**(0:35) What I built.** LeadFlow fixes that in five steps. It cleans each enquiry, gives it a priority from six rules a manager can read, and routes it to the right salesperson by country; unclear cases go to a person, not a guess. Then it starts a promise: a first follow-up within eight working hours, with a tighter target for urgent leads. It tracks the promise, keeps the CRM up to date, and reports it all on a Power BI dashboard.

**(1:05) How I proved it.** The part I'm proudest of is the proof. Before writing any code, I wrote down the expected outcome of 100 test enquiries and 69 edge cases. Every layer is checked against that answer key: 268 automated tests, a 28-point reconciliation, 74 KPI values and 32 dashboard numbers. If anything drifts, the build fails before a manager sees a wrong number.

**(1:35) What it revealed.** And on day one the dashboard tells a story. The team keeps the eight-hour promise 92% of the time, which looks healthy. But only 68% of leads meet their urgency target, and the most urgent miss the most: just 6 of 12 P1 leads got a call within the hour. One SLA number hides that.

**(2:00) The dashboard.** This is what the Sales Manager sees each morning: whether the data balanced, the five numbers that matter, and the leads to call now. Salespeople see only their own.

**(2:15) What I'd do next.** In a real team, I'd connect the live CRM, which is already HubSpot-ready; send P1 leads to whoever is free, with an alert at thirty minutes; and measure again with the same tests. That's what I'd bring to your team: revenue processes you can measure, and numbers people trust. Thank you. (Ends about 2:40.)

## Facts behind the numbers

| Said | Source |
|---|---|
| 100 test enquiries, 69 scenarios | `data/synthetic/`, `tests/fixtures/scenarios/` (S-, B-, T- files) |
| 268 tests, 28 checks, 74 KPI values, 32 dashboard values | README "How I know it works" |
| 92% promise, 68% target | SLA attainment 58 ÷ 63, response-target hit rate 44 ÷ 65 (`docs/kpi_definitions.md`) |
| 6 of 12 P1 leads within the hour | `reporting.fact_lead`: P1 response target met 6, missed 6 |
| Median P1 first follow-up 2 h 6 min | KPI 25, P1: 126 working minutes |

All data is synthetic: the numbers show what the system reveals, not how a real team performs.
If asked, say so plainly.

## Likely follow-up questions (short answers)

- **"Is this real data?"** No, synthetic and labelled as such. The point is the method: rules,
  tests and a dashboard you can trust. Plugged into a real CRM, the same checks run on real data.
- **"Why not machine learning for the priority?"** No outcome data to train on, and managers
  need to explain every decision. Rules first; a model only once there is history to prove it beats them.
- **"How long did it take?"** Approx. 2 weeks. Built card by
  card, each card merged as a pull request with its evidence.
- **"What would you measure next?"** Lead-to-meeting conversion by priority, once the CRM
  connection gives real outcomes.
