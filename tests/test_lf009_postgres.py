"""LF-009: SLA tracking saved to PostgreSQL (integration tests).

Runs against leadflow_eu_test only (see tests/pg_support.py); skipped without psycopg or
LEADFLOW_TEST_DSN.

- LF-005 with SLA tracking: every assigned lead's SLA and response-target outcome in the
  database at the cut-off matches the answer key; reconciliation balances (28 checks since LF-010).
- Every SLA scenario (T-01 to T-20, B-12, B-13, B-16, B-17) replayed through the database:
  the saved statuses, history, alerts, flags and owners match the reviewed answers, and
  the database refuses nothing.
- The same scenarios with a full restart (memory rebuilt from the database) before every
  step leave exactly the same rows.
"""
import json
from datetime import datetime

import pytest
from pg_support import DATASET, EXPECTED, RULES, SEED_FROM, SETTINGS, connect, rebuild, snapshot

from leadflow import ContactStore, postgres, reconcile
from leadflow import batch
from leadflow.postgres import Jsonb, key_uuid
from leadflow.reload import load_absences, load_store
from leadflow.sla import ALERT, LATE, SlaTracker
from test_lf009_sla import REPS, SLA_SCENARIOS, differences, steps_of


def iso(moment):
    return moment.astimezone(RULES.timezone).isoformat(timespec="seconds") if moment else None


@pytest.fixture(scope="module")
def lf005():
    conn = connect()
    rebuild(conn)
    batch.run(conn, DATASET, ContactStore(), RULES, SETTINGS, until=DATASET["metadata"]["sla_cutoff"])
    yield conn
    conn.close()


def test_lf005_outcomes_saved_at_cutoff(lf005):
    saved = {email: (status, target) for email, status, target in lf005.execute(
        """SELECT l.normalised_email, s.sla_status, s.response_target_status
           FROM sla_tracking s JOIN leads l ON l.lead_id = s.lead_id""").fetchall()}
    wanted = {lead["lead_email"]: (lead["sla_outcome"], lead["response_target_outcome"])
              for lead in EXPECTED["leads"] if lead["owner"]}
    assert saved == wanted


def test_lf005_history_and_reconciliation(lf005):
    breached = lf005.execute("SELECT count(*) FROM sla_tracking WHERE sla_status = 'breached'").fetchone()[0]
    spotted = lf005.execute("""SELECT count(*) FROM sla_history
                               WHERE event_type = 'status_changed' AND new_status = 'breached'""").fetchone()[0]
    assert breached == spotted == EXPECTED["summary"]["sla_outcomes_at_cutoff"]["breached"]
    checks = reconcile.reconcile(lf005, DATASET, RULES)
    assert len(checks) == 28
    assert [c for c in checks if c["difference"]] == []


# ---------------------------------------------------------------------------
# Scenarios through the database
# ---------------------------------------------------------------------------

