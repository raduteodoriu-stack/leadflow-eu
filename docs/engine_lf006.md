# LF-006 Validation and normalisation

First half of the LeadFlow engine. `prepare_event` turns one raw inbound event into a
**prepared event**: cleaned data, who the contact is, and any problems found. LF-007 then
scores, prioritises, assigns and saves the decision.

It covers LF-002 processing steps 1-5. Rule version: `LF-RULES-v1.0`.

## How to use

```python
from leadflow import ContactStore, load_rules, prepare_event

rules = load_rules()            # reads leadflow/rules/LF-RULES-v1.0.json
store = ContactStore()          # in-memory record of earlier events and contacts
prepared = prepare_event(raw_event, received_at, store, rules,
                         settings={"supplier_redirect_rules": {...}})
```

Events must be processed in the order they were received; `store` carries what has been seen so far.

## What each step does

| LF-002 step | Module | What happens |
|---|---|---|
| 1. Already processed? | `prepare.py`, `identity.py` | `(source_system, source_event_id)` seen before → `status: duplicate`, `DUPLICATE_EVENT_RECONTACT`. No event ID → `status: rejected`, `SOURCE_EVENT_INVALID`; a repeated payload without an ID is flagged as a possible repeat (DR-016) |
| 2. Validate and standardise | `normalise.py`, `validate.py` | Email trimmed, lower-cased and format-checked (DR-017); country aliases → ISO code; domain cleaned; missing controlled values → `'unknown'`; earlier engagement names mapped to stored names (DR-002); unexpected values reported in `warnings` |
| 3. Contact identity | `identity.py` | `new`, `existing`, `recontact` (same email, under 8 business hours since first contact), `crm_match` (new email, existing CRM contact ID), plus a same-company colleague within 8 business hours. An existing contact without company data uses its stored company data |
| 4. Country eligibility | `prepare.py` | New contacts only: `missing`/`unrecognised` → `COUNTRY_INVALID`, `conflict` → `COUNTRY_CONFLICT`, `unsupported` → `UNSUPPORTED_TERRITORY`; each sets `blocking: true` |
| 5. Relationship | `prepare.py` | Paid-survey participants → `status: participant` with `PARTICIPANT_REDIRECT` or `NO_REDIRECT_RULE`; supplier or both → `SUPPLIER_REVIEW`; unknown → `RELATIONSHIP_UNKNOWN` |

Working-time arithmetic (Monday-Friday 09:00 up to 18:00, Europe/Madrid) lives in `business_time.py` and is reused by LF-007 and LF-009.

## Prepared event

| Field | Meaning |
|---|---|
| `status` | `ready` (go to LF-007), `rejected` (malformed), `duplicate` (replay, ignore), `participant` (redirect step) |
| `event` | Source system and event ID, event type, occurred and received times, payload fingerprint |
| `contact` | Email as received, normalised email, whether it is valid, CRM contact ID |
| `identity` | `match`, the existing lead it refers to (`lead_key`), business minutes since first contact, same-company colleague |
| `country` | Input values, ISO code, status; existing contacts keep their stored country |
| `relationship`, `enquiry_type`, `redirect_rule` | Classification |
| `company` | Standardised company data; `source` is `event` or `stored` |
| `engagement` | Coverage, events after mapping and de-duplication, names that could not be mapped |
| `reason_codes` | Codes decided in LF-006 (order not significant) |
| `blocking` | `true` → LF-007 sends the lead to `unassigned_review` instead of round-robin (priority is still shown) |
| `warnings` | Values that were unexpected and how they were treated |

## Decisions made while building

- **Same-company code applied in LF-007.** LF-006 detects the colleague; `SAME_COMPANY_RECENT_CONTACT` is added by LF-007 when the colleague's owner is available.
- **Country conflict needs two values.** A conflict is raised only when both the form and the CRM give a country and they differ. A missing form country is `COUNTRY_INVALID` even if the CRM has one (never inferred).
- **Windows use occurrence times.** Recontact and same-company windows are measured from the first contact's occurrence time to the new event's occurrence time (decision 2026-10-23). The LF-005 generator measures to receipt time; no event in the dataset is near the boundary, so outcomes are identical.
- **Pure logic, no database yet.** `ContactStore` keeps state in memory. LF-007 adds PostgreSQL with the same interface.
- **Standard library only**, Python 3.9+.

## Tests

| Test file | What it checks |
|---|---|
| `tests/engine/test_normalise.py` | Email, country aliases, domain and text cleaning |
| `tests/engine/test_business_time.py` | Working-time arithmetic, incl. Friday → Monday, 18:00, before 09:00, the clock change |
| `tests/engine/test_prepare.py` | Rejection, replay, recontact boundary, CRM match, same company, stored company data, country problems, invalid email, participants, unknown values, old event names |
| `tests/test_lf006_acceptance.py` | All 45 inbound-event LF-004 scenarios and all 100 LF-005 events, LF-006 fields only |

The acceptance tests were checked for sensitivity: deliberately breaking a rule (removing the "España" alias, shrinking the recontact window, dropping France, ending the day at 17:00) makes them fail.

Run everything with `python3 -m pytest`.
