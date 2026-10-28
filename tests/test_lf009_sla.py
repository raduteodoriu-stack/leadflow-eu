"""LF-009 acceptance tests: SLA tracking, response targets, alerts and reassignment (in memory).

- The 20 reviewed T- scenarios (timelines of follow-ups, checks, absences, reassignments)
  and the 4 LF-004 follow-up scenarios (B-12, B-13, B-16, B-17).
- Every assigned LF-005 lead's SLA and response-target outcome at the cut-off.
"""
import json
import pathlib

import pytest

from leadflow import ContactStore, load_rules
from leadflow.decide import process_event
from leadflow.sla import ALERT, SlaTracker, outcome

ROOT = pathlib.Path(__file__).resolve().parents[1]
RULES = load_rules()
SCENARIO_DIR = ROOT / "tests/fixtures/scenarios"
SLA_SCENARIOS = sorted([p for p in SCENARIO_DIR.glob("*.json")
                        if json.loads(p.read_text(encoding="utf-8"))["input"].get("event_type")
                        in ("activities", "sla_timeline")])
DATASET = json.loads((ROOT / "data/synthetic/leads_100.json").read_text(encoding="utf-8"))
EXPECTED = json.loads((ROOT / "data/synthetic/expected_outcomes.json").read_text(encoding="utf-8"))
REPS = {"ES": ["ES-01", "ES-02"], "PT": ["PT-01", "PT-02"], "FR": ["FR-01", "FR-02"]}


def _at(value):
    from datetime import datetime
    return datetime.fromisoformat(value) if value else None


def differences(expected, actual, path="expected"):
    found = []
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return [f"{path}: expected an object, got {actual!r}"]
        for key, value in expected.items():
            if key not in actual:
                found.append(f"{path}.{key}: missing")
            else:
                found += differences(value, actual[key], f"{path}.{key}")
    elif expected != actual:
        found.append(f"{path}: {actual!r} != {expected!r}")
    return found


def build(prior):
    """Store, settings and tracker for a scenario's starting point."""
    store = ContactStore()
    for lead in prior["existing_leads"]:
        record = store.add_contact(lead["normalised_email"], lead["assigned_at"],
                                   country_code=lead.get("country_code", "ES"), owner=lead["owner"])
        followup = lead.get("first_qualifying_followup")
        record.update(assigned_at=_at(lead["assigned_at"]), priority=lead["priority"], initial_priority=lead["priority"],
                      sla_deadline=_at(lead["sla_deadline"]), target_at=_at(lead["response_target_at"]),
                      first_followup_at=_at(followup["at"]) if followup else None,
                      owner_history=[{"owner": lead["owner"], "from": _at(lead["assigned_at"])}])
        first, deadline, target = record["first_followup_at"], record["sla_deadline"], record["target_at"]
        record["sla_status"] = "pending" if first is None else ("met" if first <= deadline else "breached")
        record["response_target_status"] = "pending" if first is None else ("met" if first <= target else "missed")
    store.rotation.update(prior.get("round_robin_next", {}))
    settings = {"representatives": REPS, "unavailability": list(prior.get("unavailability", []))}
    return store, settings, SlaTracker(store, RULES, settings)


def steps_of(scenario):
    data = scenario["input"]
    if data["event_type"] == "sla_timeline":
        return data["steps"]
    email = scenario["prior_state"]["existing_leads"][0]["normalised_email"]
    return [dict(a, step="activity", lead_email=email) for a in data["activities"]]


def replay(scenario):
    store, settings, tracker = build(scenario["prior_state"])
    changes = []
    for number, step in enumerate(steps_of(scenario), start=1):
        kind = step["step"]
        if kind == "activity":
            activity = dict(step, activity_id=f"{scenario['input']['source_event_id']}-A{number}",
                            source_system=scenario["input"]["source_system"])
            changes += tracker.activity(activity)
        elif kind == "evaluate":
            changes += tracker.advance(step["at"])
        elif kind == "absence":
            changes += tracker.absence({k: step[k] for k in ("rep", "from", "until", "recorded_at", "reason")})
        elif kind == "reassign":
            changes += tracker.reassign(step["lead_email"], step["to"], step["at"], step["by"])
    changes += tracker.advance(scenario["evaluation_time"])
    return store, changes


