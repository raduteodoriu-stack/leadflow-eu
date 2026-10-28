"""LF-007 Phase B: save each decision to PostgreSQL.

The engine (LF-006 + LF-007 Phase A) decides in memory; this module records what it
decided, one database transaction per inbound event:

    ingestion_events, companies, leads, engagement_events, processing_decisions,
    assignments, routing_state, sla_tracking + sla_history, review_cases,
    participant_redirects

Design rules
- All or nothing: if any write fails, the transaction rolls back AND the in-memory
  store is put back as it was, so the round-robin pointer never advances for a lead
  that was not saved, and a retry is not mistaken for a duplicate.
- Repeats write nothing new: a replayed event (same source system + event ID) only
  produces the in-memory "duplicate_event_ignored" decision. Every row also has a
  deterministic ID or key, and inserts use ON CONFLICT DO NOTHING, so running the
  same batch twice cannot create duplicate rows. (Loading the store back from the
  database and reconciling counts is LF-008.)
- Simulated time: every timestamp is set from the event's received time, never from
  the database clock, so results are reproducible.
- Follow-up calls and emails, SLA statuses, alerts, absences and reassignments are saved
  through `track` (LF-008, LF-009), from the changes the SLA tracker reports.
- Out of scope here: CRM writes (LF-010), review actions (people do those).

Requires psycopg 3 (`pip install -r requirements.txt`).
"""
from __future__ import annotations

import copy
import uuid
from datetime import datetime

from psycopg.types.json import Jsonb

from leadflow.decide import process_event

NAMESPACE = uuid.UUID("6f1c6f43-2b38-4f7e-9a4e-1f0c4c7d2a10")  # fixed: same input -> same IDs
ENGINE = "leadflow-engine"
SALES_MANAGER = "SM-01"
APPROVER = "Radu Teodoriu"
RULES_APPROVED_AT = "2026-10-23T12:00:00+02:00"

OUTCOME_TO_DB = {
    "assigned": "assignment_required",
    "assigned_to_company_owner": "assignment_required",
    "review": "review_required",
    "redirected": "redirection_required",
    "rejected": "rejection_required",
    "existing_owner_kept": "no_change",
    "attached_to_existing_contact": "no_change",
}
ASSIGNMENT_METHOD = {"assigned": "round_robin", "assigned_to_company_owner": "same_company_owner"}
COMPANY_FIELDS = ("industry_code", "employee_band_declared", "research_use_case", "research_frequency",
                  "uses_digital_research_tools", "integration_required", "technical_resource_available",
                  "adoption_owner_confirmed", "onboarding_support_needed", "adoption_interest_confirmed",
                  "adoption_unwilling_or_unable")


def key_uuid(*parts):
    """Deterministic UUID for a business key, so retries reuse the same row ID."""
    return uuid.uuid5(NAMESPACE, "|".join(str(p) for p in parts))


def _at(value):
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


# ---------------------------------------------------------------------------
# Reference data: rule version, owners, eligibility, routing start, supplier rules
# ---------------------------------------------------------------------------

