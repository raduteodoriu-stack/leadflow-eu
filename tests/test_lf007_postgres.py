"""LF-007 Phase B: decisions saved to PostgreSQL (integration tests).

These tests WIPE and rebuild the database they connect to, so they only run against a
database named leadflow_eu_test, given in the LEADFLOW_TEST_DSN environment variable, e.g.

    export LEADFLOW_TEST_DSN="dbname=leadflow_eu_test user=postgres"

They are skipped (not failed) when psycopg is not installed, the variable is not set or
the server cannot be reached, so the rest of the suite still runs anywhere.

What is checked: all 100 LF-005 events are processed by the engine and saved one
transaction per event; the saved rows match the reviewed answer keys; running the batch
again adds nothing; and a failed save leaves no partial rows and does not advance the
round-robin.
"""
import json
import os
import pathlib
from collections import Counter

import pytest

psycopg = pytest.importorskip("psycopg", reason="psycopg not installed (pip install -r requirements.txt)")

from leadflow import ContactStore, load_rules  # noqa: E402
from leadflow import postgres  # noqa: E402
from leadflow.decide import record_activity  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
RULES = load_rules()
DATASET = json.loads((ROOT / "data/synthetic/leads_100.json").read_text(encoding="utf-8"))
EXPECTED = json.loads((ROOT / "data/synthetic/expected_outcomes.json").read_text(encoding="utf-8"))
META = DATASET["metadata"]
SETTINGS = {"representatives": META["representatives"], "initial_rotation": META["initial_rotation"],
            "unavailability": META["unavailability"], "supplier_redirect_rules": META["supplier_redirect_rules"]}
SEED_FROM = "2026-10-01T00:00:00+02:00"
TABLES = ("ingestion_events", "companies", "leads", "engagement_events", "processing_decisions", "assignments",
          "sla_tracking", "sla_history", "review_cases", "participant_redirects", "owners",
          "owner_eligibility_history", "supplier_redirect_rules", "rule_versions")
EXPECTED_BY_SEQ = {e["seq"]: e["expected"] for e in EXPECTED["events"]}
SAVED = [e for e in EXPECTED["events"] if e["expected"]["outcome"] != "duplicate_event_ignored"]


def connect():
    dsn = os.environ.get("LEADFLOW_TEST_DSN")
    if not dsn:
        pytest.skip("LEADFLOW_TEST_DSN not set")
    try:
        conn = psycopg.connect(dsn, autocommit=True)
    except psycopg.OperationalError as error:
        pytest.skip(f"cannot reach PostgreSQL: {error}")
    name = conn.execute("SELECT current_database()").fetchone()[0]
    if name != "leadflow_eu_test":
        conn.close()
        pytest.fail(f"refusing to wipe database {name!r}: point LEADFLOW_TEST_DSN at leadflow_eu_test")
    return conn


def rebuild(conn):
    """Empty the test database and apply every migration in number order, then seed."""
    conn.execute("DROP SCHEMA IF EXISTS public CASCADE")
    conn.execute("CREATE SCHEMA public")
    for migration in sorted((ROOT / "SQL").glob("[0-9][0-9][0-9]_*.sql")):
        conn.execute(migration.read_text(encoding="utf-8"))
    postgres.seed_reference_data(conn, RULES, SETTINGS, SEED_FROM)


def timeline():
    """Events and follow-ups in time order (activity before event at the same minute)."""
    items = [(postgres._at(e["received_at"]), 1, i, "event", e) for i, e in enumerate(DATASET["events"])]
    items += [(postgres._at(a["occurred_at"]), 0, i, "activity", a)
              for i, a in enumerate(DATASET["followup_activities"])]
    return [(kind, item) for *_, kind, item in sorted(items, key=lambda x: x[:3])]


def run_batch(conn, store):
    decisions = {}
    for kind, item in timeline():
        if kind == "activity":
            record_activity(store, RULES, item)
        else:
            decisions[item["seq"]] = postgres.process_and_record(
                conn, item["input"], item["received_at"], store, RULES, SETTINGS)[1]
    return decisions


def counts(conn):
    return {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in TABLES}


def epoch(value):
    return int(postgres._at(value).timestamp())


@pytest.fixture(scope="module")
def db():
    conn = connect()
    rebuild(conn)
    store = ContactStore()
    decisions = run_batch(conn, store)
    yield conn, store, decisions
    conn.close()


