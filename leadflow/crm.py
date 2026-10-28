"""LF-010: write LeadFlow's decisions back to the CRM, safely.

For each lead, the database view `crm_desired_contact_state` (migration 005) says what
the CRM contact should show: owner, priority, SLA deadline and status, response target
and outcome, open review reasons. The writer compares that with the values last
CONFIRMED in the CRM and sends only the difference. An unchanged contact gets nothing.

Every intended update is one LOGICAL UPDATE (`logical_update_id`), and every try at it is
one row in `crm_write_log` (attempt 1, 2, ...). The order follows the database design:

1. Record the attempt as `in_progress` (committed) before calling the CRM.
2. Call the CRM (outside any database transaction).
3. Record the result: `succeeded`, `failed` (with a retry time if retrying makes sense),
   `unknown` (no answer: checked before anything is sent again) or `simulated`.

So a crash in the middle leaves an `in_progress` row, which the next run treats like
`unknown`: it reads the contact back before deciding whether to send again. Nothing is
written twice, and nothing is lost.

Phase A (this release) uses SimulatedTransport: attempts are logged as `simulated` with
the exact payload that would be sent; no CRM is contacted. Phase B adds a HubSpot
transport with the same `send` / `read` methods.

Failure rules:
- 429 (rate limit) and 5xx: retried with growing waits (1, 5, 15, 60 minutes), up to
  5 attempts; then given up and sent to RevOps (`CRM_WRITE_FAILED`).
- Other 4xx (e.g. a validation error): not retried; sent to RevOps straight away.
- No answer (timeout): `unknown`; next run reads the contact back, records success if it
  already shows the values, otherwise sends again.
- A newer change for the same contact supersedes an update still waiting to retry: the new
  update carries every value not yet confirmed, and the old one stops retrying.
- Nothing secret is stored: the payload holds only contact properties, and response
  details keep only a short list of safe fields (never headers or tokens).
"""
from __future__ import annotations

import hashlib
import json
from datetime import timedelta

from psycopg.types.json import Jsonb

from leadflow.postgres import key_uuid

TARGET_SYSTEM = "hubspot"
OBJECT_TYPE = "contact"
BACKOFF_MINUTES = (1, 5, 15, 60)
MAX_ATTEMPTS = 5
REVIEW_REASON = "CRM_WRITE_FAILED"
SAFE_RESPONSE_FIELDS = ("status", "category", "message", "correlationId", "errorType", "policyName")
FINAL = ("succeeded", "simulated")


class Result:
    """What the CRM answered. status=None and timeout=True means no answer at all."""

    def __init__(self, status=None, body=None, timeout=False):
        self.status, self.body, self.timeout = status, body or {}, timeout


class SimulatedTransport:
    """Phase A: never contacts a CRM. The writer logs `simulated` attempts."""

    mode = "simulation"

    def send(self, target_record_id, id_property, properties):
        return None

    def read(self, target_record_id, id_property, names):
        return None


def sanitise(body):
    """Keep only safe, short response fields; never headers, tokens or contact data."""
    if not isinstance(body, dict):
        return {}
    kept = {k: body[k] for k in SAFE_RESPONSE_FIELDS if k in body}
    if isinstance(kept.get("message"), str):
        kept["message"] = kept["message"][:300]
    return kept