def seed_reference_data(conn, rules, settings, effective_from):
    """Write the reference data the decisions point at. Safe to run more than once.

    effective_from -- when the owners and supplier rules start to apply (simulated time)
    """
    start = _at(effective_from)
    reps = settings.get("representatives") or {}
    with conn.transaction():
        conn.execute(
            """INSERT INTO rule_versions (rule_version, description, rule_config, approved_by, approved_at,
                                          created_at)
               VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (rule_version) DO NOTHING""",
            (rules.version, "LF-002 business rules v1.0 (option C SLA, decision 2026-10-23)", Jsonb(rules.data),
             APPROVER, _at(RULES_APPROVED_AT), _at(RULES_APPROVED_AT)))
        manager = key_uuid("owner", SALES_MANAGER)
        conn.execute(
            """INSERT INTO owners (owner_id, staff_code, display_name, owner_role, created_at)
               VALUES (%s, %s, %s, 'sales_manager', %s) ON CONFLICT (owner_id) DO NOTHING""",
            (manager, SALES_MANAGER, "Sales Manager (synthetic)", start))
        for country, codes in sorted(reps.items()):
            for code in codes:
                conn.execute(
                    """INSERT INTO owners (owner_id, staff_code, display_name, owner_role, manager_id, created_at)
                       VALUES (%s, %s, %s, 'sales_rep', %s, %s) ON CONFLICT (owner_id) DO NOTHING""",
                    (key_uuid("owner", code), code, f"Sales Rep {code} (synthetic)", manager, start))
                for period_from, period_to, eligible, reason in _eligibility_periods(
                        code, start, settings.get("unavailability") or ()):
                    conn.execute(
                        """INSERT INTO owner_eligibility_history (eligibility_id, owner_id, country_code,
                               is_eligible, effective_from, effective_to, change_reason, recorded_at)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (eligibility_id) DO NOTHING""",
                        (key_uuid("eligibility", code, period_from.isoformat()), key_uuid("owner", code),
                         country, eligible, period_from, period_to, reason, start))
            # routing_state stores the LAST rep assigned; the engine keeps the NEXT one to try.
            # Only set when empty, so re-seeding never rewinds a rotation already in use.
            first = (settings.get("initial_rotation") or {}).get(country)
            ordered = sorted(codes)
            last = ordered[ordered.index(first) - 1] if first in ordered else None
            conn.execute(
                """UPDATE routing_state SET last_assigned_owner_id = %s, updated_at = %s
                   WHERE country_code = %s AND last_assigned_owner_id IS NULL""",
                (key_uuid("owner", last) if last else None, start, country))
        for territory, rule in sorted((settings.get("supplier_redirect_rules") or {}).items()):
            conn.execute(
                """INSERT INTO supplier_redirect_rules (redirect_rule_id, rule_key, territory_code, supplier_code,
                       supplier_name, destination_url, effective_from, change_reason, approved_by, approved_at,
                       created_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (rule_key) DO NOTHING""",
                (_redirect_rule_id(territory, rule), f"{territory}:{rule['supplier_code']}:{start.date()}",
                 territory, rule["supplier_code"], rule["supplier_name"], rule["destination_url"], start,
                 "Synthetic supplier for LF-005", APPROVER, start, start))


def _eligibility_periods(rep, start, unavailability):
    """Split a rep's time into eligible / not eligible periods ('[)' ranges, last one open)."""
    periods, cursor = [], start
    for item in sorted((u for u in unavailability if u["rep"] == rep), key=lambda u: _at(u["from"])):
        begin, end = max(_at(item["from"]), start), _at(item.get("until"))
        if begin > cursor:
            periods.append((cursor, begin, True, "Available for new leads"))
        periods.append((begin, end, False, item.get("reason") or "Unavailable"))
        if end is None:
            return periods
        cursor = end
    periods.append((cursor, None, True, "Available for new leads" if not periods else "Available again"))
    return periods


def _redirect_rule_id(territory, rule):
    return key_uuid("redirect_rule", territory, rule["supplier_code"])


# ---------------------------------------------------------------------------
# One event
# ---------------------------------------------------------------------------

def process_and_record(conn, raw, received_at, store, rules, settings=None, calendar=None):
    """Decide one event in memory, then save it in ONE transaction.

    Returns (prepared, decision). If saving fails, the store is restored and the
    error is raised again, so the event can be retried as if it never arrived.
    """
    before = copy.deepcopy(store.__dict__)
    prepared, decision = process_event(raw, received_at, store, rules, settings, calendar)
    try:
        with conn.transaction():
            record_decision(conn, raw, prepared, decision, store, rules)
    except Exception:
        store.__dict__.clear()
        store.__dict__.update(before)
        raise
    return prepared, decision


