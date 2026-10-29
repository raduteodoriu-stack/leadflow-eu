"""LF-010 Phase A: CRM write-back, simulated (PostgreSQL integration tests).

Runs against leadflow_eu_test only (see tests/pg_support.py); skipped without psycopg or
LEADFLOW_TEST_DSN.

- LF-005 with the simulated writer: every contact gets exactly the values LeadFlow
  decided, only changed values are sent, nothing is confirmed twice, and running the
  batch again after a restart writes nothing new.
- Failure handling with a fake CRM (the real HubSpot client arrives in Phase B): rate
  limits and server errors retried with waits, validation errors sent to RevOps, no
  answer checked by reading back before any resend, a crash mid-call recovered, a newer
  change superseding a waiting update, retries given up after 5 attempts, and nothing
  secret stored.
"""
from datetime import datetime, timedelta

import pytest
from pg_support import DATASET, RULES, SETTINGS, connect, rebuild, snapshot

from leadflow import ContactStore, batch, reconcile
from leadflow.crm import MAX_ATTEMPTS, CrmWriter, Result, sanitise
from leadflow.postgres import key_uuid
from leadflow.reload import load_store

CUTOFF = DATASET["metadata"]["sla_cutoff"]
LATER = datetime.fromisoformat("2026-11-09T10:00:00+01:00")


class Rollback(Exception):
    pass


class FakeCrm:
    """A CRM that answers from a script: 200, 429, 400, 500, 'timeout', 'timeout-applied' or 'crash'."""

    mode = "fake"

    def __init__(self, *answers):
        self.answers, self.sent, self.contacts = list(answers), [], {}

    def send(self, target, id_property, properties):
        self.sent.append((target, dict(properties)))
        answer = self.answers.pop(0) if self.answers else 200
        if answer == "crash":
            raise ConnectionError("process stopped mid-call")
        if answer in (200, "timeout-applied"):
            self.contacts.setdefault(target, {}).update(properties)
        if answer in ("timeout", "timeout-applied"):
            return Result(timeout=True)
        body = {"status": "error", "category": "VALIDATION_ERROR", "message": "Property values were not valid",
                "headers": {"Authorization": "Bearer pat-secret"}, "token": "pat-secret"} if answer == 400 else {}
        return Result(status=answer, body=body)

    def read(self, target, id_property, names):
        return dict(self.contacts.get(target, {}))


def checks_by_id(conn):
    return {c["id"]: c["difference"] for c in reconcile.reconcile(conn, DATASET, RULES)}


@pytest.fixture(scope="module")
def simulated():
    conn = connect()
    rebuild(conn)
    batch.run(conn, DATASET, ContactStore(), RULES, SETTINGS, until=CUTOFF)
    yield conn
    conn.close()


def test_every_contact_shows_what_leadflow_decided(simulated):
    statuses = {s for (s,) in simulated.execute("SELECT DISTINCT attempt_status FROM crm_write_log").fetchall()}
    assert statuses == {"simulated"}
    contacts = simulated.execute("SELECT count(*) FROM crm_desired_contact_state").fetchone()[0]
    updated = simulated.execute("SELECT count(DISTINCT target_record_id) FROM crm_write_log").fetchone()[0]
    assert contacts == updated == 76
    attempts, logical = simulated.execute(
        "SELECT count(*), count(DISTINCT logical_update_id) FROM crm_write_log").fetchone()
    assert attempts == logical  # one attempt per intended update when nothing fails
    checks = checks_by_id(simulated)
    assert len(checks) == 28
    assert {k: v for k, v in checks.items() if v} == {}


def test_only_changed_values_are_sent(simulated):
    rows = simulated.execute("""SELECT target_record_id, request_payload -> 'properties' FROM crm_write_log
                                ORDER BY target_record_id, completed_at, logical_update_id""").fetchall()
    shown, problems = {}, []
    for target, properties in rows:
        state = shown.setdefault(target, {})
        for name, value in properties.items():
            if state.get(name, "") == value:
                problems.append(f"{target}: {name}={value!r} sent again")
            state[name] = value
    assert not problems, "\n".join(problems[:10])


