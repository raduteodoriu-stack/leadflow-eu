"""LF-008: restart safety and reconciliation (PostgreSQL integration tests).

Runs against leadflow_eu_test only (see tests/pg_support.py); skipped without psycopg or
LEADFLOW_TEST_DSN.

- The engine's working memory rebuilt from the database equals the memory of a run that
  never stopped.
- Stopping and reloading before EVERY event and follow-up of LF-005 gives exactly the
  same decisions and exactly the same database rows as one uninterrupted run.
- Repeats are still recognised after a restart, including events without an ID (DR-016).
- Reconciliation balances on a clean run, and reports each deliberately broken record.
"""
import copy
from datetime import datetime

import pytest
from pg_support import DATASET, EXPECTED, RULES, SETTINGS, connect, rebuild, snapshot

from leadflow import ContactStore, postgres
from leadflow import batch, reconcile
from leadflow.reload import load_store

ITEMS = len(batch.timeline(DATASET))


class Rollback(Exception):
    """Raised inside a transaction to undo a deliberate break."""


@pytest.fixture(scope="module")
def uninterrupted():
    conn = connect()
    rebuild(conn)
    store = ContactStore()
    decisions = batch.run(conn, DATASET, store, RULES, SETTINGS)
    yield conn, store, decisions, snapshot(conn)
    conn.close()


def comparable(store):
    """The store as plain data. Engagement actions: once per ID, compared as instants."""
    contacts = {}
    for email, record in store.contacts.items():
        record = copy.deepcopy(record)
        actions, seen = [], set()
        for action in record["engagement_events"]:
            key = action["id"] or (action["type"], action["occurred_at"])
            if key in seen:
                continue  # scoring counts a repeated ID once
            seen.add(key)
            actions.append((str(action["id"]), action["type"], datetime.fromisoformat(action["occurred_at"])))
        record["engagement_events"] = sorted(actions)
        contacts[email] = record
    return {"processed": store.processed, "payload_hashes": store.payload_hashes, "contacts": contacts,
            "crm_index": store.crm_index, "company_first": store.company_first, "rotation": store.rotation,
            "alerts": store.alerts, "clock": store.clock}


def test_reloaded_memory_equals_live_memory(uninterrupted):
    conn, live, _, _ = uninterrupted
    reloaded = comparable(load_store(conn, RULES, SETTINGS))
    expected = comparable(live)
    for part in expected:
        if part == "contacts":
            assert reloaded[part].keys() == expected[part].keys()
            problems = [f"{email}.{field}: {reloaded[part][email].get(field)!r} != {value!r}"
                        for email, record in expected[part].items() for field, value in record.items()
                        if reloaded[part][email].get(field) != value]
            assert not problems, "\n".join(problems[:20])
        else:
            assert reloaded[part] == expected[part], part


def test_decisions_still_match_answer_key(uninterrupted):
    _, _, decisions, _ = uninterrupted
    wrong = [e["seq"] for e in EXPECTED["events"]
             if (decisions[e["seq"]]["outcome"], decisions[e["seq"]].get("owner"))
             != (e["expected"]["outcome"], e["expected"].get("owner"))]
    assert not wrong


def test_repeats_recognised_after_restart(uninterrupted):
    conn, _, _, _ = uninterrupted
    before = snapshot(conn)
    try:
        with conn.transaction():  # undone at the end, so later tests see the clean run
            store = load_store(conn, RULES, SETTINGS)
            with_id = next(e for e in DATASET["events"] if e["input"].get("source_event_id"))
            _, decision = postgres.process_and_record(conn, with_id["input"], with_id["received_at"], store,
                                                      RULES, SETTINGS)
            assert decision["outcome"] == "duplicate_event_ignored"
            assert snapshot(conn) == before, "a repeat with an ID must write nothing"
            without_id = next(e for e in DATASET["events"] if not e["input"].get("source_event_id"))
            prepared, decision = postgres.process_and_record(
                conn, without_id["input"], "2026-11-06T17:00:00+01:00", store, RULES, SETTINGS)
            assert decision["outcome"] == "rejected"
            assert any("possible repeat" in w for w in prepared["warnings"]), prepared["warnings"]
            raise Rollback
    except Rollback:
        pass
    assert snapshot(conn) == before