def record_decision(conn, raw, prepared, decision, store, rules):
    """Write the rows for one decision. Call inside a transaction."""
    if decision["outcome"] == "duplicate_event_ignored":
        return  # LF-002 step 1: a repeat is not stored again and makes no new decision
    t = _at(prepared["event"]["received_at"])
    identity = prepared.get("identity") or {}
    lead_key = None
    if identity.get("match") not in (None, "unresolved"):  # a new contact's key is its own email
        lead_key = identity.get("lead_key") or prepared["contact"]["normalised_email"]
    lead = store.contact(lead_key) if lead_key else None
    event_id = _write_ingestion_event(conn, raw, prepared, decision, t)
    lead_id = None
    if lead is not None:
        lead_id = key_uuid("lead", lead_key)
        if identity.get("match") == "new":
            _write_lead(conn, raw, lead, lead_id, t)
        conn.execute("UPDATE ingestion_events SET lead_id = %s WHERE ingestion_event_id = %s", (lead_id, event_id))
        _write_engagement(conn, prepared, lead_id, t)
    decision_id = _write_decision(conn, prepared, decision, event_id, lead_id, rules, t)
    if decision["outcome"] in ASSIGNMENT_METHOD:
        _write_assignment(conn, decision, lead, lead_id, decision_id, event_id, rules, t)
    target = decision.get("response_target") or {}
    if target.get("target_changed"):
        _write_target_shortened(conn, decision, lead, lead_id, decision_id, t)
    _write_review_cases(conn, decision, event_id, lead_id, decision_id, rules, t)
    if prepared["status"] == "participant":
        _write_participant_redirect(conn, prepared, decision, event_id, t)


def _processing_status(decision):
    outcome = decision["outcome"]
    if outcome == "rejected":
        return "rejected"
    if outcome == "redirected":
        return "redirected"
    if outcome == "review":
        return "review_required"
    return "processed"


def _write_ingestion_event(conn, raw, prepared, decision, t):
    event = prepared["event"]
    system = event["source_system"] or "unknown"
    if event["source_event_id"]:
        event_id = key_uuid("event", system, event["source_event_id"])
    else:  # no ID: the payload fingerprint plus arrival time identifies this delivery (DR-016)
        event_id = key_uuid("event-without-id", event["payload_hash"], event["received_at"])
    event_type = event["event_type"] if event["event_type"] in ("lead_created", "lead_updated") else None
    status = _processing_status(decision)
    conn.execute(
        """INSERT INTO ingestion_events (ingestion_event_id, source_system, source_event_id, source_record_id,
               event_type, source_occurred_at, received_at, raw_payload, processing_status, error_code,
               error_detail, processed_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (ingestion_event_id) DO NOTHING""",
        (event_id, system, event["source_event_id"], raw.get("crm_contact_id"), event_type,
         _at(event["occurred_at"]), t, Jsonb(raw), status, decision.get("error_code"),
         ("; ".join(prepared["warnings"]) or None) if status == "rejected" else None, t))
    return event_id


def _write_lead(conn, raw, lead, lead_id, t):
    company_id = None
    company = lead.get("company")
    if company:
        domain = company.get("company_domain")
        company_id = key_uuid("company", domain) if domain else key_uuid("company-of-lead", lead["lead_key"])
        values = [company.get(f) for f in COMPANY_FIELDS]
        conn.execute(
            f"""INSERT INTO companies (company_id, company_name, company_domain, {", ".join(COMPANY_FIELDS)},
                    created_at, updated_at)
                VALUES ({", ".join(["%s"] * (len(COMPANY_FIELDS) + 5))}) ON CONFLICT (company_id) DO NOTHING""",
            [company_id, company.get("company_name"), domain] + values + [t, t])
    conn.execute(
        """INSERT INTO leads (lead_id, company_id, crm_contact_id, normalised_email, first_name, last_name,
               business_country_code, relationship_type, first_contact_at, created_at, updated_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (lead_id) DO NOTHING""",
        (lead_id, company_id, lead.get("crm_contact_id"), lead["lead_key"], raw.get("first_name"),
         raw.get("last_name"), lead.get("country_code"), lead.get("relationship") or "unknown",
         lead["first_contact_at"], t, t))