def test_running_again_sends_nothing(simulated):
    """After a restart (memory rebuilt from the database), re-running the whole batch writes nothing new."""
    before = snapshot(simulated)
    CrmWriter().sync_all(simulated, LATER)
    store = load_store(simulated, RULES, SETTINGS)
    batch.run(simulated, DATASET, store, RULES, SETTINGS, until=CUTOFF)
    assert snapshot(simulated) == before


# ---------------------------------------------------------------------------
# Failure handling, on LF-005 processed without CRM writes; each test is rolled back
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def no_crm():
    conn = connect()
    rebuild(conn)
    batch.run(conn, DATASET, ContactStore(), RULES, SETTINGS, until=CUTOFF, crm=None)
    lead = conn.execute("""SELECT normalised_email FROM crm_desired_contact_state
                           WHERE properties ? 'leadflow_owner' ORDER BY normalised_email LIMIT 1""").fetchone()[0]
    yield conn, lead
    conn.close()


def in_rollback(conn, body):
    try:
        with conn.transaction():
            body()
            raise Rollback
    except Rollback:
        pass


def attempts(conn, lead):
    return conn.execute(
        """SELECT w.attempt_number, w.attempt_status, w.http_status_code, w.is_retryable, w.next_retry_at,
                  w.error_code, w.response_details
           FROM crm_write_log w JOIN crm_desired_contact_state d ON d.target_record_id = w.target_record_id
           WHERE d.normalised_email = %s ORDER BY w.started_at, w.attempt_number""", (lead,)).fetchall()


def review_cases(conn, lead):
    return conn.execute("""SELECT c.case_details ->> 'action_owner', c.case_details ->> 'error_code'
                           FROM review_cases c JOIN leads l ON l.lead_id = c.lead_id
                           WHERE l.normalised_email = %s AND c.reason_code = 'CRM_WRITE_FAILED'""",
                        (lead,)).fetchall()


def test_rate_limit_waits_then_retries(no_crm):
    conn, lead = no_crm

    def body():
        crm = FakeCrm(429, 200)
        writer = CrmWriter(crm)
        writer.sync(conn, {lead: LATER})
        first = attempts(conn, lead)
        assert [(a[1], a[2], a[3]) for a in first] == [("failed", 429, True)]
        assert first[0][4] == LATER + timedelta(minutes=1)
        writer.sync(conn, {lead: LATER + timedelta(seconds=30)})  # too early: nothing sent
        assert len(crm.sent) == 1
        writer.sync(conn, {lead: LATER + timedelta(minutes=1)})
        assert [(a[0], a[1]) for a in attempts(conn, lead)] == [(1, "failed"), (2, "succeeded")]
        assert crm.sent[0] == crm.sent[1]  # the same update, sent again
        assert checks_by_id(conn)["C20"] == 0
    in_rollback(conn, body)


def test_validation_error_goes_to_revops_and_is_not_resent(no_crm):
    conn, lead = no_crm

    def body():
        crm = FakeCrm(400)
        writer = CrmWriter(crm)
        writer.sync(conn, {lead: LATER})
        writer.sync(conn, {lead: LATER + timedelta(hours=1)})
        assert len(crm.sent) == 1
        assert [(a[1], a[2], a[3], a[5]) for a in attempts(conn, lead)] == \
            [("failed", 400, False, "CRM_VALIDATION_ERROR")]
        assert review_cases(conn, lead) == [("revops", "CRM_VALIDATION_ERROR")]
        assert checks_by_id(conn)["C21"] == 0
    in_rollback(conn, body)


def test_no_answer_is_checked_by_reading_back_before_any_resend(no_crm):
    conn, lead = no_crm

    def body():
        crm = FakeCrm("timeout-applied")
        writer = CrmWriter(crm)
        writer.sync(conn, {lead: LATER})
        assert [a[1] for a in attempts(conn, lead)] == ["unknown"]
        writer.sync(conn, {lead: LATER + timedelta(minutes=5)})
        rows = attempts(conn, lead)
        assert [(a[1], a[2]) for a in rows] == [("unknown", None), ("succeeded", 200)]
        assert rows[1][6] == {"verified_by_read": True}
        assert len(crm.sent) == 1  # never sent twice
    in_rollback(conn, body)


