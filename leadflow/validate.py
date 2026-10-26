"""Validate and standardise the parts of an inbound event."""
from __future__ import annotations

import hashlib
import json

from leadflow.normalise import clean_text, normalise_domain

CONTROLLED_COMPANY_FIELDS = ("industry_code", "employee_band_declared", "research_use_case", "research_frequency")


def payload_hash(raw):
    """Stable fingerprint of the raw event, used to spot repeats that carry no event ID (DR-016)."""
    text = json.dumps(raw, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def controlled(value, field, rules, warnings):
    """Lower-case a controlled value; missing becomes 'unknown', an unexpected one is reported."""
    text = clean_text(value)
    if text is None:
        return rules.unknown
    text = text.lower()
    if text not in rules.allowed[field]:
        warnings.append(f"{field}: unexpected value {value!r} treated as {rules.unknown!r}")
        return rules.unknown
    return text


def standardise_company(company, rules, warnings):
    if not company:
        return None
    out = {"company_name": clean_text(company.get("company_name")),
           "company_domain": normalise_domain(company.get("company_domain"))}
    for field in CONTROLLED_COMPANY_FIELDS:
        out[field] = controlled(company.get(field), field, rules, warnings)
    for field in rules.readiness_fields:
        value = company.get(field)
        if value is not None and not isinstance(value, bool):
            warnings.append(f"{field}: expected true/false, got {value!r}; treated as unknown")
            value = None
        out[field] = value
    return out


def standardise_engagement(events, coverage, rules, warnings):
    """Map earlier event names to stored names (DR-002), drop repeated IDs, report what cannot be mapped."""
    kept, seen, unmapped = [], set(), []
    for event in events or []:
        name = clean_text(event.get("type"))
        name = rules.event_name_map.get(name, name)
        if name not in rules.allowed["engagement_event_type"]:
            unmapped.append(event.get("type"))
            continue
        event_id = event.get("id")
        if event_id is not None and event_id in seen:
            continue
        seen.add(event_id)
        kept.append({"id": event_id, "type": name, "occurred_at": event.get("occurred_at")})
    if unmapped:
        warnings.append(f"engagement: unmapped event types {sorted(set(map(str, unmapped)))}")
    cov = clean_text(coverage)
    cov = cov.lower() if cov else None
    if cov not in rules.allowed["engagement_coverage"]:
        warnings.append(f"engagement_coverage: unexpected value {coverage!r} treated as 'failed'")
        cov = "failed"
    return {"coverage": cov, "events": kept, "unmapped_event_types": unmapped}


def standardise_relationship(value, rules, warnings):
    return controlled(value, "relationship_type", rules, warnings)


def standardise_enquiry_type(value, rules, warnings):
    text = clean_text(value)
    if text is None:
        return "sales"
    text = text.lower()
    if text not in rules.allowed["enquiry_type"]:
        warnings.append(f"enquiry_type: unexpected value {value!r} treated as 'sales'")
        return "sales"
    return text
