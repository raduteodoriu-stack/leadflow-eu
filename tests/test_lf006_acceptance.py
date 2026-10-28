"""LF-006 acceptance tests: the engine's preparation step against the reviewed answer keys.

Runs every LF-004 scenario (49) and every LF-005 event (100) through `prepare_event` and
compares only what LF-006 is responsible for: event status, normalised email, country code,
whether a lead is created, the identity outcome and the LF-006 reason codes.
Scores, priority, owners, queues and SLA times are checked in LF-007.
"""
import json
import pathlib

import pytest

from leadflow import ContactStore, load_rules, prepare_event

ROOT = pathlib.Path(__file__).resolve().parents[1]
RULES = load_rules()
SCENARIOS = sorted((ROOT / "tests/fixtures/scenarios").glob("*.json"))
DATASET = json.loads((ROOT / "data/synthetic/leads_100.json").read_text(encoding="utf-8"))
EXPECTED = json.loads((ROOT / "data/synthetic/expected_outcomes.json").read_text(encoding="utf-8"))

# Reason codes decided in LF-006. SAME_COMPANY_RECENT_CONTACT is detected here but only
# applied by LF-007 (it depends on the colleague's owner being available).
LF006_CODES = {"SOURCE_EVENT_INVALID", "DUPLICATE_EVENT_RECONTACT", "EMAIL_INVALID", "COUNTRY_INVALID",
               "COUNTRY_CONFLICT", "UNSUPPORTED_TERRITORY", "EXISTING_CONTACT", "IDENTITY_REVIEW",
               "SUPPLIER_REVIEW", "RELATIONSHIP_UNKNOWN", "DOMAIN_MISSING", "PARTICIPANT_REDIRECT",
               "NO_REDIRECT_RULE"}
STATUS_FOR_OUTCOME = {"rejected": "rejected", "duplicate_event_ignored": "duplicate", "redirected": "participant"}


def mismatches(prepared, expected):
    found = []
    want_codes = set(expected.get("reason_codes", [])) & LF006_CODES
    if set(prepared["reason_codes"]) != want_codes:
        found.append(f"reason codes {sorted(prepared['reason_codes'])} != {sorted(want_codes)}")
    outcome = expected.get("outcome")
    if outcome in STATUS_FOR_OUTCOME and prepared["status"] != STATUS_FOR_OUTCOME[outcome]:
        found.append(f"status {prepared['status']} != {STATUS_FOR_OUTCOME[outcome]}")
    if prepared["status"] in ("rejected", "duplicate"):
        return found
    if "normalised_email" in expected and prepared["status"] != "participant":
        if expected["normalised_email"] is None:
            if prepared["contact"]["email_valid"]:
                found.append("email should be invalid")
        elif prepared["contact"]["normalised_email"] != expected["normalised_email"]:
            found.append(f"email {prepared['contact']['normalised_email']} != {expected['normalised_email']}")
    if "country_code" in expected and prepared["country"]["code"] != expected["country_code"]:
        found.append(f"country {prepared['country']['code']} != {expected['country_code']}")
    if "lead_created" in expected:
        creates = (prepared["status"] == "ready" and prepared["contact"]["email_valid"]
                   and prepared["identity"]["match"] == "new")
        if creates != expected["lead_created"]:
            found.append(f"lead created {creates} != {expected['lead_created']}")
    colleague = (prepared.get("identity") or {}).get("same_company_colleague")
    if "SAME_COMPANY_RECENT_CONTACT" in expected.get("reason_codes", []) and not colleague:
        found.append("same-company colleague not detected")
    if colleague and not prepared["blocking"] and "SAME_COMPANY_RECENT_CONTACT" not in expected.get("reason_codes", []):
        found.append("unexpected same-company colleague")
    return found


def store_from_prior_state(prior):
    store = ContactStore()
    for lead in prior.get("existing_leads", []):
        domain = lead.get("company_domain")
        store.add_contact(lead["normalised_email"],
                          lead.get("first_contact_at") or lead.get("assigned_at") or "2026-01-01T09:00:00+01:00",
                          company={"company_domain": domain} if domain else None,
                          crm_contact_id=lead.get("crm_contact_id"), owner=lead.get("owner"))
    for done in prior.get("processed_events", []):
        store.mark_processed(done["source_system"].lower(), done["source_event_id"])
    return store


LEAD_SCENARIOS = [p for p in SCENARIOS
                  if json.loads(p.read_text(encoding="utf-8"))["input"].get("event_type") not in ("activities", "sla_timeline")]


def test_every_scenario_is_covered():
    # B-12, B-13, B-16 and B-17 are follow-up activity scenarios and T-01 to T-20 are SLA timelines
    # (both LF-009), not inbound events.
    lf004 = [p for p in SCENARIOS if p.stem[:2] in ("S-", "B-")]
    assert len(lf004) == 49 and len(LEAD_SCENARIOS) == 45


@pytest.mark.parametrize("path", LEAD_SCENARIOS, ids=lambda p: p.stem)
def test_lf004_scenario(path):
    scenario = json.loads(path.read_text(encoding="utf-8"))
    prior = scenario["prior_state"]
    settings = {"supplier_redirect_rules": prior.get("supplier_redirect_rules", {})}
    prepared = prepare_event(scenario["input"], scenario["evaluation_time"], store_from_prior_state(prior),
                             RULES, settings)
    assert not mismatches(prepared, scenario["expected"]), mismatches(prepared, scenario["expected"])


def test_lf005_dataset_in_processing_order():
    store = ContactStore()
    settings = {"supplier_redirect_rules": DATASET["metadata"]["supplier_redirect_rules"]}
    problems = []
    for event, expected in zip(DATASET["events"], EXPECTED["events"]):
        prepared = prepare_event(event["input"], event["received_at"], store, RULES, settings)
        for issue in mismatches(prepared, expected["expected"]):
            problems.append(f"event {event['seq']} ({expected['subtype']}): {issue}")
    assert not problems, "\n".join(problems)