def _write_engagement(conn, prepared, lead_id, t):
    system = prepared["event"]["source_system"]
    for index, item in enumerate((prepared.get("engagement") or {}).get("events", [])):
        if not item.get("occurred_at"):
            continue  # cannot be placed in time, so it can never count in a score
        source_id = item.get("id")
        details = {"received_with_event": prepared["event"]["source_event_id"]}
        if not source_id:  # keep it, under a stand-in ID, so a reload still sees it (LF-008)
            source_id = f"{prepared['event']['source_event_id']}#{index}"
            details["source_id_missing"] = True
        conn.execute(
            """INSERT INTO engagement_events (engagement_event_id, source_system, source_event_id, lead_id,
                   event_type, occurred_at, recorded_at, event_details)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (source_system, source_event_id) DO NOTHING""",
            (key_uuid("engagement", system, source_id), system, source_id, lead_id, item["type"],
             _at(item["occurred_at"]), t, Jsonb(details)))


def _write_decision(conn, prepared, decision, event_id, lead_id, rules, t):
    evaluation_key = f"{event_id}:{rules.version}"
    decision_id = key_uuid("decision", evaluation_key)
    fit, engagement = decision.get("fit") or {}, decision.get("engagement") or {}
    owner = decision.get("owner") if decision["outcome"] in ASSIGNMENT_METHOD else None
    conn.execute(
        """INSERT INTO processing_decisions (decision_id, evaluation_key, ingestion_event_id, lead_id, rule_version,
               evaluated_at, input_snapshot, fit_score, engagement_score, fit_data_complete,
               engagement_data_complete, priority, decision_outcome, selected_owner_id, reason_codes,
               decision_details)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT (evaluation_key) DO NOTHING""",
        (decision_id, evaluation_key, event_id, lead_id, rules.version, t, Jsonb(prepared),
         fit.get("total"), engagement.get("total"), fit.get("status") == "complete",
         bool(engagement) and engagement.get("status") != "unknown", decision.get("priority"),
         OUTCOME_TO_DB[decision["outcome"]], key_uuid("owner", owner) if owner else None,
         list(decision["reason_codes"]), Jsonb(decision)))
    return decision_id


def _write_assignment(conn, decision, lead, lead_id, decision_id, event_id, rules, t):
    owner_id = key_uuid("owner", decision["owner"])
    assignment_id = key_uuid("assignment", event_id)
    method = ASSIGNMENT_METHOD[decision["outcome"]]
    conn.execute(
        """INSERT INTO assignments (assignment_id, assignment_key, lead_id, owner_id, decision_id,
               assignment_method, assignment_reason, effective_from, recorded_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (assignment_key) DO NOTHING""",
        (assignment_id, f"assign:{event_id}", lead_id, owner_id, decision_id, method,
         "Round-robin by country" if method == "round_robin" else "SAME_COMPANY_RECENT_CONTACT", t, t))
    if decision.get("round_robin_advanced"):
        conn.execute("UPDATE routing_state SET last_assigned_owner_id = %s, updated_at = %s WHERE country_code = %s",
                     (owner_id, t, decision["country_code"]))
    sla, target = decision["sla"], decision["response_target"]
    sla_id = key_uuid("sla", lead["lead_key"])
    deadline, target_at = _at(sla["deadline"]), _at(target["target_at"])
    conn.execute(
        """INSERT INTO sla_tracking (sla_id, lead_id, initial_assignment_id, rule_version, initial_priority,
               sla_started_at, original_deadline_at, current_deadline_at, sla_status, last_evaluated_at,
               created_at, updated_at, response_target_priority, original_response_target_at,
               current_response_target_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'pending', %s, %s, %s, %s, %s, %s)
           ON CONFLICT (lead_id) DO NOTHING""",
        (sla_id, lead_id, assignment_id, rules.version, decision["priority"], t, deadline, deadline, t, t, t,
         target["priority"], target_at, target_at))
    conn.execute(
        """INSERT INTO sla_history (sla_history_id, history_key, sla_id, decision_id, event_type, previous_status,
               new_status, previous_deadline_at, new_deadline_at, change_reason, changed_by, change_details,
               recorded_at)
           VALUES (%s, %s, %s, %s, 'sla_created', NULL, 'pending', NULL, %s, %s, %s, %s, %s)
           ON CONFLICT (history_key) DO NOTHING""",
        (key_uuid("sla_history", f"sla_created:{sla_id}"), f"sla_created:{sla_id}", sla_id, decision_id, deadline, "Lead assigned: 8-business-hour SLA started",
         ENGINE, Jsonb({"owner": decision["owner"], "priority": decision["priority"],
                        "business_clock_starts": sla.get("business_clock_starts"),
                        "response_target": target}), t))


