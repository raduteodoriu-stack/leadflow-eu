# LF-005 Spot-check of expected outcomes

Hand review of a random sample of 20 events from `data/synthetic/expected_outcomes.json`
against LF-002 and the 2026-10-23 rule decisions. Sample drawn with seed 20261023,
stratified by event group so every type is represented.

Reviewer: Radu Teodoriu. Prepared with Claude (working shown for each event).

| Batch | Events | Date | Result |
|---|---|---|---|
| 1 | 6, 11, 18, 19, 23 | 2026-10-26 | Agreed |
| 2 | 26, 27, 32, 34, 46 | 2026-10-26 | Agreed |
| 3 | 55, 56, 59, 67, 69 | 2026-10-26 | Agreed |
| 4 | 75, 90, 91, 93, 100 | 2026-10-26 | Agreed |

**Result: 20 of 20 expected outcomes agreed; no labelling errors found.**

## Findings and follow-ups

- **For LF-009 (SLA tracking):** event 46 has its SLA deadline on its owner's day off (ES-01, 28 Oct).
  LF-002 only raises `OWNER_REVIEW` when a new event arrives for the lead, so a pending lead can breach
  while its owner is away without anyone being warned. Add to LF-009: *when an owner becomes unavailable,
  alert the Sales Manager about their leads that are still pending, before the deadline passes.*
- **Rule question for later (LF-002):** event 59 is P1 because of a quote request from a week earlier
  that the rep had already answered. Under LF-002 an explicit request keeps a lead at P1 for 30 days, so a
  handled contact can sit at the top of the P1 list for a month. Possible refinement: a request that has
  already received a qualifying follow-up no longer triggers priority rule 2. Not a labelling error.
