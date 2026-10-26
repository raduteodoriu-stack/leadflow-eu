"""What the engine already knows (in memory for LF-006) and contact identity resolution."""
from __future__ import annotations

from datetime import datetime


def _at(value):
    return value if isinstance(value, datetime) else datetime.fromisoformat(value)


class ContactStore:
    """In-memory record of processed events and known contacts.

    LF-007 replaces this with PostgreSQL; the interface stays the same.
    """

    def __init__(self):
        self.processed = {}          # (source_system, source_event_id) -> lead key or None
        self.payload_hashes = set()  # fingerprints of events without an ID
        self.contacts = {}           # normalised email -> contact record
        self.crm_index = {}          # CRM contact ID -> normalised email
        self.company_first = {}      # company domain -> {"lead_key", "at"}

    # events
    def was_processed(self, system, event_id):
        return (system, event_id) in self.processed

    def lead_for_event(self, system, event_id):
        return self.processed.get((system, event_id))

    def mark_processed(self, system, event_id, lead_key=None):
        self.processed[(system, event_id)] = lead_key

    def remember_payload(self, digest):
        seen = digest in self.payload_hashes
        self.payload_hashes.add(digest)
        return seen

    # contacts
    def contact(self, email):
        return self.contacts.get(email)

    def email_for_crm(self, crm_id):
        return self.crm_index.get(crm_id)

    def company_first_contact(self, domain):
        return self.company_first.get(domain)

    def add_contact(self, email, first_contact_at, country_code=None, company=None, crm_contact_id=None,
                    relationship=None, owner=None):
        record = {"lead_key": email, "first_contact_at": _at(first_contact_at), "country_code": country_code,
                  "company": company, "crm_contact_id": crm_contact_id, "relationship": relationship,
                  "owner": owner, "engagement_events": []}
        self.contacts[email] = record
        if crm_contact_id:
            self.crm_index.setdefault(crm_contact_id, email)
        domain = (company or {}).get("company_domain")
        if domain and domain not in self.company_first:
            self.company_first[domain] = {"lead_key": email, "at": record["first_contact_at"]}
        return record


def resolve_identity(email, crm_contact_id, domain, occurred_at, store, calendar, rules):
    """Return the identity part of a prepared event (LF-002 step 3)."""
    result = {"match": "new", "lead_key": None, "business_minutes_since_first_contact": None,
              "same_company_colleague": None}
    known = store.contact(email) if email else None
    if known:
        minutes = calendar.working_minutes_between(known["first_contact_at"], occurred_at)
        result.update(match="recontact" if minutes < rules.recontact_window else "existing",
                      lead_key=email, business_minutes_since_first_contact=minutes)
        return result
    other = store.email_for_crm(crm_contact_id) if crm_contact_id else None
    if other and other != email:
        result.update(match="crm_match", lead_key=other)
        return result
    first = store.company_first_contact(domain) if domain else None
    if first:
        minutes = calendar.working_minutes_between(first["at"], occurred_at)
        if minutes < rules.same_company_window:
            result["same_company_colleague"] = {"lead_key": first["lead_key"],
                                                "business_minutes_since_company_first_contact": minutes}
    return result