def _write_target_shortened(conn, decision, lead, lead_id, decision_id, t):
    target = decision["response_target"]
    sla_id = key_uuid("sla", lead["lead_key"])
    row = conn.execute("SELECT sla_status, current_deadline_at FROM sla_tracking WHERE sla_id = %s",
                       (sla_id,)).fetchone()
    if row is None:  # lead assigned before this database existed: nothing to shorten here
        return
    status, deadline = row
    conn.execute(
        """UPDATE sla_tracking SET response_target_priority = %s, current_response_target_at = %s, updated_at = %s
           WHERE sla_id = %s AND current_response_target_at > %s""",
        (target["priority"], _at(target["target_at"]), t, sla_id, _at(target["target_at"])))
    conn.execute(
        """INSERT INTO sla_history (sla_history_id, history_key, sla_id, decision_id, event_type, previous_status,
               new_status, previous_deadline_at, new_deadline_at, change_reason, changed_by, change_details,
               recorded_at)
           VALUES (%s, %s, %s, %s, 'response_target_shortened', %s, %s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT (history_key) DO NOTHING""",
        (key_uuid("sla_history", f"target:{decision_id}"), f"target:{decision_id}", sla_id, decision_id, status, status, deadline, deadline,
         "Priority increased before first follow-up: response target shortened (SLA deadline unchanged)",
         ENGINE, Jsonb({"previous_priority": target["previous_priority"], "new_priority": target["priority"],
                        "previous_target_at": target["previous_target_at"], "new_target_at": target["target_at"]}),
         t))


def _review_cases(decision, rules):
    """(reason_code, queue, action_owner) for every case this decision opens."""
    routing = rules.data["review_routing"]
    cases = []
    queue = decision.get("review_queue")
    if queue:
        codes = decision["reason_codes"]
        if queue == routing["participant_queue"]:
            code = "NO_REDIRECT_RULE"
        else:
            code = next((c for c in codes if c in routing["action_owner_by_code"]), codes[0])
        cases.append((code, queue, decision.get("action_owner")))
    parallel = decision.get("parallel_review")
    if parallel:
        cases.append((parallel["reason_code"], "parallel_review", parallel["action_owner"]))
    return cases


def _write_review_cases(conn, decision, event_id, lead_id, decision_id, rules, t):
    for code, queue, action_owner in _review_cases(decision, rules):
        conn.execute(
            """INSERT INTO review_cases (review_case_id, case_key, ingestion_event_id, lead_id, decision_id,
                   reason_code, case_details, review_status, opened_at, updated_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, 'open', %s, %s) ON CONFLICT (case_key) DO NOTHING""",
            (key_uuid("case", event_id, code), f"case:{event_id}:{code}", event_id, lead_id, decision_id, code,
             Jsonb({"queue": queue, "action_owner": action_owner, "reason_codes": decision["reason_codes"],
                    "priority_shown_while_waiting": decision.get("priority")}), t, t))


def _write_participant_redirect(conn, prepared, decision, event_id, t):
    referral = decision["referral"]
    rule = prepared.get("redirect_rule")
    country = prepared["country"]["code"]
    simulated = referral["attempt_status"] == "simulated"
    conn.execute(
        """INSERT INTO participant_redirects (redirect_attempt_id, ingestion_event_id, redirect_rule_id,
               attempt_number, supplier_code_snapshot, supplier_name_snapshot, destination_url_snapshot,
               referral_method, attempt_status, attempted_at, error_code, attempt_details)
           VALUES (%s, %s, %s, 1, %s, %s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT (ingestion_event_id, attempt_number) DO NOTHING""",
        (key_uuid("redirect", event_id, 1), event_id, _redirect_rule_id(country, rule) if simulated else None,
         rule["supplier_code"] if simulated else None, rule["supplier_name"] if simulated else None,
         rule["destination_url"] if simulated else None, referral["referral_method"], referral["attempt_status"],
         t, referral.get("error_code"),
         Jsonb({"personal_data_transferred": False, "note": "MVP simulation: no reply sent (DR-007)"})))