def test_followups_saved_with_first_qualifying_time(uninterrupted):
    conn, _, _, _ = uninterrupted
    assert conn.execute("SELECT count(*) FROM followup_activities").fetchone()[0] == \
        len(DATASET["followup_activities"])
    first = dict(conn.execute(
        """SELECT l.normalised_email, extract(epoch FROM min(f.occurred_at))::bigint
           FROM followup_activities f JOIN leads l ON l.lead_id = f.lead_id
           WHERE (f.activity_details ->> 'qualifying')::boolean GROUP BY 1""").fetchall())
    wanted = {lead["lead_email"]: int(datetime.fromisoformat(lead["first_qualifying_followup_at"]).timestamp())
              for lead in EXPECTED["leads"] if lead.get("first_qualifying_followup_at")}
    assert first == wanted
    automated = conn.execute("""SELECT count(*) FROM followup_activities
                                WHERE is_automated AND (activity_details ->> 'qualifying')::boolean""").fetchone()[0]
    assert automated == 0


def test_reconciliation_balances(uninterrupted):
    conn, _, _, _ = uninterrupted
    checks = reconcile.reconcile(conn, DATASET, RULES)
    assert len(checks) == 28
    assert [c for c in checks if c["difference"]] == []
    totals = {c["id"]: c for c in checks}
    assert totals["S01"]["expected"] == 100


BREAKS = {
    "C07": "DELETE FROM sla_history WHERE sla_id = (SELECT min(sla_id::text)::uuid FROM sla_tracking); "
           "DELETE FROM sla_tracking WHERE sla_id = (SELECT min(sla_id::text)::uuid FROM sla_tracking)",
    "C06": "UPDATE assignments SET effective_to = effective_from + interval '1 hour' "
           "WHERE assignment_id = (SELECT min(assignment_id::text)::uuid FROM assignments)",
    "C11": "UPDATE routing_state SET last_assigned_owner_id = (SELECT owner_id FROM owners WHERE staff_code = 'SM-01') "
           "WHERE country_code = 'ES'",
    "C12": "INSERT INTO companies (company_name) VALUES ('Orphan Ltd')",
    "C09": "DELETE FROM review_cases WHERE review_case_id = (SELECT min(review_case_id::text)::uuid FROM review_cases "
           "WHERE case_details ->> 'queue' = 'unassigned_review')",
    "S05": "DELETE FROM followup_activities WHERE activity_id = (SELECT min(activity_id::text)::uuid "
           "FROM followup_activities)",
    "S07": "DELETE FROM engagement_events WHERE engagement_event_id = (SELECT min(engagement_event_id::text)::uuid "
           "FROM engagement_events)",
}


@pytest.mark.parametrize("check_id", sorted(BREAKS))
def test_reconciliation_reports_a_deliberate_break(uninterrupted, check_id):
    conn, _, _, _ = uninterrupted
    found = None
    try:
        with conn.transaction():
            for statement in BREAKS[check_id].split("; "):
                conn.execute(statement)
            found = {c["id"]: c["difference"] for c in reconcile.reconcile(conn, DATASET, RULES)}
            raise Rollback
    except Rollback:
        pass
    assert found[check_id] != 0, f"{check_id} did not report the break"
    assert [c for c in reconcile.reconcile(conn, DATASET, RULES) if c["difference"]] == [], "rollback failed"


def test_restart_before_every_item_changes_nothing(uninterrupted):
    """Kept last: it rebuilds the same database and must end with identical rows."""
    _, _, expected_decisions, expected_rows = uninterrupted
    conn = connect()
    try:
        rebuild(conn)
        decisions = {}
        for index in range(ITEMS):  # forget everything and reload from the database each time
            store = load_store(conn, RULES, SETTINGS)
            decisions.update(batch.run(conn, DATASET, store, RULES, SETTINGS, start=index, stop=index + 1))
        assert decisions == expected_decisions
        assert snapshot(conn) == expected_rows
    finally:
        conn.close()
