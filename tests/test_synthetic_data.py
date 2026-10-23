"""Validation tests for the LF-005 synthetic dataset.

Run from the repository root:  python3 -m pytest
These tests check the dataset files. They do not test the routing engine.
"""
import importlib.util
import json
import pathlib
import re
from collections import Counter
from datetime import datetime

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = json.loads((ROOT / "data/synthetic/leads_100.json").read_text(encoding="utf-8"))
EXPECTED = json.loads((ROOT / "data/synthetic/expected_outcomes.json").read_text(encoding="utf-8"))
EVENTS = DATA["events"]
OUTCOMES = EXPECTED["events"]
CUTOFF = datetime.fromisoformat(DATA["metadata"]["sla_cutoff"])

# Targets from the LF-005 card (approximate mix, +/- 2 per group).
CARD_TARGETS = {"new_buyer_assignable": 55, "returning_contact": 10, "supplier_or_both": 7,
                "relationship_unknown": 3, "blocking_exception": 12, "ambiguous_identity": 2,
                "participant": 5, "replay": 3, "malformed": 3}

# Allowed values, copied from docs/data_dictionary.md and SQL/001_create_schema.sql.
ALLOWED = {
    "industry_code": {"market_research", "polling", "research_consultancy", "panel_sample_provider",
                      "research_technology", "advertising_media_pr_agency", "ux_research_agency",
                      "management_consultancy", "consumer_goods", "retail_ecommerce", "technology_telecoms",
                      "financial_services", "automotive_mobility", "healthcare_pharma", "travel_hospitality",
                      "media_entertainment_gaming", "energy_utilities", "public_academic_nonprofit",
                      "other", "unknown"},
    "employee_band_declared": {"1-10", "11-49", "50-249", "250-999", "1000_plus", "unknown"},
    "research_use_case": {"respondents_fieldwork", "panel_management", "both", "other", "unknown"},
    "research_frequency": {"monthly_or_more", "recurring_less_than_monthly", "one_off", "none", "unknown"},
    "relationship_type": {"buyer", "supplier", "both", "unknown"},
    "event_type": {"lead_created", "lead_updated"},
    "engagement_type": {"demo_requested", "sales_contact_requested", "quote_requested", "pricing_page_visited",
                        "webinar_attended", "guide_downloaded", "case_study_downloaded"},
    "engagement_coverage": {"complete", "partial", "failed"},
}

LF002_CODES = {"COUNTRY_INVALID", "COUNTRY_CONFLICT", "EMAIL_INVALID", "EXISTING_CONTACT", "IDENTITY_REVIEW",
               "UNSUPPORTED_TERRITORY", "NO_ELIGIBLE_OWNER", "OWNER_REVIEW", "SUPPLIER_REVIEW",
               "RELATIONSHIP_UNKNOWN", "FIT_INCOMPLETE", "DOMAIN_MISSING", "ENGAGEMENT_UNKNOWN",
               "PARTICIPANT_REDIRECT", "SOURCE_EVENT_INVALID", "NO_REDIRECT_RULE",
               "DUPLICATE_EVENT_RECONTACT", "SAME_COMPANY_RECENT_CONTACT",
               "PRIORITY_EXPLICIT_REQUEST", "PRIORITY_HIGH_FIT_HIGH_ENGAGEMENT", "PRIORITY_HIGH_ENGAGEMENT",
               "PRIORITY_STANDARD_FIT", "PRIORITY_MISSING_INFO", "PRIORITY_DEFAULT"}