# ---------------------------------------------------------------------------
# SLA tracking: follow-ups, statuses, alerts, absences, reassignment (LF-008, LF-009)
# ---------------------------------------------------------------------------

ACTIVITY_TYPES = ("call", "email", "administrative", "other")
SLA_QUEUE = "sla_review"
REASSIGNMENT = "MANUAL_REASSIGNMENT"
HISTORY_REASONS = {
    ("status_changed", "met"): "First qualifying follow-up on or before the deadline",
    ("status_changed", "breached"): "Deadline passed without a qualifying follow-up",
    ("evidence_corrected", "met"): "Follow-up logged late but made before the deadline: verdict corrected",
    ("followup_recorded", "breached"): "Follow-up made after the deadline: breach stands",
    ("followup_recorded", "met"): "Earlier follow-up logged late: SLA still met",
}


def track(conn, tracker, action, *args):
    """Run one SLA tracker action (advance, activity, absence, reassign) and save its changes.

    All or nothing: if saving fails, the store and the list of absences are put back.
    Returns the changes.
    """
    store = tracker.store
    before = copy.deepcopy(store.__dict__)
    absences = list(tracker.settings["unavailability"])
    changes = getattr(tracker, action)(*args)
    try:
        with conn.transaction():
            apply_sla_changes(conn, changes, store, tracker.rules)
    except Exception:
        store.__dict__.clear()
        store.__dict__.update(before)
        tracker.settings["unavailability"][:] = absences
        raise
    return changes


def apply_sla_changes(conn, changes, store, rules):
    """Write the tracker's changes. Call inside a transaction."""
    for change in changes:
        kind = change["kind"]
        if kind == "activity":
            _save_activity(conn, change["activity"], change["lead_key"], change["qualifying"])
        elif kind in ("status", "target"):
            _save_sla_state(conn, change)
        elif kind == "case_opened":
            _save_sla_case(conn, change)
        elif kind == "absence":
            _save_absence(conn, change["absence"])
        elif kind == "owner_changed":
            _save_reassignment(conn, change, store, rules)


def _save_activity(conn, activity, lead_key, qualifying):
    """Every follow-up is stored, qualifying or not. recorded_at = when it was logged."""
    email = (activity.get("lead_email") or "").strip().lower()
    kind = activity.get("type") if activity.get("type") in ACTIVITY_TYPES else "other"
    occurred = _at(activity["occurred_at"])
    logged = _at(activity.get("logged_at")) or occurred
    conn.execute(
        """INSERT INTO followup_activities (activity_id, source_system, source_activity_id, lead_id,
               performed_by_owner_id, source_contact_id, source_owner_id, activity_type, activity_outcome,
               is_automated, occurred_at, recorded_at, activity_details)
           VALUES (%s, %s, %s, %s, (SELECT owner_id FROM owners WHERE staff_code = %s), %s, %s, %s,
                   'unknown', %s, %s, %s, %s)
           ON CONFLICT (source_system, source_activity_id) DO NOTHING""",
        (_activity_id(activity), activity["source_system"], activity["activity_id"],
         key_uuid("lead", lead_key) if lead_key else None, activity.get("owner"),
         None if lead_key else (email or None), activity.get("owner"), kind, activity.get("automated"),
         occurred, logged, Jsonb({"qualifying": qualifying, "lead_email": email or None})))


def _activity_id(activity):
    return key_uuid("activity", activity["source_system"], activity["activity_id"])


