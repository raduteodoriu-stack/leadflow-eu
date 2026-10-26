"""Unit tests: validation, identity and classification in prepare_event (LF-006)."""
import copy

from leadflow import ContactStore, load_rules, prepare_event

RULES = load_rules()
T = "2026-11-03T10:00:00+01:00"


def event(**overrides):
    base = {"source_system": "synthetic_fixture", "source_event_id": "U-1", "event_type": "lead_created",
            "source_occurred_at": "2026-11-03T09:58:00+01:00", "email": "ana@panel.example",
            "business_country": "ES", "relationship_type": "buyer",
            "company": {"company_domain": "panel.example", "industry_code": "polling",
                        "employee_band_declared": "50-249", "research_use_case": "both",
                        "research_frequency": "monthly_or_more", "uses_digital_research_tools": True},
            "engagement_events": [], "engagement_coverage": "complete"}
    base.update(overrides)
    return base


def test_missing_event_id_is_rejected_and_repeat_payload_flagged():
    store = ContactStore()
    raw = event(source_event_id=None)
    first = prepare_event(raw, T, store, RULES)
    second = prepare_event(copy.deepcopy(raw), T, store, RULES)
    assert first["status"] == "rejected" and first["reason_codes"] == ["SOURCE_EVENT_INVALID"]
    assert not first["warnings"] and any("possible repeat" in w for w in second["warnings"])


def test_replay_is_detected_and_points_to_the_lead():
    store = ContactStore()
    prepare_event(event(), T, store, RULES)
    replay = prepare_event(event(), "2026-11-03T10:30:00+01:00", store, RULES)
    assert replay["status"] == "duplicate"
    assert replay["reason_codes"] == ["DUPLICATE_EVENT_RECONTACT"]
    assert replay["identity"]["lead_key"] == "ana@panel.example"


def test_recontact_boundary_is_under_eight_business_hours():
    store = ContactStore()
    prepare_event(event(source_occurred_at="2026-11-02T10:00:00+01:00"), "2026-11-02T10:00:00+01:00", store, RULES)
    under = prepare_event(event(source_event_id="U-2", source_occurred_at="2026-11-02T17:59:00+01:00"),
                          "2026-11-02T17:59:00+01:00", store, RULES)
    at = prepare_event(event(source_event_id="U-3", source_occurred_at="2026-11-03T09:00:00+01:00"),
                       "2026-11-03T09:00:00+01:00", store, RULES)
    assert under["identity"]["match"] == "recontact" and "DUPLICATE_EVENT_RECONTACT" in under["reason_codes"]
    assert at["identity"]["match"] == "existing" and "EXISTING_CONTACT" in at["reason_codes"]


def test_crm_match_with_new_email_is_attached_not_merged():
    store = ContactStore()
    prepare_event(event(crm_contact_id="CRM-1"), T, store, RULES)
    other = prepare_event(event(source_event_id="U-2", email="a.lopez@panel.example", crm_contact_id="CRM-1"),
                          T, store, RULES)
    assert other["identity"] == {"match": "crm_match", "lead_key": "ana@panel.example",
                                 "business_minutes_since_first_contact": None, "same_company_colleague": None}
    assert "IDENTITY_REVIEW" in other["reason_codes"]
    assert store.contact("a.lopez@panel.example") is None


def test_same_company_colleague_within_window():
    store = ContactStore()
    prepare_event(event(), T, store, RULES)
    colleague = prepare_event(event(source_event_id="U-2", email="rita@panel.example",
                                    source_occurred_at="2026-11-03T12:00:00+01:00"), T, store, RULES)
    assert colleague["identity"]["match"] == "new"
    assert colleague["identity"]["same_company_colleague"]["lead_key"] == "ana@panel.example"


def test_existing_contact_without_company_uses_stored_company():
    store = ContactStore()
    prepare_event(event(), T, store, RULES)
    later = prepare_event(event(source_event_id="U-2", company=None, source_occurred_at="2026-11-05T10:00:00+01:00"),
                          "2026-11-05T10:00:00+01:00", store, RULES)
    assert later["company"]["source"] == "stored" and later["company"]["industry_code"] == "polling"


def test_country_problems_block_new_leads():
    cases = {"Atlantis": "COUNTRY_INVALID", None: "COUNTRY_INVALID", "Italia": "UNSUPPORTED_TERRITORY"}
    for i, (country, code) in enumerate(cases.items()):
        p = prepare_event(event(source_event_id=f"C-{i}", email=f"c{i}@x{i}.example", business_country=country),
                          T, ContactStore(), RULES)
        assert code in p["reason_codes"] and p["blocking"]
    conflict = prepare_event(event(business_country="Spain", crm_business_country="Portugal"), T, ContactStore(), RULES)
    assert "COUNTRY_CONFLICT" in conflict["reason_codes"] and conflict["country"]["code"] is None


def test_invalid_email_blocks_and_creates_no_contact():
    store = ContactStore()
    p = prepare_event(event(email="ana(at)panel.example"), T, store, RULES)
    assert p["reason_codes"] == ["EMAIL_INVALID"] and p["blocking"] and not store.contacts


def test_participants_are_redirected_or_held():
    rules = {"supplier_redirect_rules": {"ES": {"supplier_code": "SUP-ES-01"}}}
    es = prepare_event(event(enquiry_type="paid_survey_participant", company=None), T, ContactStore(), RULES, rules)
    pt = prepare_event(event(enquiry_type="paid_survey_participant", company=None, business_country="PT"),
                       T, ContactStore(), RULES, rules)
    assert es["status"] == "participant" and es["reason_codes"] == ["PARTICIPANT_REDIRECT"]
    assert pt["reason_codes"] == ["NO_REDIRECT_RULE"] and pt["redirect_rule"] is None


def test_unknown_values_old_event_names_and_duplicates():
    p = prepare_event(event(
        company={"company_domain": None, "industry_code": None, "employee_band_declared": "huge"},
        relationship_type=None,
        engagement_events=[{"id": "E1", "type": "demo_request", "occurred_at": T},
                           {"id": "E1", "type": "demo_request", "occurred_at": T},
                           {"id": "E2", "type": "newsletter_open", "occurred_at": T}]), T, ContactStore(), RULES)
    assert p["company"]["industry_code"] == "unknown" and p["company"]["employee_band_declared"] == "unknown"
    assert p["relationship"] == "unknown" and {"RELATIONSHIP_UNKNOWN", "DOMAIN_MISSING"} <= set(p["reason_codes"])
    assert [e["type"] for e in p["engagement"]["events"]] == ["demo_requested"]
    assert p["engagement"]["unmapped_event_types"] == ["newsletter_open"]
    assert any("employee_band_declared" in w for w in p["warnings"])