class CrmWriter:
    def __init__(self, transport=None):
        self.transport = transport or SimulatedTransport()

    # ------------------------------------------------------------------ public
    def sync(self, conn, leads):
        """Bring each lead's CRM contact up to date. `leads` = {lead email: moment}."""
        for lead_key, at in sorted(leads.items()):
            self._sync_lead(conn, lead_key, at)

    def sync_all(self, conn, at):
        """Retry what is due and update every contact that differs (e.g. after a restart)."""
        keys = [k for (k,) in conn.execute("SELECT normalised_email FROM crm_desired_contact_state").fetchall()]
        self.sync(conn, {k: at for k in keys})

    # ------------------------------------------------------------------ one lead
    def _sync_lead(self, conn, lead_key, at):
        row = conn.execute("""SELECT target_record_id, id_property, latest_decision_id, properties
                              FROM crm_desired_contact_state WHERE normalised_email = %s""", (lead_key,)).fetchone()
        if row is None:
            return
        target, id_property, decision_id, desired = row
        latest = self._latest(conn, target)
        waiting = None  # the newest update, if it is still to be retried or verified
        if latest is not None:
            logical, attempt, status, payload, next_retry, retryable = latest
            if status in ("unknown", "in_progress"):
                if not self._verify(conn, logical, attempt, target, id_property, payload, decision_id, at):
                    waiting = latest
            elif status == "failed" and retryable and next_retry is not None:
                if next_retry > at:
                    return  # waiting to retry; nothing new is sent before then
                waiting = latest
        confirmed = self._confirmed(conn, target)
        changes = {name: desired.get(name, "") for name in sorted(set(desired) | set(confirmed))
                   if desired.get(name, "") != confirmed.get(name, "")}
        if waiting is not None:
            logical, attempt, _, payload, _, _ = waiting
            if changes == payload:  # the waiting update is still exactly right: try it again
                self._attempt(conn, logical, attempt + 1, target, id_property, payload, decision_id, at)
                return
            self._supersede(conn, logical, attempt, at)
        elif latest is not None and latest[2] == "failed" and changes == latest[3]:
            return  # the CRM refused exactly this: RevOps has the case; sending it again would fail again
        if not changes:
            return
        digest = hashlib.sha256(json.dumps(changes, sort_keys=True).encode()).hexdigest()[:16]
        logical = key_uuid("crm_update", target, at.isoformat(), digest)
        self._attempt(conn, logical, 1, target, id_property, changes, decision_id, at)

    def _confirmed(self, conn, target):
        """Values the CRM is known to show: every confirmed update applied in order."""
        state = {}
        for (payload,) in conn.execute(
                """SELECT request_payload FROM crm_write_log
                   WHERE target_system = %s AND target_record_id = %s AND attempt_status IN ('succeeded', 'simulated')
                   ORDER BY completed_at, logical_update_id""", (TARGET_SYSTEM, target)).fetchall():
            state.update(payload["properties"])
        return {k: v for k, v in state.items() if v != ""}

    def _latest(self, conn, target):
        """The newest attempt for this contact, or None."""
        row = conn.execute(
            """SELECT logical_update_id, attempt_number, attempt_status, request_payload, next_retry_at, is_retryable
               FROM crm_write_log WHERE target_system = %s AND target_record_id = %s
               ORDER BY started_at DESC, attempt_number DESC LIMIT 1""", (TARGET_SYSTEM, target)).fetchone()
        if row is None:
            return None
        logical, attempt, status, payload, next_retry, retryable = row
        return logical, attempt, status, payload["properties"], next_retry, retryable

    # ------------------------------------------------------------------ attempts
    def _attempt(self, conn, logical, number, target, id_property, properties, decision_id, at):
        attempt_id = key_uuid("crm_attempt", logical, number)
        payload = {"id_property": id_property, "properties": properties}
        conn.execute(  # 1. intent, committed before the CRM is called
            """INSERT INTO crm_write_log (write_attempt_id, logical_update_id, attempt_number, decision_id, target_system,
                   target_object_type, target_record_id, request_payload, attempt_status, started_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'in_progress', %s)
               ON CONFLICT (logical_update_id, attempt_number) DO NOTHING""",
            (attempt_id, logical, number, decision_id, TARGET_SYSTEM, OBJECT_TYPE, target, Jsonb(payload), at))
        result = self.transport.send(target, id_property, properties)  # 2. the CRM call
        self._record(conn, attempt_id, logical, number, decision_id, result, at)  # 3. the result

    def _record(self, conn, attempt_id, logical, number, decision_id, result, at):
        if result is None:
            status, http, retry, next_retry, code, details = "simulated", None, None, None, None, \
                {"mode": self.transport.mode}
        elif result.timeout:
            status, http, retry, next_retry, code, details = "unknown", None, True, None, "CRM_TIMEOUT", \
                {"note": "no answer; contact is read back before any resend"}
        elif 200 <= result.status <= 299:
            status, http, retry, next_retry, code, details = "succeeded", result.status, None, None, None, \
                sanitise(result.body)
        else:
            retryable = result.status == 429 or result.status >= 500
            gave_up = retryable and number >= MAX_ATTEMPTS
            status, http, code, details = "failed", result.status, \
                ("CRM_RATE_LIMITED" if result.status == 429 else
                 "CRM_SERVER_ERROR" if result.status >= 500 else "CRM_VALIDATION_ERROR"), sanitise(result.body)
            retry = retryable and not gave_up
            next_retry = at + timedelta(minutes=BACKOFF_MINUTES[min(number, len(BACKOFF_MINUTES)) - 1]) \
                if retry else None
            if not retry:
                details["gave_up_after_attempts" if gave_up else "not_retryable"] = number if gave_up else True
        conn.execute(
            """UPDATE crm_write_log SET attempt_status = %s, completed_at = %s, http_status_code = %s,
                   is_retryable = %s, next_retry_at = %s, error_code = %s, response_details = %s
               WHERE write_attempt_id = %s AND attempt_status = 'in_progress'""",
            (status, at, http, retry, next_retry, code, Jsonb(details), attempt_id))
        if status == "failed" and not retry:
            self._review_case(conn, logical, decision_id, code, number, at)

    def _verify(self, conn, logical, attempt, target, id_property, payload, decision_id, at):
        """After no answer (or a crash mid-call): read the contact back before sending anything again.

        Returns True if the CRM already shows the values (recorded as a success).
        """
        attempt_id = key_uuid("crm_attempt", logical, attempt)
        conn.execute("""UPDATE crm_write_log SET attempt_status = 'unknown', completed_at = %s, is_retryable = TRUE,
                            error_code = 'CRM_NO_RESULT', response_details = %s
                        WHERE write_attempt_id = %s AND attempt_status = 'in_progress'""",
                     (at, Jsonb({"note": "interrupted before the result was recorded"}), attempt_id))
        shown = self.transport.read(target, id_property, sorted(payload))
        if shown is None or any(str(shown.get(k, "")) != str(v) for k, v in payload.items()):
            return False
        verified = key_uuid("crm_attempt", logical, attempt + 1)
        conn.execute(
            """INSERT INTO crm_write_log (write_attempt_id, logical_update_id, attempt_number, decision_id, target_system,
                   target_object_type, target_record_id, request_payload, attempt_status, started_at, completed_at,
                   http_status_code, response_details)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'succeeded', %s, %s, 200, %s)
               ON CONFLICT (logical_update_id, attempt_number) DO NOTHING""",
            (verified, logical, attempt + 1, decision_id, TARGET_SYSTEM, OBJECT_TYPE, target,
             Jsonb({"id_property": id_property, "properties": payload}), at, at,
             Jsonb({"verified_by_read": True})))
        return True

    def _supersede(self, conn, logical, attempt, at):
        """A newer change replaces an update still waiting: it stops retrying, with the reason kept."""
        conn.execute("""UPDATE crm_write_log SET next_retry_at = NULL, is_retryable = FALSE,
                            response_details = response_details || %s
                        WHERE logical_update_id = %s AND attempt_number = %s""",
                     (Jsonb({"superseded_at": at.isoformat()}), logical, attempt))

    def _review_case(self, conn, logical, decision_id, code, attempts, at):
        lead_id = conn.execute("SELECT lead_id FROM processing_decisions WHERE decision_id = %s",
                               (decision_id,)).fetchone()[0]
        key = f"{REVIEW_REASON}:{logical}"
        conn.execute(
            """INSERT INTO review_cases (review_case_id, case_key, lead_id, decision_id, reason_code, case_details,
                   review_status, opened_at, updated_at)
               VALUES (%s, %s, %s, %s, %s, %s, 'open', %s, %s) ON CONFLICT (case_key) DO NOTHING""",
            (key_uuid("case", key), key, lead_id, decision_id, REVIEW_REASON,
             Jsonb({"queue": "crm_review", "action_owner": "revops", "error_code": code, "attempts": attempts,
                    "logical_update_id": str(logical)}), at, at))