def _save_sla_state(conn, change):
    """Bring the lead's SLA row to the state recorded in the change; add history for status changes."""
    state, at, lead_id = change["state"], change["at"], key_uuid("lead", change["lead_key"])
    activity = change.get("activity") if change["kind"] == "status" else None
    conn.execute(
        """UPDATE sla_tracking SET sla_status = %s, response_target_status = %s,
               breach_detected_at = %s,
               qualifying_activity_id = COALESCE(%s, qualifying_activity_id),
               qualifying_activity_at = COALESCE(%s, qualifying_activity_at),
               last_evaluated_at = %s, updated_at = %s
           WHERE lead_id = %s""",
        (state["sla_status"], state["response_target_status"], state["breach_detected_at"],
         _activity_id(activity) if activity else None, state["first_followup_at"] if activity else None,
         at, at, lead_id))
    if change["kind"] != "status":
        return
    row = conn.execute("SELECT sla_id, current_deadline_at FROM sla_tracking WHERE lead_id = %s",
                       (lead_id,)).fetchone()
    sla_id, deadline = row
    history_key = f"{change['event_type']}:{change['lead_key']}:{at.isoformat()}" + \
        (f":{activity['activity_id']}" if activity else "")
    conn.execute(
        """INSERT INTO sla_history (sla_history_id, history_key, sla_id, activity_id, event_type, previous_status,
               new_status, previous_deadline_at, new_deadline_at, change_reason, changed_by, change_details,
               recorded_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (history_key) DO NOTHING""",
        (key_uuid("sla_history", history_key), history_key, sla_id, _activity_id(activity) if activity else None,
         change["event_type"], change["previous_status"], change["new_status"], deadline, deadline,
         HISTORY_REASONS.get((change["event_type"], change["new_status"]), "SLA re-evaluated"), ENGINE,
         Jsonb({"response_target_status": state["response_target_status"],
                "breach_detected_at": _iso(state["breach_detected_at"]),
                "qualifying_followup_at": _iso(state["first_followup_at"])}), at))


def _iso(moment):
    return moment.isoformat(timespec="seconds") if moment else None


def _save_sla_case(conn, change):
    details = {k: v for k, v in change.items() if k not in ("kind", "key", "lead_key", "at", "reason_code")}
    conn.execute(
        """INSERT INTO review_cases (review_case_id, case_key, lead_id, reason_code, case_details, review_status,
               opened_at, updated_at)
           VALUES (%s, %s, %s, %s, %s, 'open', %s, %s) ON CONFLICT (case_key) DO NOTHING""",
        (key_uuid("case", change["key"]), change["key"], key_uuid("lead", change["lead_key"]), change["reason_code"],
         Jsonb(dict(details, queue=SLA_QUEUE)), change["at"], change["at"]))


