"""LF-008: rebuild the engine's working memory (ContactStore) from PostgreSQL.

While it runs, the engine keeps what it knows in memory: which events it has handled,
each contact and its owner, priority, deadlines and engagement, and whose turn it is in
each country. `load_store` rebuilds all of that from the database, so after a restart
the engine carries on exactly where it stopped. The restart test in
tests/test_lf008_reload.py proves it: stopping and reloading before every single event
and follow-up gives the same decisions and the same rows as one uninterrupted run.

Times come back from the database as instants; they are converted to the rules' time
zone (Europe/Madrid) so the engine sees them exactly as it wrote them.
"""
from __future__ import annotations

from leadflow.identity import ContactStore
from leadflow.validate import payload_hash

READINESS_COLUMNS = ("uses_digital_research_tools", "integration_required", "technical_resource_available",
                     "adoption_owner_confirmed", "onboarding_support_needed", "adoption_interest_confirmed",
                     "adoption_unwilling_or_unable")
CONTROLLED_COLUMNS = ("industry_code", "employee_band_declared", "research_use_case", "research_frequency")


def load_store(conn, rules, settings=None):
    """Return a ContactStore holding everything the engine needs to continue."""
    settings = settings or {}
    tz = rules.timezone

    def local(moment):
        return moment.astimezone(tz) if moment is not None else None

    def iso(moment):
        return local(moment).isoformat(timespec="seconds") if moment is not None else None

    store = ContactStore()

    # 1. Contacts, in the order they were first created (that order decides the company's first contact).
    company_cols = ", ".join(f"c.{c}" for c in ("company_name", "company_domain") + CONTROLLED_COLUMNS
                             + READINESS_COLUMNS)
    leads = conn.execute(
        f"""SELECT l.lead_id, l.normalised_email, l.first_contact_at, l.business_country_code, l.crm_contact_id,
                   l.relationship_type, c.company_id, {company_cols}
            FROM leads l LEFT JOIN companies c ON c.company_id = l.company_id
            ORDER BY l.created_at, l.normalised_email""").fetchall()
    by_id = {}
    for row in leads:
        lead_id, email, first_at, country, crm_id, relationship, company_id = row[:7]
        company = None
        if company_id is not None:
            names = ("company_name", "company_domain") + CONTROLLED_COLUMNS + READINESS_COLUMNS
            company = dict(zip(names, row[7:]), source="event")
        if first_at is None:
            raise ValueError(f"lead {email} has no first_contact_at: apply migration 003 and reprocess")
        record = store.add_contact(email, local(first_at), country_code=country, company=company,
                                   crm_contact_id=crm_id, relationship=relationship)
        by_id[lead_id] = record

    # 2. Ownership: the open assignment's owner; assigned_at = the first assignment.
    for lead_id, owner, first_assigned in conn.execute(
            """SELECT a.lead_id, o.staff_code,
                      min(a.effective_from) OVER (PARTITION BY a.lead_id)
               FROM assignments a JOIN owners o ON o.owner_id = a.owner_id
               WHERE a.effective_to IS NULL""").fetchall():
        by_id[lead_id].update(owner=owner, assigned_at=local(first_assigned))

    # 3. Priority: first decision = initial priority; latest decision = current priority and rule.
    for lead_id, first_priority, last_priority, last_rule in conn.execute(
            """SELECT lead_id,
                      (array_agg(priority ORDER BY evaluated_at, decision_id))[1],
                      (array_agg(priority ORDER BY evaluated_at DESC, decision_id DESC))[1],
                      (array_agg(decision_details -> 'priority_rule' ORDER BY evaluated_at DESC, decision_id DESC))[1]
               FROM processing_decisions WHERE lead_id IS NOT NULL GROUP BY lead_id""").fetchall():
        by_id[lead_id].update(initial_priority=first_priority, priority=last_priority, priority_rule=last_rule)

    # 4. SLA deadline and response target, and every time the target was shortened.
    for lead_id, deadline, target in conn.execute(
            "SELECT lead_id, current_deadline_at, current_response_target_at FROM sla_tracking").fetchall():
        by_id[lead_id].update(sla_deadline=local(deadline), target_at=local(target))
    for lead_id, recorded, details in conn.execute(
            """SELECT s.lead_id, h.recorded_at, h.change_details FROM sla_history h
               JOIN sla_tracking s ON s.sla_id = h.sla_id
               WHERE h.event_type = 'response_target_shortened'
               ORDER BY h.recorded_at, h.history_key""").fetchall():
        by_id[lead_id]["target_changes"].append({"at": iso(recorded), "from": details["previous_target_at"],
                                                 "to": details["new_target_at"],
                                                 "new_priority": details["new_priority"]})

    # 5. First qualifying follow-up.
    for lead_id, first in conn.execute(
            """SELECT lead_id, min(occurred_at) FROM followup_activities
               WHERE lead_id IS NOT NULL AND (activity_details ->> 'qualifying')::boolean
               GROUP BY lead_id""").fetchall():
        by_id[lead_id]["first_followup_at"] = local(first)

    # 6. Engagement history.
    for lead_id, source_id, kind, occurred, details in conn.execute(
            """SELECT lead_id, source_event_id, event_type, occurred_at, event_details FROM engagement_events
               WHERE lead_id IS NOT NULL ORDER BY recorded_at, occurred_at, source_event_id""").fetchall():
        by_id[lead_id]["engagement_events"].append(
            {"id": None if details.get("source_id_missing") else source_id, "type": kind,
             "occurred_at": iso(occurred)})

    # 7. Events already handled. Rejected events (no usable ID) are remembered by their payload
    #    fingerprint, so a repeat of one is still flagged after a restart (DR-016).
    for system, event_id, status, email, raw in conn.execute(
            """SELECT e.source_system, e.source_event_id, e.processing_status, l.normalised_email, e.raw_payload
               FROM ingestion_events e LEFT JOIN leads l ON l.lead_id = e.lead_id""").fetchall():
        if status == "rejected":
            store.payload_hashes.add(payload_hash(raw))
        else:
            store.mark_processed(system, event_id, email)

    # 8. Round-robin: the database keeps the LAST rep assigned; the engine keeps the NEXT to try.
    reps = settings.get("representatives") or {}
    for country, last in conn.execute(
            """SELECT r.country_code, o.staff_code FROM routing_state r
               JOIN owners o ON o.owner_id = r.last_assigned_owner_id""").fetchall():
        ordered = sorted(reps.get(country) or [])
        if last in ordered:
            store.rotation[country] = ordered[(ordered.index(last) + 1) % len(ordered)]
    return store