def test_no_answer_and_not_applied_is_sent_again(no_crm):
    conn, lead = no_crm

    def body():
        crm = FakeCrm("timeout", 200)
        writer = CrmWriter(crm)
        writer.sync(conn, {lead: LATER})
        writer.sync(conn, {lead: LATER + timedelta(minutes=5)})
        assert [(a[0], a[1]) for a in attempts(conn, lead)] == [(1, "unknown"), (2, "succeeded")]
        assert len(crm.sent) == 2
    in_rollback(conn, body)


def test_crash_mid_call_is_recovered_without_double_write(no_crm):
    conn, lead = no_crm

    def body():
        crm = FakeCrm("crash")
        with pytest.raises(ConnectionError):
            CrmWriter(crm).sync(conn, {lead: LATER})
        assert [a[1] for a in attempts(conn, lead)] == ["in_progress"]
        crm.contacts.clear()  # the call never reached the CRM
        CrmWriter(crm).sync(conn, {lead: LATER + timedelta(minutes=5)})
        assert [(a[0], a[1]) for a in attempts(conn, lead)] == [(1, "unknown"), (2, "succeeded")]
    in_rollback(conn, body)


def test_newer_change_supersedes_a_waiting_update(no_crm):
    conn, lead = no_crm

    def body():
        crm = FakeCrm(429, 200)
        writer = CrmWriter(crm)
        writer.sync(conn, {lead: LATER})
        lead_id = key_uuid("lead", lead)
        conn.execute("""INSERT INTO review_cases (case_key, lead_id, reason_code, case_details, opened_at, updated_at)
                        VALUES (%s, %s, 'TEST_REASON', '{}', %s, %s)""", (f"test:{lead}", lead_id, LATER, LATER))
        writer.sync(conn, {lead: LATER + timedelta(minutes=2)})
        rows = attempts(conn, lead)
        assert [(a[0], a[1]) for a in rows] == [(1, "failed"), (1, "succeeded")]
        assert rows[0][4] is None and "superseded_at" in rows[0][6]
        assert crm.sent[1][1]["leadflow_review_reason"] == "TEST_REASON"
        assert set(crm.sent[0][1]) < set(crm.sent[1][1])  # carries every value not yet confirmed
        checks = checks_by_id(conn)
        assert (checks["C20"], checks["C21"]) == (0, 0)
    in_rollback(conn, body)


def test_retries_given_up_after_five_attempts(no_crm):
    conn, lead = no_crm

    def body():
        crm = FakeCrm(*[500] * MAX_ATTEMPTS)
        writer = CrmWriter(crm)
        at = LATER
        for _ in range(MAX_ATTEMPTS):
            writer.sync(conn, {lead: at})
            nxt = attempts(conn, lead)[-1][4]
            at = nxt or at + timedelta(hours=2)
        rows = attempts(conn, lead)
        assert [a[0] for a in rows] == list(range(1, MAX_ATTEMPTS + 1))
        waits = [(rows[i + 1][4] - rows[i][4]) if rows[i + 1][4] else None for i in range(MAX_ATTEMPTS - 1)]
        assert [w for w in waits if w] == [timedelta(minutes=5), timedelta(minutes=15), timedelta(minutes=60)]
        assert (rows[-1][1], rows[-1][3]) == ("failed", False)
        assert review_cases(conn, lead) == [("revops", "CRM_SERVER_ERROR")]
        writer.sync(conn, {lead: at + timedelta(days=1)})
        assert len(crm.sent) == MAX_ATTEMPTS
        checks = checks_by_id(conn)
        assert checks["C21"] == 0 and checks["C19"] > 0  # the contact is honestly reported as not up to date
    in_rollback(conn, body)


def test_nothing_secret_is_stored(no_crm):
    conn, lead = no_crm
    assert sanitise({"headers": {"Authorization": "Bearer x"}, "token": "x", "status": "error"}) == {"status": "error"}

    def body():
        CrmWriter(FakeCrm(400)).sync(conn, {lead: LATER})
        text = conn.execute("SELECT string_agg(request_payload::TEXT || response_details::TEXT, ' ') "
                            "FROM crm_write_log").fetchone()[0]
        assert "pat-secret" not in text and "Bearer" not in text and "Authorization" not in text
    in_rollback(conn, body)