def _load_generator():
    spec = importlib.util.spec_from_file_location("generator", ROOT / "tools/generate_synthetic_leads.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_exactly_100_events_in_processing_order():
    assert len(EVENTS) == 100
    assert [e["seq"] for e in EVENTS] == list(range(1, 101))
    times = [datetime.fromisoformat(e["received_at"]) for e in EVENTS]
    assert times == sorted(times)
    assert all(t <= CUTOFF for t in times)


def test_regenerating_gives_identical_files():
    files = _load_generator().build()
    for rel, content in files.items():
        assert (ROOT / rel).read_text(encoding="utf-8") == content, f"{rel} is out of date; rerun the generator"


def test_mix_matches_the_card():
    counts = Counter(o["group"] for o in OUTCOMES)
    assert set(counts) == set(CARD_TARGETS)
    for group, target in CARD_TARGETS.items():
        assert abs(counts[group] - target) <= 2, (group, counts[group])


def test_inputs_use_allowed_values():
    for e in EVENTS:
        inp = e["input"]
        assert inp["event_type"] in ALLOWED["event_type"]
        assert inp["relationship_type"] in ALLOWED["relationship_type"]
        assert inp["engagement_coverage"] in ALLOWED["engagement_coverage"]
        for ev in inp["engagement_events"]:
            assert ev["type"] in ALLOWED["engagement_type"]
        company = inp.get("company")
        if company:
            for field in ("industry_code", "employee_band_declared", "research_use_case", "research_frequency"):
                assert company[field] in ALLOWED[field], (e["seq"], field, company[field])


def test_all_data_is_fictional():
    for e in EVENTS:
        inp = e["input"]
        assert ".example" in inp["email"] or inp["email"].strip().endswith("@"), inp["email"]
        company = inp.get("company")
        if company and company["company_domain"]:
            assert company["company_domain"].endswith(".example")
    for rule in DATA["metadata"]["supplier_redirect_rules"].values():
        assert re.match(r"https://[a-z0-9-]+\.example/", rule["destination_url"])


def test_every_event_has_an_explained_expected_outcome():
    assert [o["seq"] for o in OUTCOMES] == [e["seq"] for e in EVENTS]
    scenarios = ROOT / "tests/fixtures/scenarios"
    for o, e in zip(OUTCOMES, EVENTS):
        assert o["source_event_id"] == e["input"]["source_event_id"]
        assert o["explanation"]
        assert o["patterns"], o["seq"]
        for pattern in o["patterns"]:
            assert (scenarios / f"{pattern}.json").exists(), pattern


def test_every_reason_code_appears():
    seen = {code for o in OUTCOMES for code in o["expected"].get("reason_codes", [])}
    assert LF002_CODES <= seen, LF002_CODES - seen


def test_every_priority_rule_and_band_appears():
    exp = [o["expected"] for o in OUTCOMES]
    assert {x["priority_rule"] for x in exp if x.get("priority_rule")} == {2, 3, 4, 5, 6, 7}
    fits = {(x["fit"]["band"] or x["fit"]["status"]) for x in exp if x.get("fit")}
    assert {"high", "medium", "low", "incomplete"} <= fits
    engs = {x["engagement"]["band"] for x in exp if x.get("engagement")}
    assert {"high", "medium", "low", "unknown"} <= engs


def test_unknown_is_never_a_zero():
    for o, e in zip(OUTCOMES, EVENTS):
        x = o["expected"]
        if x.get("fit") and x["fit"]["status"] == "incomplete":
            assert x["fit"]["band"] is None
            assert any(v is None for v in x["fit"]["components"].values())
        if x.get("engagement") and x["engagement"]["status"] == "unknown":
            assert x["engagement"]["total"] is None
            assert "ENGAGEMENT_UNKNOWN" in x["reason_codes"]


def test_followup_activities_are_consistent():
    leads = {l["lead_email"]: l for l in EXPECTED["leads"]}
    for act in DATA["followup_activities"]:
        lead = leads[act["lead_email"]]
        assert lead["owner"] == act["owner"]
        at = datetime.fromisoformat(act["occurred_at"])
        assert datetime.fromisoformat(lead["assigned_at"]) <= at <= CUTOFF


def test_replays_and_malformed_events():
    by_id = {}
    for e, o in zip(EVENTS, OUTCOMES):
        sid = e["input"]["source_event_id"]
        if o["group"] == "replay":
            assert e["input"] == by_id[sid], "a replay must repeat an earlier event exactly"
            assert o["expected"]["outcome"] == "duplicate_event_ignored"
        elif o["group"] == "malformed":
            assert sid is None
            assert o["expected"]["outcome"] == "rejected"
        else:
            assert sid not in by_id
            by_id[sid] = e["input"]


def test_counts_reconcile():
    summary = EXPECTED["summary"]
    assert sum(summary["events_by_outcome"].values()) == 100
    created = sum(1 for o in OUTCOMES if o["expected"].get("lead_created"))
    assert created == summary["leads_created"] == len(EXPECTED["leads"])
    assert summary["leads_assigned"] + summary["leads_waiting_in_review"] == created


def test_followup_mix_is_realistic():
    assigned = [l for l in EXPECTED["leads"] if l["owner"]]
    sla = Counter(l["sla_outcome"] for l in assigned)
    met_but_missed = sum(1 for l in assigned if l["sla_outcome"] == "met" and l["response_target_outcome"] == "missed")
    assert sla["met"] / len(assigned) >= 0.5
    assert sla["breached"] >= 3 and sla["pending"] >= 2
    assert met_but_missed >= 5
