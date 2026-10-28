"""LF-007 acceptance tests: full decisions against the reviewed answer keys.

Every inbound LF-004 scenario (45) and every LF-005 event (100) goes through LF-006 + LF-007.
Each field in the expected outcome must match the decision (reason codes as sets); extra
fields in the decision are allowed. Lead-level state at the LF-005 cut-off is checked too.
SLA met/breached tracking is tested in LF-009.
"""
import json
import pathlib

import pytest

from leadflow import ContactStore, load_rules
from leadflow.decide import process_event, record_activity

ROOT = pathlib.Path(__file__).resolve().parents[1]
RULES = load_rules()
SCENARIOS = sorted((ROOT / "tests/fixtures/scenarios").glob("*.json"))
DATASET = json.loads((ROOT / "data/synthetic/leads_100.json").read_text(encoding="utf-8"))
EXPECTED = json.loads((ROOT / "data/synthetic/expected_outcomes.json").read_text(encoding="utf-8"))
REPS = {"ES": ["ES-01", "ES-02"], "PT": ["PT-01", "PT-02"], "FR": ["FR-01", "FR-02"]}


def differences(expected, actual, path="expected"):
    """List every field of `expected` that `actual` does not reproduce."""
    found = []
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return [f"{path}: expected an object, got {actual!r}"]
        for key, value in expected.items():
            if key == "reason_codes":
                if set(value) != set(actual.get(key) or []):
                    found.append(f"{path}.reason_codes: {sorted(actual.get(key) or [])} != {sorted(value)}")
                continue
            if key not in actual:
                found.append(f"{path}.{key}: missing")
                continue
            found += differences(value, actual[key], f"{path}.{key}")
    elif expected != actual:
        found.append(f"{path}: {actual!r} != {expected!r}")
    return found


def store_from_prior_state(prior):
    store = ContactStore()
    leads = prior.get("existing_leads", [])
    for lead in leads:
        domain = lead.get("company_domain")
        record = store.add_contact(lead["normalised_email"],
                                   lead.get("first_contact_at") or lead.get("assigned_at") or "2026-01-01T09:00:00+01:00",
                                   company={"company_domain": domain} if domain else None,
                                   crm_contact_id=lead.get("crm_contact_id"), owner=lead.get("owner"))
        followup = lead.get("first_qualifying_followup")
        record.update(
            assigned_at=_at(lead.get("assigned_at")), priority=lead.get("priority"),
            initial_priority=lead.get("priority"), priority_rule=lead.get("priority_rule"),
            sla_deadline=_at(lead.get("sla_deadline")), target_at=_at(lead.get("response_target_at")),
            first_followup_at=_at(followup["at"]) if followup else None)
    for done in prior.get("processed_events", []):
        store.mark_processed(done["source_system"].lower(), done["source_event_id"],
                             leads[0]["normalised_email"] if len(leads) == 1 else None)
    store.rotation.update(prior.get("round_robin_next", {}))
    return store


def _at(value):
    from datetime import datetime
    return datetime.fromisoformat(value) if value else None


LEAD_SCENARIOS = [p for p in SCENARIOS
                  if json.loads(p.read_text(encoding="utf-8"))["input"].get("event_type") not in ("activities", "sla_timeline")]


@pytest.mark.parametrize("path", LEAD_SCENARIOS, ids=lambda p: p.stem)
def test_lf004_scenario(path):
    scenario = json.loads(path.read_text(encoding="utf-8"))
    prior = scenario["prior_state"]
    settings = {"representatives": REPS, "active_reps": prior.get("active_reps"),
                "supplier_redirect_rules": prior.get("supplier_redirect_rules", {})}
    _, decision = process_event(scenario["input"], scenario["evaluation_time"], store_from_prior_state(prior),
                                RULES, settings)
    problems = differences(scenario["expected"], decision)
    assert not problems, "\n".join(problems)


def run_lf005():
    meta = DATASET["metadata"]
    settings = {"representatives": meta["representatives"], "initial_rotation": meta["initial_rotation"],
                "unavailability": meta["unavailability"],
                "supplier_redirect_rules": meta["supplier_redirect_rules"]}
    timeline = [(_at(e["received_at"]), 1, i, "event", e) for i, e in enumerate(DATASET["events"])]
    timeline += [(_at(a["occurred_at"]), 0, i, "activity", a) for i, a in enumerate(DATASET["followup_activities"])]
    store, decisions = ContactStore(), {}
    for _, _, _, kind, item in sorted(timeline, key=lambda x: x[:3]):
        if kind == "activity":
            record_activity(store, RULES, item)
        else:
            decisions[item["seq"]] = process_event(item["input"], item["received_at"], store, RULES, settings)[1]
    return store, decisions


def test_lf005_events_in_processing_order():
    _, decisions = run_lf005()
    problems = []
    for expected in EXPECTED["events"]:
        for issue in differences(expected["expected"], decisions[expected["seq"]]):
            problems.append(f"event {expected['seq']} ({expected['subtype']}): {issue}")
    assert not problems, "\n".join(problems)


def test_lf005_lead_state_at_cutoff():
    store, _ = run_lf005()
    problems = []
    for lead in EXPECTED["leads"]:
        actual = store.contact(lead["lead_email"])
        if actual is None:
            problems.append(f"{lead['lead_email']}: no contact")
            continue
        if actual["owner"] != lead["owner"]:
            problems.append(f"{lead['lead_email']}: owner {actual['owner']} != {lead['owner']}")
        if lead["owner"]:
            for field, mine in [("sla_deadline", actual["sla_deadline"]), ("response_target_at", actual["target_at"]),
                                ("assigned_at", actual["assigned_at"])]:
                if mine.isoformat(timespec="seconds") != lead[field]:
                    problems.append(f"{lead['lead_email']}: {field} {mine} != {lead[field]}")
            for field in ("initial_priority", "final_priority"):
                mine = actual["initial_priority"] if field == "initial_priority" else actual["priority"]
                if mine != lead[field]:
                    problems.append(f"{lead['lead_email']}: {field} {mine} != {lead[field]}")
    assert not problems, "\n".join(problems)
