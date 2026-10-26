"""Unit tests: fit, engagement and priority (LF-007)."""
from datetime import datetime

import pytest

from leadflow import load_rules
from leadflow.priority import decide_priority
from leadflow.scoring import engagement_score, fit_score

RULES = load_rules()
AT = datetime.fromisoformat("2026-11-03T10:00:00+01:00")


def company(**kw):
    base = {"industry_code": "market_research", "employee_band_declared": "50-249",
            "research_use_case": "both", "research_frequency": "monthly_or_more", "uses_digital_research_tools": True}
    base.update(kw)
    return base


def test_complete_fit_and_bands():
    assert fit_score(company(), RULES) == {"components": {"industry": 40, "size": 10, "need": 25, "readiness": 10},
                                           "total": 85, "status": "complete", "band": "high"}
    assert fit_score(company(employee_band_declared="1000_plus", research_frequency="one_off",
                             uses_digital_research_tools=None, adoption_unwilling_or_unable=True), RULES)["band"] == "medium"


@pytest.mark.parametrize("change, component", [
    ({"industry_code": "unknown"}, "industry"), ({"employee_band_declared": "unknown"}, "size"),
    ({"research_frequency": "unknown"}, "need"), ({"research_use_case": "other"}, "need"),
    ({"uses_digital_research_tools": None}, "readiness"),
])
def test_unknown_component_makes_fit_incomplete_without_band(change, component):
    fit = fit_score(company(**change), RULES)
    assert fit["components"][component] is None and fit["status"] == "incomplete" and fit["band"] is None


def test_confirmed_absence_is_zero_not_unknown():
    fit = fit_score(company(research_use_case="other", research_frequency="none"), RULES)
    assert fit["components"]["need"] == 0


def test_readiness_takes_highest_supported_level():
    full = company(integration_required=True, technical_resource_available=True, adoption_unwilling_or_unable=True)
    assert fit_score(full, RULES)["components"]["readiness"] == 15


def ev(i, kind, when):
    return {"id": f"E{i}", "type": kind, "occurred_at": when}


def test_engagement_caps_window_and_distinct_days():
    events = [ev(1, "pricing_page_visited", "2026-11-02T08:00:00+01:00"),
              ev(2, "pricing_page_visited", "2026-11-02T22:00:00+01:00"),   # same Madrid day
              ev(3, "guide_downloaded", "2026-11-01T10:00:00+01:00"),
              ev(4, "case_study_downloaded", "2026-11-01T11:00:00+01:00"),
              ev(5, "guide_downloaded", "2026-11-01T12:00:00+01:00"),        # downloads capped at 10
              ev(5, "guide_downloaded", "2026-11-01T12:00:00+01:00"),        # same ID twice
              ev(6, "demo_requested", "2026-09-20T10:00:00+02:00")]          # outside 30 days
    result = engagement_score(events, "complete", AT, RULES)
    assert (result["total"], result["band"], result["explicit_request"]) == (20, "medium", False)


def test_window_edge_is_exactly_720_hours():
    inside = engagement_score([ev(1, "webinar_attended", "2026-10-04T11:00:00+02:00")], "complete", AT, RULES)
    outside = engagement_score([ev(1, "webinar_attended", "2026-10-04T10:59:00+02:00")], "complete", AT, RULES)
    assert inside["total"] == 15 and outside["total"] == 0


def test_partial_or_failed_coverage_is_unknown_not_zero():
    for coverage in ("partial", "failed"):
        result = engagement_score([], coverage, AT, RULES)
        assert result["total"] is None and result["band"] == "unknown"


def fit(band, status="complete"):
    return {"status": status, "band": band if status == "complete" else None}


def eng(band, request=False, status="complete"):
    return {"band": band, "status": status, "explicit_request": request}


@pytest.mark.parametrize("f, e, rel, expected", [
    (fit("low"), eng("high", request=True), "buyer", ("P1", 2)),
    (fit("high"), eng("high"), "buyer", ("P1", 3)),
    (fit(None, "incomplete"), eng("high"), "buyer", ("P2", 4)),
    (fit("high"), eng("unknown", status="unknown"), "buyer", ("P2", 5)),
    (fit("medium"), eng("medium"), "unknown", ("P2", 5)),
    (fit("medium"), eng("low"), "unknown", ("P2", 6)),
    (fit("low"), eng("medium"), "buyer", ("P3", 7)),
])
def test_priority_rules_in_order(f, e, rel, expected):
    priority, rule, code = decide_priority(f, e, rel, RULES)
    assert (priority, rule) == expected and code == RULES.data["priority_reason_codes"][str(rule)]