def _save_absence(conn, absence):
    """Split the salesperson's eligibility: available until `from`, away until `until`, then available."""
    rep, starts, until = absence["rep"], _at(absence["from"]), _at(absence.get("until"))
    recorded = _at(absence.get("recorded_at")) or starts
    owner_id = key_uuid("owner", rep)
    if conn.execute("""SELECT 1 FROM owner_eligibility_history
                       WHERE owner_id = %s AND NOT is_eligible AND effective_from = %s""",
                    (owner_id, starts)).fetchone():
        return  # already recorded
    row = conn.execute(
        """SELECT eligibility_id, country_code, is_eligible, effective_from, effective_to
           FROM owner_eligibility_history
           WHERE owner_id = %s AND effective_from <= %s AND (effective_to IS NULL OR effective_to > %s)""",
        (owner_id, starts, starts)).fetchone()
    if row is None or not row[2]:
        raise ValueError(f"cannot record an absence for {rep} from {starts}: not in an available period")
    eligibility_id, country, _, period_from, period_to = row
    if until is not None and period_to is not None and until > period_to:
        raise ValueError(f"absence for {rep} runs past the end of their current period ({period_to})")
    if period_from < starts:
        conn.execute("UPDATE owner_eligibility_history SET effective_to = %s WHERE eligibility_id = %s",
                     (starts, eligibility_id))
    else:
        conn.execute("DELETE FROM owner_eligibility_history WHERE eligibility_id = %s", (eligibility_id,))
    periods = [(starts, until, False, absence.get("reason") or "Unavailable")]
    if until is not None and (period_to is None or until < period_to):
        periods.append((until, period_to, True, "Available again"))
    for period_from_, period_to_, eligible, reason in periods:
        conn.execute(
            """INSERT INTO owner_eligibility_history (eligibility_id, owner_id, country_code, is_eligible,
                   effective_from, effective_to, change_reason, recorded_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (key_uuid("eligibility", rep, period_from_.isoformat()), owner_id, country, eligible, period_from_,
             period_to_, reason, recorded))


def _save_reassignment(conn, change, store, rules):
    """A Sales Manager moves a lead: a decision, a review action, the old assignment closed, a new one opened."""
    lead_key, at, new_owner = change["lead_key"], change["at"], change["new_owner"]
    lead = store.contact(lead_key)
    lead_id, owner_id = key_uuid("lead", lead_key), key_uuid("owner", new_owner)
    key = f"reassign:{lead_key}:{at.isoformat()}"
    decision_id = key_uuid("decision", key)
    conn.execute(
        """INSERT INTO processing_decisions (decision_id, evaluation_key, lead_id, rule_version, evaluated_at,
               input_snapshot, priority, decision_outcome, selected_owner_id, reason_codes, decision_details)
           VALUES (%s, %s, %s, %s, %s, %s, %s, 'assignment_required', %s, %s, %s)
           ON CONFLICT (evaluation_key) DO NOTHING""",
        (decision_id, key, lead_id, rules.version, at,
         Jsonb({"previous_owner": change["previous_owner"], "requested_by": change["by"]}), lead.get("priority"),
         owner_id, [REASSIGNMENT],
         Jsonb({"outcome": "reassigned", "owner": new_owner, "previous_owner": change["previous_owner"],
                "priority": lead.get("priority"), "priority_rule": lead.get("priority_rule"),
                "sla_deadline_kept": _iso(lead.get("sla_deadline")),
                "resolved_alerts": change["resolved_alerts"]})))
    if change["resolved_alerts"]:
        case_key = change["resolved_alerts"][0]
        conn.execute("""UPDATE review_cases SET review_status = 'resolved', resolved_at = %s, updated_at = %s
                        WHERE case_key = ANY(%s) AND review_status <> 'resolved'""",
                     (at, at, change["resolved_alerts"]))
    else:  # a reassignment with no alert behind it still leaves a reviewable trail
        case_key = f"{REASSIGNMENT}:{lead_key}:{at.isoformat()}"
        conn.execute(
            """INSERT INTO review_cases (review_case_id, case_key, lead_id, decision_id, reason_code, case_details,
                   review_status, assigned_reviewer, opened_at, updated_at, resolved_at)
               VALUES (%s, %s, %s, %s, %s, %s, 'resolved', %s, %s, %s, %s) ON CONFLICT (case_key) DO NOTHING""",
            (key_uuid("case", case_key), case_key, lead_id, decision_id, REASSIGNMENT,
             Jsonb({"queue": SLA_QUEUE, "action_owner": "sales_manager"}), change["by"], at, at, at))
    action_key = f"owner_selected:{lead_key}:{at.isoformat()}"
    action_id = key_uuid("review_action", action_key)
    conn.execute(
        """INSERT INTO review_actions (review_action_id, action_key, review_case_id, performed_by, performed_at,
               action_type, action_reason, action_details, selected_owner_id)
           VALUES (%s, %s, %s, %s, %s, 'owner_selected', %s, %s, %s) ON CONFLICT (action_key) DO NOTHING""",
        (action_id, action_key, key_uuid("case", case_key), change["by"], at,
         "Lead reassigned by the Sales Manager; SLA deadline and target kept",
         Jsonb({"previous_owner": change["previous_owner"], "new_owner": new_owner}), owner_id))
    conn.execute("""UPDATE assignments SET effective_to = %s
                    WHERE lead_id = %s AND effective_to IS NULL AND effective_from < %s""", (at, lead_id, at))
    conn.execute(
        """INSERT INTO assignments (assignment_id, assignment_key, lead_id, owner_id, decision_id, review_action_id,
               assignment_method, assignment_reason, effective_from, recorded_at)
           VALUES (%s, %s, %s, %s, %s, %s, 'manual_review', %s, %s, %s) ON CONFLICT (assignment_key) DO NOTHING""",
        (key_uuid("assignment", key), key, lead_id, owner_id, decision_id, action_id,
         "Reassigned by the Sales Manager", at, at))