def test_every_event_saved_once(db):
    conn, _, _ = db
    found = counts(conn)
    outcomes = Counter(e["expected"]["outcome"] for e in SAVED)
    assigned = outcomes["assigned"] + outcomes["assigned_to_company_owner"]
    assert found["ingestion_events"] == len(SAVED)  # the 3 replays are not stored again
    assert found["processing_decisions"] == len(SAVED)
    assert found["leads"] == sum(1 for e in SAVED if e["expected"].get("lead_created"))
    assert found["assignments"] == assigned
    methods = dict(conn.execute("SELECT assignment_method, count(*) FROM assignments GROUP BY 1").fetchall())
    assert methods == {k: v for k, v in (("round_robin", outcomes["assigned"]),
                                         ("same_company_owner", outcomes["assigned_to_company_owner"])) if v}
    assert found["sla_tracking"] == assigned
    assert found["participant_redirects"] == sum(
        1 for e in SAVED if e["expected"]["outcome"] == "redirected"
        or e["expected"].get("review_queue") == "participant_redirect_review")
    target_changes = sum(1 for e in SAVED if (e["expected"].get("response_target") or {}).get("target_changed"))
    history = dict(conn.execute("SELECT event_type, count(*) FROM sla_history GROUP BY event_type").fetchall())
    assert history == {"sla_created": assigned, **({"response_target_shortened": target_changes}
                                                    if target_changes else {})}
    assert found["engagement_events"] > 0
    orphans = conn.execute("SELECT count(*) FROM companies c WHERE NOT EXISTS "
                           "(SELECT 1 FROM leads l WHERE l.company_id = c.company_id)").fetchone()[0]
    assert orphans == 0


def test_processing_status_matches_outcome(db):
    conn, _, _ = db
    wanted = Counter({"assigned": "processed", "assigned_to_company_owner": "processed",
                      "existing_owner_kept": "processed", "attached_to_existing_contact": "processed",
                      "review": "review_required", "redirected": "redirected", "rejected": "rejected"}
                     [e["expected"]["outcome"]] for e in SAVED)
    found = dict(conn.execute("SELECT processing_status, count(*) FROM ingestion_events GROUP BY 1").fetchall())
    assert found == dict(wanted)
    bad = conn.execute("SELECT count(*) FROM ingestion_events WHERE processing_status = 'rejected' "
                       "AND error_code IS DISTINCT FROM 'SOURCE_EVENT_INVALID'").fetchone()[0]
    assert bad == 0


def test_saved_decisions_match_answer_key(db):
    conn, _, _ = db
    rows = conn.execute(
        """SELECT d.decision_details ->> 'outcome', d.decision_outcome, d.priority, to_jsonb(d.reason_codes),
                  o.staff_code, e.source_event_id, e.received_at
           FROM processing_decisions d
           JOIN ingestion_events e ON e.ingestion_event_id = d.ingestion_event_id
           LEFT JOIN owners o ON o.owner_id = d.selected_owner_id""").fetchall()
    saved = {(source_id, int(received.timestamp())): row for *row, source_id, received in rows}
    problems = []
    for item in SAVED:
        exp = item["expected"]
        key = (item["source_event_id"] or None, epoch(item["received_at"]))
        if key not in saved:
            problems.append(f"event {item['seq']}: no decision row")
            continue
        outcome, db_outcome, priority, codes, owner = saved[key]
        if outcome != exp["outcome"] or db_outcome != postgres.OUTCOME_TO_DB[exp["outcome"]]:
            problems.append(f"event {item['seq']}: outcome {outcome}/{db_outcome} != {exp['outcome']}")
        if priority != exp.get("priority"):
            problems.append(f"event {item['seq']}: priority {priority} != {exp.get('priority')}")
        if set(codes) != set(exp["reason_codes"]):
            problems.append(f"event {item['seq']}: reason codes {sorted(codes)} != {sorted(exp['reason_codes'])}")
        if exp["outcome"] in postgres.ASSIGNMENT_METHOD and owner != exp["owner"]:
            problems.append(f"event {item['seq']}: owner {owner} != {exp['owner']}")
    assert not problems, "\n".join(problems)


def test_lead_ownership_sla_and_target_match_answer_key(db):
    conn, _, _ = db
    rows = conn.execute(
        """SELECT l.normalised_email, o.staff_code, a.assignment_method, a.effective_from, s.initial_priority,
                  s.original_deadline_at, s.current_deadline_at, s.current_response_target_at,
                  s.response_target_priority, s.sla_status
           FROM sla_tracking s
           JOIN leads l ON l.lead_id = s.lead_id
           JOIN assignments a ON a.assignment_id = s.initial_assignment_id
           JOIN owners o ON o.owner_id = a.owner_id""").fetchall()
    saved = {row[0]: row[1:] for row in rows}
    problems = []
    assigned = [lead for lead in EXPECTED["leads"] if lead["owner"]]
    assert len(saved) == len(assigned)
    for lead in assigned:
        email = lead["lead_email"]
        if email not in saved:
            problems.append(f"{email}: no SLA row")
            continue
        owner, method, start, initial, deadline, current, target, target_priority, status = saved[email]
        checks = [("owner", owner, lead["owner"]), ("assigned_at", int(start.timestamp()), epoch(lead["assigned_at"])),
                  ("initial_priority", initial, lead["initial_priority"]),
                  ("sla_deadline", int(deadline.timestamp()), epoch(lead["sla_deadline"])),
                  ("deadline unchanged", current, deadline),
                  ("response_target_at", int(target.timestamp()), epoch(lead["response_target_at"])),
                  ("status (LF-009 evaluates met/breached)", status, "pending")]
        if not lead["target_changes"]:
            checks.append(("target priority", target_priority, lead["initial_priority"]))
        problems += [f"{email}: {name} {mine} != {want}" for name, mine, want in checks if mine != want]
    assert not problems, "\n".join(problems)