def seed_scenario(conn, scenario):
    """Write the scenario's starting point: reference data, then each assigned lead as LF-007 would."""
    prior = scenario["prior_state"]
    settings = {"representatives": REPS, "initial_rotation": prior["round_robin_next"],
                "unavailability": list(prior.get("unavailability", []))}
    rebuild(conn, seed=False)
    postgres.seed_reference_data(conn, RULES, settings, SEED_FROM)
    for lead in prior["existing_leads"]:
        email, owner = lead["normalised_email"], lead["owner"]
        assigned = datetime.fromisoformat(lead["assigned_at"])
        deadline, target = datetime.fromisoformat(lead["sla_deadline"]), datetime.fromisoformat(lead["response_target_at"])
        lead_id, owner_id = key_uuid("lead", email), key_uuid("owner", owner)
        decision_id, assignment_id, sla_id = (key_uuid(k, email) for k in ("decision", "assignment", "sla"))
        conn.execute("""INSERT INTO leads (lead_id, normalised_email, business_country_code, first_contact_at,
                            created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s)""",
                     (lead_id, email, lead.get("country_code", "ES"), assigned, assigned, assigned))
        conn.execute("""INSERT INTO processing_decisions (decision_id, evaluation_key, lead_id, rule_version,
                            evaluated_at, input_snapshot, priority, decision_outcome, selected_owner_id, reason_codes,
                            decision_details)
                        VALUES (%s, %s, %s, %s, %s, '{}', %s, 'assignment_required', %s, %s, %s)""",
                     (decision_id, f"prior:{email}", lead_id, RULES.version, assigned, lead["priority"], owner_id,
                      ["SCENARIO_PRIOR_STATE"], Jsonb({"priority_rule": None})))
        conn.execute("""INSERT INTO assignments (assignment_id, assignment_key, lead_id, owner_id, decision_id,
                            assignment_method, assignment_reason, effective_from, recorded_at)
                        VALUES (%s, %s, %s, %s, %s, 'round_robin', 'Scenario starting point', %s, %s)""",
                     (assignment_id, f"prior:{email}", lead_id, owner_id, decision_id, assigned, assigned))
        followup = lead.get("first_qualifying_followup")
        first = datetime.fromisoformat(followup["at"]) if followup else None
        activity_id = None
        if followup:
            activity_id = key_uuid("activity", "scenario", email)
            conn.execute("""INSERT INTO followup_activities (activity_id, source_system, source_activity_id, lead_id,
                                performed_by_owner_id, activity_type, activity_outcome, is_automated, occurred_at,
                                recorded_at, activity_details)
                            VALUES (%s, 'scenario', %s, %s, %s, %s, 'unknown', FALSE, %s, %s, %s)""",
                         (activity_id, f"prior:{email}", lead_id, owner_id, followup.get("type", "call"), first, first,
                          Jsonb({"qualifying": True})))
        status = "pending" if first is None else ("met" if first <= deadline else "breached")
        target_status = "pending" if first is None else ("met" if first <= target else "missed")
        conn.execute("""INSERT INTO sla_tracking (sla_id, lead_id, initial_assignment_id, rule_version, initial_priority,
                            sla_started_at, original_deadline_at, current_deadline_at, sla_status, qualifying_activity_id,
                            qualifying_activity_at, last_evaluated_at, created_at, updated_at, response_target_priority,
                            original_response_target_at, current_response_target_at, response_target_status)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                     (sla_id, lead_id, assignment_id, RULES.version, lead["priority"], assigned, deadline, deadline,
                      status, activity_id, first, first or assigned, assigned, assigned, lead["priority"], target,
                      target, target_status))
        conn.execute("""INSERT INTO sla_history (sla_history_id, history_key, sla_id, decision_id, event_type,
                            new_status, new_deadline_at, change_reason, changed_by, change_details, recorded_at)
                        VALUES (%s, %s, %s, %s, 'sla_created', 'pending', %s, 'Scenario starting point', 'scenario',
                                '{}', %s)""",
                     (key_uuid("sla_history", email), f"prior:{email}", sla_id, decision_id, deadline, assigned))


def run_steps(conn, scenario, restart_every_step=False):
    def fresh():
        settings = load_absences(conn, {"representatives": REPS,
                                        "unavailability": list(scenario["prior_state"].get("unavailability", []))})
        return SlaTracker(load_store(conn, RULES, settings), RULES, settings)

    tracker = fresh()
    for number, step in enumerate(steps_of(scenario), start=1):
        if restart_every_step:
            tracker = fresh()
        kind = step["step"]
        if kind == "activity":
            postgres.track(conn, tracker, "activity", dict(step, source_system=scenario["input"]["source_system"],
                                                           activity_id=f"{scenario['input']['source_event_id']}-A{number}"))
        elif kind == "evaluate":
            postgres.track(conn, tracker, "advance", step["at"])
        elif kind == "absence":
            postgres.track(conn, tracker, "absence", {k: step[k] for k in ("rep", "from", "until", "recorded_at", "reason")})
        elif kind == "reassign":
            postgres.track(conn, tracker, "reassign", step["lead_email"], step["to"], step["at"], step["by"])
    if restart_every_step:
        tracker = fresh()
    postgres.track(conn, tracker, "advance", scenario["evaluation_time"])


def saved_result(conn, scenario):
    email = scenario["prior_state"]["existing_leads"][0]["normalised_email"]
    lead_id = key_uuid("lead", email)
    owner, status, target_status, deadline, target, first, detected = conn.execute(
        """SELECT o.staff_code, s.sla_status, s.response_target_status, s.current_deadline_at,
                  s.current_response_target_at, s.qualifying_activity_at, s.breach_detected_at
           FROM sla_tracking s
           JOIN assignments a ON a.lead_id = s.lead_id AND a.effective_to IS NULL
           JOIN owners o ON o.owner_id = a.owner_id WHERE s.lead_id = %s""", (lead_id,)).fetchone()
    result = {"owner": owner, "sla_deadline": iso(deadline), "sla_outcome": status,
              "breached_at": iso(deadline) if status == "breached" else None, "breach_detected_at": iso(detected),
              "qualifying_followup_at": iso(first), "late_followup": bool(first and first > deadline),
              "response_target_at": iso(target), "response_target_outcome": target_status}
    result["history"] = [{"at": iso(at), "event_type": kind, "previous_status": previous, "new_status": new}
                         for at, kind, previous, new in conn.execute(
                             """SELECT h.recorded_at, h.event_type, h.previous_status, h.new_status FROM sla_history h
                                JOIN sla_tracking s ON s.sla_id = h.sla_id
                                WHERE s.lead_id = %s AND h.event_type <> 'sla_created'
                                ORDER BY h.recorded_at, h.history_key""", (lead_id,)).fetchall()]
    cases = []
    for reason, lead_email, opened, details, status, resolved in conn.execute(
            """SELECT c.reason_code, l.normalised_email, c.opened_at, c.case_details, c.review_status, c.resolved_at
               FROM review_cases c JOIN leads l ON l.lead_id = c.lead_id
               WHERE c.reason_code IN (%s, %s) ORDER BY c.opened_at, l.normalised_email""", (ALERT, LATE)).fetchall():
        case = {"reason_code": reason, "lead_email": lead_email, "opened_at": iso(opened),
                "action_owner": details["action_owner"], "status": status}
        if reason == ALERT:
            case["suggested_owner"] = details["suggested_owner"]
        if details.get("note"):
            case["note"] = details["note"]
        if resolved:
            case["resolved_at"] = iso(resolved)
        cases.append(case)
    result["review_cases"] = cases
    return result


@pytest.fixture(scope="module")
def db():
    conn = connect()
    yield conn
    conn.close()


@pytest.mark.parametrize("path", SLA_SCENARIOS, ids=lambda p: p.stem)
def test_sla_scenario_in_database(db, path):
    scenario = json.loads(path.read_text(encoding="utf-8"))
    seed_scenario(db, scenario)
    run_steps(db, scenario)
    problems = differences(scenario["expected"], saved_result(db, scenario))
    assert not problems, "\n".join(problems)
    rows = snapshot(db)
    seed_scenario(db, scenario)
    run_steps(db, scenario, restart_every_step=True)
    assert snapshot(db) == rows, "restarting before every step changed what was saved"


def test_open_alert_survives_a_restart_before_reassignment(db):
    """T-16 with a check at 09:00: the alert is raised in one step and resolved after a restart."""
    scenario = json.loads((SLA_SCENARIOS[0].parent / "T-16.json").read_text(encoding="utf-8"))
    steps = scenario["input"]["steps"]
    steps.insert(1, {"step": "evaluate", "at": "2026-11-10T09:00:00+01:00"})
    seed_scenario(db, scenario)
    run_steps(db, scenario, restart_every_step=True)
    problems = differences(scenario["expected"], saved_result(db, scenario))
    assert not problems, "\n".join(problems)
    assert db.execute("SELECT count(*) FROM review_cases WHERE reason_code = 'MANUAL_REASSIGNMENT'").fetchone()[0] == 0


def test_failed_save_leaves_nothing_and_memory_unchanged(db):
    """Break the alert write while T-11's absence starts, then retry."""
    scenario = json.loads((SLA_SCENARIOS[0].parent / "T-11.json").read_text(encoding="utf-8"))
    seed_scenario(db, scenario)
    settings = {"representatives": REPS, "unavailability": []}
    tracker = SlaTracker(load_store(db, RULES, settings), RULES, settings)
    absence = {k: scenario["input"]["steps"][0][k] for k in ("rep", "from", "until", "recorded_at", "reason")}
    postgres.track(db, tracker, "absence", absence)
    before_rows, before_alerts, before_clock = snapshot(db), dict(tracker.store.alerts), tracker.store.clock
    original = postgres._save_sla_case

    def broken(*args, **kwargs):
        raise RuntimeError("simulated database failure")

    postgres._save_sla_case = broken
    try:
        with pytest.raises(RuntimeError):
            postgres.track(db, tracker, "advance", "2026-11-10T09:00:00+01:00")
    finally:
        postgres._save_sla_case = original
    assert snapshot(db) == before_rows
    assert (tracker.store.alerts, tracker.store.clock) == (before_alerts, before_clock)
    postgres.track(db, tracker, "advance", "2026-11-10T09:00:00+01:00")
    problems = differences(scenario["expected"], saved_result(db, scenario))
    assert not problems, "\n".join(problems)
