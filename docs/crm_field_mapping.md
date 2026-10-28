# CRM field mapping (LF-010)

What LeadFlow writes on each CRM contact, and where each value comes from. The values
are defined once, in the database view `crm_desired_contact_state` (migration
`SQL/005_crm_desired_state.sql`). The writer, the reconciliation and later reporting all
read that view.

| CRM contact property | LeadFlow source | Format | Example | Owned by |
|---|---|---|---|---|
| `leadflow_owner` | Current owner's staff code (open assignment) | Text | `ES-01` | LeadFlow (routing) |
| `hubspot_owner_id` | `owners.crm_owner_id` of the current owner | CRM user id | `12345678` | Phase B: filled once salespeople are mapped to CRM users. Not sent while unmapped |
| `leadflow_priority` | Priority of the lead's latest decision | `P1` / `P2` / `P3` | `P2` | LeadFlow (LF-002 rules) |
| `leadflow_sla_deadline` | `sla_tracking.current_deadline_at` | ISO 8601, UTC | `2026-11-10T12:00:00Z` | LeadFlow (SLA) |
| `leadflow_sla_status` | `sla_tracking.sla_status` | `pending` / `met` / `breached` | `met` | LeadFlow (LF-009) |
| `leadflow_response_target_at` | `sla_tracking.current_response_target_at` | ISO 8601, UTC | `2026-11-09T17:00:00Z` | LeadFlow (SLA) |
| `leadflow_response_target_status` | `sla_tracking.response_target_status` | `pending` / `met` / `missed` | `missed` | LeadFlow (LF-009) |
| `leadflow_review_reason` | Reason codes of the lead's open review cases | Codes separated by `;` | `SUPPLIER_REVIEW` | LeadFlow; cleared when the cases are resolved |

## Rules

- **Which contact:** a lead with a CRM contact id is addressed by it (`hs_object_id`).
  Otherwise it is addressed by its email address, the CRM's unique contact property
  (`id_property = email`).
- **Only differences are sent:** what the contact should show is compared with the values
  last confirmed in the CRM. An unchanged contact gets no update.
- **Clearing:** a property that had a value but now has none (for example, a review
  resolved) is sent as an empty value, which clears it in the CRM.
- **Not written:** CRM-related review cases (`CRM_WRITE_FAILED`), which are about the
  integration, not the contact. Contact details (name, email, company) are never written:
  the CRM stays the owner of those.
- **Dates in UTC:** the CRM shows them in each user's own time zone.

## Phase B notes (live HubSpot)

- The `leadflow_*` properties are created in the test account by a setup script, as
  custom contact properties in a "LeadFlow" property group.
- Each property's HubSpot type (text, enumeration, date and time) and the value format
  HubSpot expects for date-time properties are taken from HubSpot's current
  documentation when Phase B is built. If HubSpot needs another format, the view changes;
  the writer does not.
- `hubspot_owner_id` is HubSpot's standard contact owner field. It is sent only once
  `owners.crm_owner_id` is filled for the six salespeople.