def test_round_robin_position_saved(db):
    conn, store, _ = db
    found = dict(conn.execute("""SELECT r.country_code, o.staff_code FROM routing_state r
                                 LEFT JOIN owners o ON o.owner_id = r.last_assigned_owner_id""").fetchall())
    last = dict(META["initial_rotation"])
    for country, first in META["initial_rotation"].items():  # before any event: the rep before the first one
        reps = sorted(META["representatives"][country])
        last[country] = reps[reps.index(first) - 1]
    for item in EXPECTED["events"]:
        if item["expected"]["outcome"] == "assigned" and item["expected"].get("round_robin_advanced"):
            last[item["expected"]["country_code"]] = item["expected"]["owner"]
    assert found == last
    for country, rep in found.items():  # the engine's next pointer follows the saved last rep
        reps = sorted(META["representatives"][country])
        assert store.rotation[country] == reps[(reps.index(rep) + 1) % len(reps)]


def test_review_cases_opened(db):
    conn, _, _ = db
    found = Counter(dict(conn.execute(
        "SELECT case_details ->> 'queue', count(*) FROM review_cases GROUP BY 1").fetchall()))
    wanted = Counter()
    for item in SAVED:
        exp = item["expected"]
        if exp.get("review_queue"):
            wanted[exp["review_queue"]] += 1
        if exp.get("parallel_review"):
            wanted["parallel_review"] += 1
    assert found == wanted
    parallel = Counter(dict(conn.execute("SELECT reason_code, count(*) FROM review_cases "
                                         "WHERE case_details ->> 'queue' = 'parallel_review' GROUP BY 1").fetchall()))
    assert parallel == Counter(e["expected"]["parallel_review"]["reason_code"]
                               for e in SAVED if e["expected"].get("parallel_review"))


def test_participant_referrals_are_simulations_only(db):
    conn, _, _ = db
    rows = conn.execute("""SELECT attempt_status, supplier_code_snapshot, error_code,
                                  attempt_details ->> 'personal_data_transferred'
                           FROM participant_redirects""").fetchall()
    assert rows
    for status, supplier, error, transferred in rows:
        assert transferred == "false"
        assert (status, error) in (("simulated", None), ("review_required", "NO_REDIRECT_RULE"))
        assert (supplier is not None) == (status == "simulated")


def test_running_the_batch_again_adds_nothing(db):
    conn, _, _ = db
    before = counts(conn)
    routing = conn.execute("SELECT country_code, last_assigned_owner_id FROM routing_state ORDER BY 1").fetchall()
    run_batch(conn, ContactStore())
    assert counts(conn) == before
    assert conn.execute("SELECT country_code, last_assigned_owner_id FROM routing_state ORDER BY 1").fetchall() \
        == routing


def test_failed_save_leaves_nothing_and_does_not_advance_rotation():
    """Break the assignment write for one round-robin lead, then retry it."""
    conn = connect()
    try:
        rebuild(conn)
        store = ContactStore()
        items = timeline()
        target = next(item["seq"] for kind, item in items
                      if kind == "event" and EXPECTED_BY_SEQ[item["seq"]]["outcome"] == "assigned"
                      and item["seq"] > 5)
        original = postgres._write_assignment
        for kind, item in items:
            if kind == "activity":
                record_activity(store, RULES, item)
                continue
            if item["seq"] == target:
                break
            postgres.process_and_record(conn, item["input"], item["received_at"], store, RULES, SETTINGS)
        before_rows, before_rotation = counts(conn), dict(store.rotation)

        def broken(*args, **kwargs):
            raise RuntimeError("simulated database failure")

        postgres._write_assignment = broken
        try:
            with pytest.raises(RuntimeError):
                postgres.process_and_record(conn, item["input"], item["received_at"], store, RULES, SETTINGS)
        finally:
            postgres._write_assignment = original
        assert counts(conn) == before_rows, "a failed save must not leave partial rows"
        assert store.rotation == before_rotation, "round-robin must not advance for an unsaved lead"
        system = item["input"]["source_system"].lower()
        assert not store.was_processed(system, item["input"]["source_event_id"]), "retry must not look like a replay"

        _, decision = postgres.process_and_record(conn, item["input"], item["received_at"], store, RULES, SETTINGS)
        expected = EXPECTED_BY_SEQ[target]
        assert (decision["outcome"], decision["owner"]) == (expected["outcome"], expected["owner"])
        assert decision["round_robin_next_after"] == expected["round_robin_next_after"]
        after = counts(conn)
        assert after["assignments"] == before_rows["assignments"] + 1
        assert after["ingestion_events"] == before_rows["ingestion_events"] + 1
    finally:
        conn.close()
