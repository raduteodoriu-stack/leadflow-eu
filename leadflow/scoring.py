"""LF-007: company-fit and engagement scores (LF-002), configured in the rules file."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

COMPONENTS = ("industry", "size", "need", "readiness")


def _band(total, thresholds):
    if total >= thresholds["high"]:
        return "high"
    return "medium" if total >= thresholds["medium"] else "low"


def fit_score(company, rules):
    """Components, provisional total, complete/incomplete and band (bands only when complete)."""
    cfg = rules.data["fit_scoring"]
    company = company or {}
    industry = cfg["industry_points"].get(company.get("industry_code"))
    size = cfg["size_points"].get(company.get("employee_band_declared"))
    use, freq = company.get("research_use_case"), company.get("research_frequency")
    if freq == cfg["need_absent_frequency"]:
        need = 0
    elif use in cfg["need_relevant_use_cases"] and freq in cfg["need_frequency_points"]:
        need = cfg["need_frequency_points"][freq]
    else:
        need = None
    readiness = None
    for level in cfg["readiness_levels"]:
        if "all_of" in level and all(company.get(f) is True for f in level["all_of"]):
            readiness = level["points"]
            break
        if "any_of" in level and any(company.get(f) is True for f in level["any_of"]):
            readiness = level["points"]
            break
    components = {"industry": industry, "size": size, "need": need, "readiness": readiness}
    total = sum(v for v in components.values() if v is not None)
    complete = all(v is not None for v in components.values())
    return {"components": components, "total": total, "status": "complete" if complete else "incomplete",
            "band": _band(total, cfg["band_thresholds"]) if complete else None}


def engagement_score(events, coverage, at, rules):
    """Score prospect actions in the 30 x 24 h before `at`; unknown unless coverage is complete."""
    cfg = rules.data["engagement_scoring"]
    end = at.astimezone(timezone.utc)
    start = end - timedelta(hours=cfg["window_hours"])
    seen, pricing_days = set(), set()
    request, webinars, downloads = False, 0, 0
    for event in events:
        key = event.get("id")
        if key is not None:
            if key in seen:
                continue
            seen.add(key)
        moment = datetime.fromisoformat(event["occurred_at"])
        if not start <= moment.astimezone(timezone.utc) <= end:
            continue
        kind = event["type"]
        if kind in cfg["explicit_request_types"]:
            request = True
        elif kind == "pricing_page_visited":
            pricing_days.add(moment.astimezone(rules.timezone).date())
        elif kind == "webinar_attended":
            webinars += 1
        elif kind in cfg["downloads"]["types"]:
            downloads += 1
    if coverage != "complete":
        return {"total": None, "status": "unknown", "band": "unknown", "explicit_request": request}
    total = (min(cfg["explicit_request"]["cap"], cfg["explicit_request"]["points"] if request else 0)
             + min(cfg["pricing_page_visited"]["cap"], cfg["pricing_page_visited"]["points_per_distinct_day"] * len(pricing_days))
             + min(cfg["webinar_attended"]["cap"], cfg["webinar_attended"]["points"] * webinars)
             + min(cfg["downloads"]["cap"], cfg["downloads"]["points"] * downloads))
    total = min(cfg["total_cap"], total)
    return {"total": total, "status": "complete", "band": _band(total, cfg["band_thresholds"]),
            "explicit_request": request}
