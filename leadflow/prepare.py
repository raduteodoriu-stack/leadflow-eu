"""LF-006: turn one raw inbound event into a prepared event (LF-002 steps 1-5).

No scores, priorities, owners, queues or SLA times are set here; LF-007 does that.
"""
from __future__ import annotations

from datetime import datetime

from leadflow.business_time import WorkingCalendar
from leadflow.identity import resolve_identity
from leadflow.normalise import (clean_text, is_valid_email, normalise_country, normalise_email,
                                normalise_source_system)
from leadflow.validate import (payload_hash, standardise_company, standardise_engagement,
                               standardise_enquiry_type, standardise_relationship)

COUNTRY_CODES = {"missing": "COUNTRY_INVALID", "unrecognised": "COUNTRY_INVALID",
                 "conflict": "COUNTRY_CONFLICT", "unsupported": "UNSUPPORTED_TERRITORY"}


def _moment(value, rules):
    if value is None:
        return None
    moment = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if moment.tzinfo is None:
        raise ValueError(f"timestamp without a time zone: {value!r}")
    return moment.astimezone(rules.timezone)


def _iso(moment):
    return moment.isoformat(timespec="seconds") if moment else None


def prepare_event(raw, received_at, store, rules, settings=None, calendar=None):
    """Validate, standardise and identify one event, updating `store`.

    raw         -- the inbound event as received (LF-004/LF-005 input format)
    received_at -- when LeadFlow received it (datetime or ISO string with offset)
    store       -- ContactStore with earlier events and contacts
    settings    -- operational settings, e.g. {"supplier_redirect_rules": {"ES": {...}}}
    """
    calendar = calendar or WorkingCalendar.from_rules(rules)
    settings = settings or {}
    warnings, codes = [], []
    received = _moment(received_at, rules)
    occurred = _moment(raw.get("source_occurred_at"), rules) or received
    system = normalise_source_system(raw.get("source_system"))
    event_id = clean_text(raw.get("source_event_id"))
    digest = payload_hash(raw)
    prepared = {
        "rule_version": rules.version,
        "status": None,
        "event": {"source_system": system, "source_event_id": event_id,
                  "event_type": clean_text(raw.get("event_type")), "occurred_at": _iso(occurred),
                  "received_at": _iso(received), "payload_hash": digest},
        "contact": None, "identity": None, "country": None, "relationship": None, "enquiry_type": None,
        "redirect_rule": None, "company": None, "engagement": None,
        "reason_codes": codes, "blocking": False, "warnings": warnings,
    }

    # Step 1: previously processed events, and events that cannot be identified
    if not system or not event_id:
        if store.remember_payload(digest):
            warnings.append("same payload as an earlier event without an ID: possible repeat (DR-016)")
        codes.append("SOURCE_EVENT_INVALID")
        prepared.update(status="rejected", blocking=True)
        return prepared
    if store.was_processed(system, event_id):
        codes.append("DUPLICATE_EVENT_RECONTACT")
        lead_key = store.lead_for_event(system, event_id)
        prepared.update(status="duplicate",
                        identity={"match": "replay", "lead_key": lead_key,
                                  "business_minutes_since_first_contact": None, "same_company_colleague": None})
        return prepared
    store.mark_processed(system, event_id)
    if prepared["event"]["event_type"] not in rules.allowed["event_type"]:
        warnings.append(f"event_type: unexpected value {raw.get('event_type')!r}")

    # Step 2: validate and standardise inputs
    email = normalise_email(raw.get("email"))
    email_valid = is_valid_email(email, rules)
    crm_id = clean_text(raw.get("crm_contact_id"))
    code, status = normalise_country(raw.get("business_country"), rules)
    crm_country_input = raw.get("crm_business_country")
    if clean_text(crm_country_input) and status != "missing":
        crm_code, crm_status = normalise_country(crm_country_input, rules)
        if crm_status != "missing" and crm_code != code:
            code, status = None, "conflict"
    relationship = standardise_relationship(raw.get("relationship_type"), rules, warnings)
    enquiry = standardise_enquiry_type(raw.get("enquiry_type"), rules, warnings)
    company = standardise_company(raw.get("company"), rules, warnings)
    engagement = standardise_engagement(raw.get("engagement_events"), raw.get("engagement_coverage"), rules, warnings)
    prepared.update(
        contact={"email_input": raw.get("email"), "normalised_email": email, "email_valid": email_valid,
                 "crm_contact_id": crm_id},
        country={"input": raw.get("business_country"), "crm_input": crm_country_input, "code": code, "status": status},
        relationship=relationship, enquiry_type=enquiry, engagement=engagement)

    # Step 5 (early): paid-survey participants are not sales leads
    if enquiry == "paid_survey_participant":
        rule = settings.get("supplier_redirect_rules", {}).get(code) if code else None
        codes.append("PARTICIPANT_REDIRECT" if rule else "NO_REDIRECT_RULE")
        prepared.update(status="participant", redirect_rule=rule, relationship=None)
        return prepared

    prepared["status"] = "ready"
    if not email_valid:
        codes.append("EMAIL_INVALID")
        prepared.update(blocking=True,
                        identity={"match": "unresolved", "lead_key": None,
                                  "business_minutes_since_first_contact": None, "same_company_colleague": None})
        if company is not None:
            company["source"] = "event"
            prepared["company"] = company
        _flags(prepared, company, relationship, codes)
        return prepared

    # Step 3: contact identity
    domain = (company or {}).get("company_domain")
    identity = resolve_identity(email, crm_id, domain, occurred, store, calendar, rules)
    prepared["identity"] = identity
    match = identity["match"]
    if match in ("existing", "recontact", "crm_match"):
        known = store.contact(identity["lead_key"])
        codes.append({"existing": "EXISTING_CONTACT", "recontact": "DUPLICATE_EVENT_RECONTACT",
                      "crm_match": "IDENTITY_REVIEW"}[match])
        if company is None and known.get("company"):
            company = dict(known["company"], source="stored")
        elif company is not None:
            company["source"] = "event"
        stored_code = known.get("country_code")
        if stored_code:
            prepared["country"] = dict(prepared["country"], code=stored_code, status=(
                "supported" if stored_code in rules.supported_countries else "unsupported"), source="stored")
        known["engagement_events"].extend(engagement["events"])
        store.mark_processed(system, event_id, identity["lead_key"])
    else:
        # Step 4: country eligibility (new contacts only; existing contacts keep their country)
        if status in COUNTRY_CODES:
            codes.append(COUNTRY_CODES[status])
            prepared["blocking"] = True
        # Step 5: relationship classification
        if relationship in ("supplier", "both"):
            codes.append("SUPPLIER_REVIEW")
        if company is not None:
            company["source"] = "event"
        record = store.add_contact(email, occurred, country_code=code if status in ("supported", "unsupported") else None,
                                   company=company, crm_contact_id=crm_id, relationship=relationship)
        record["engagement_events"].extend(engagement["events"])
        store.mark_processed(system, event_id, email)
    prepared["company"] = company
    _flags(prepared, company, relationship, codes)
    return prepared


def _flags(prepared, company, relationship, codes):
    if relationship == "unknown":
        codes.append("RELATIONSHIP_UNKNOWN")
    if company is not None and not company.get("company_domain"):
        codes.append("DOMAIN_MISSING")