def actual_result(scenario, store, changes):
    key = scenario["prior_state"]["existing_leads"][0]["normalised_email"]
    lead = store.contact(key)
    result = {"owner": lead["owner"], "sla_deadline": lead["sla_deadline"].isoformat(timespec="seconds"),
              "response_target_at": lead["target_at"].isoformat(timespec="seconds"), **outcome(lead)}
    result["history"] = [{"at": c["at"].isoformat(timespec="seconds"), "event_type": c["event_type"],
                          "previous_status": c["previous_status"], "new_status": c["new_status"]}
                         for c in changes if c["kind"] == "status" and c["lead_key"] == key]
    resolved = {k: c["at"] for c in changes if c["kind"] == "owner_changed" for k in c["resolved_alerts"]}
    cases = []
    for c in changes:
        if c["kind"] != "case_opened":
            continue
        status = "open"
        if c["reason_code"] == ALERT:  # the tracker's own record of the alert
            status = store.alerts[c["key"]]["status"]
        case = {"reason_code": c["reason_code"], "lead_email": c["lead_key"],
                "opened_at": c["at"].isoformat(timespec="seconds"), "action_owner": c["action_owner"],
                "status": status}
        if c["reason_code"] == ALERT:
            case["suggested_owner"] = c["suggested_owner"]
        if c.get("note"):
            case["note"] = c["note"]
        if c["key"] in resolved:
            case["resolved_at"] = resolved[c["key"]].isoformat(timespec="seconds")
        cases.append(case)
    result["review_cases"] = cases
    return result


@pytest.mark.parametrize("path", SLA_SCENARIOS, ids=lambda p: p.stem)
def test_sla_scenario(path):
    scenario = json.loads(path.read_text(encoding="utf-8"))
    store, changes = replay(scenario)
    problems = differences(scenario["expected"], actual_result(scenario, store, changes))
    assert not problems, "\n".join(problems)


def test_every_sla_scenario_is_covered():
    assert len(SLA_SCENARIOS) == 24  # T-01 to T-20 + B-12, B-13, B-16, B-17


def run_lf005():
    meta = DATASET["metadata"]
    settings = {"representatives": meta["representatives"], "initial_rotation": meta["initial_rotation"],
                "unavailability": [dict(u) for u in meta["unavailability"]],
                "supplier_redirect_rules": meta["supplier_redirect_rules"]}
    store = ContactStore()
    tracker = SlaTracker(store, RULES, settings)
    timeline = [(_at(e["received_at"]), 1, i, "event", e) for i, e in enumerate(DATASET["events"])]
    timeline += [(_at(a["occurred_at"]), 0, i, "activity", a) for i, a in enumerate(DATASET["followup_activities"])]
    changes = []
    for moment, _, _, kind, item in sorted(timeline, key=lambda x: x[:3]):
        if kind == "activity":
            changes += tracker.activity(item)
        else:
            changes += tracker.advance(moment)
            process_event(item["input"], item["received_at"], store, RULES, settings)
    changes += tracker.advance(meta["sla_cutoff"])
    return store, changes


def test_lf005_outcomes_at_cutoff():
    store, _ = run_lf005()
    problems = []
    for lead in EXPECTED["leads"]:
        if not lead["owner"]:
            continue
        mine = outcome(store.contact(lead["lead_email"]))
        for field in ("sla_outcome", "response_target_outcome"):
            if mine[field] != lead[field]:
                problems.append(f"{lead['lead_email']}: {field} {mine[field]} != {lead[field]}")
    assert not problems, "\n".join(problems)


def test_lf005_history_is_consistent():
    store, changes = run_lf005()
    statuses = [c for c in changes if c["kind"] == "status"]
    assigned = [lead for lead in store.contacts.values() if lead["owner"]]
    breached = [lead for lead in assigned if lead["sla_status"] == "breached"]
    assert {lead["lead_key"] for lead in breached} <= {c["lead_key"] for c in statuses if c["new_status"] == "breached"}
    for lead in breached:  # breach spotted after the deadline, never before
        assert lead["breach_detected_at"] > lead["sla_deadline"]
    # LF-005 has no late-logged follow-ups and no lead pending on an absent owner
    assert [c for c in changes if c["kind"] == "case_opened"] == []
