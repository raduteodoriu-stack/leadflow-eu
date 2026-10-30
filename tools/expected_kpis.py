"""LF-011: expected KPI values for the LF-005 dataset, worked out from the answer key.

Reads data/synthetic/expected_outcomes.json (and the source channels in leads_100.json)
and writes reporting/seeds/expected_kpis.csv. dbt loads that file as a seed, and the
test `kpi_summary_matches_expected` fails if any KPI the reporting layer computes from
the database differs from it.

The calculation here is deliberately independent: it reads only the hand-checked answer
key, never the database or the engine, and has its own working-time arithmetic. So the
dbt models are checked against something they did not produce.

    python tools/expected_kpis.py          # rewrite the seed
    python tools/expected_kpis.py --check  # fail if it is out of date
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import pathlib
import statistics
import sys
from collections import Counter
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

ROOT = pathlib.Path(__file__).resolve().parents[1]
EXPECTED = ROOT / "data/synthetic/expected_outcomes.json"
SOURCE = ROOT / "data/synthetic/leads_100.json"
SEED = ROOT / "reporting/seeds/expected_kpis.csv"

MADRID = ZoneInfo("Europe/Madrid")
OPENS, CLOSES = time(9), time(18)
AT_RISK_MINUTES = 120
# Which review reason a case is filed under (LF-002 review routing; mirrors the rules file).
ACTION_OWNER_BY_CODE = {"COUNTRY_INVALID": "revops", "COUNTRY_CONFLICT": "revops", "EMAIL_INVALID": "revops",
                        "SOURCE_EVENT_INVALID": "revops", "UNSUPPORTED_TERRITORY": "sales_manager",
                        "NO_ELIGIBLE_OWNER": "sales_manager", "OWNER_REVIEW": "sales_manager"}


def parse(value):
    return datetime.fromisoformat(value)


def working_minutes(a, b):
    """Monday-Friday 09:00-18:00 Madrid, from a up to b, whole minutes."""
    if b <= a:
        return 0
    total = timedelta(0)
    day = a.astimezone(MADRID).date()
    while day <= b.astimezone(MADRID).date():
        if day.weekday() < 5:
            lo = max(a, datetime.combine(day, OPENS, MADRID))
            hi = min(b, datetime.combine(day, CLOSES, MADRID))
            if hi > lo:
                total += hi - lo
        day += timedelta(days=1)
    return int(total.total_seconds() // 60)


def iso_week(moment):
    year, week, _ = moment.astimezone(MADRID).isocalendar()
    return f"{year}-W{week:02d}"


def build_rows():
    answer = json.loads(EXPECTED.read_text(encoding="utf-8"))
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    cutoff = parse(answer["metadata"]["sla_cutoff"])
    channel = {e["seq"]: e["input"]["source_channel"] for e in source["events"]}

    events = answer["events"]
    stored = [e for e in events if e["expected"]["outcome"] != "duplicate_event_ignored"]
    created = [e for e in events if e["expected"].get("lead_created")]
    leads = answer["leads"]
    assigned = [l for l in leads if l["owner"]]
    waiting = [l for l in leads if not l["owner"]]
    rows = []

    def add(kpi, breakdown, member, numerator, denominator=None):
        if isinstance(numerator, float) and numerator.is_integer():
            numerator = int(numerator)  # a median of whole minutes can end in .5; otherwise print it whole
        rows.append({"kpi_id": kpi, "breakdown": breakdown, "member": member,
                     "numerator": numerator, "denominator": "" if denominator is None else denominator})

    def add_counts(kpi, breakdown, counter, denominator=None):
        for member, n in sorted(counter.items()):
            add(kpi, breakdown, member, n, denominator)

    # 1 Enquiries received (stored; repeats are not stored)
    add(1, "total", "all", len(stored))
    add_counts(1, "week", Counter(iso_week(parse(e["received_at"])) for e in stored))
    # 2 New leads
    add(2, "total", "all", len(created))
    add_counts(2, "week", Counter(iso_week(parse(e["received_at"])) for e in created))
    # 3 Leads by country (no usable country -> 'unknown')
    add_counts(3, "country", Counter(l["country_code"] or "unknown" for l in leads))
    # 4 Leads by source channel (of the enquiry that created the lead)
    add_counts(4, "channel", Counter(channel[e["seq"]] for e in created))
    # 5 Rejected enquiries %
    add(5, "total", "all", sum(1 for e in stored if e["expected"]["outcome"] == "rejected"), len(stored))
    # 7 Incomplete data %: company data incomplete or interest unknown when the lead was created
    incomplete = sum(1 for e in created if (e["expected"].get("fit") or {}).get("status") != "complete"
                     or (e["expected"].get("engagement") or {}).get("status") == "unknown")
    add(7, "total", "all", incomplete, len(created))
    # 9 Auto-assignment rate
    auto = sum(1 for e in created if e["expected"]["outcome"] in ("assigned", "assigned_to_company_owner"))
    add(9, "total", "all", auto, len(created))
    # 10 Leads waiting for an owner, and the longest wait in working minutes
    since = {e["expected"]["normalised_email"]: parse(e["expected"]["waiting_since"])
             for e in created if e["expected"].get("waiting_since")}
    add(10, "total", "all", len(waiting))
    add(10, "longest_wait_working_minutes", "all", max(working_minutes(since[l["lead_email"]], cutoff) for l in waiting))
    # 12 Leads per salesperson (first owner)
    add_counts(12, "owner", Counter(l["owner"] for l in assigned))
    # 16 Urgency mix of assigned leads (priority when assigned)
    add_counts(16, "priority", Counter(l["initial_priority"] for l in assigned), len(assigned))
    # 17 Why leads were urgent: priority rule of the creating decision
    add_counts(17, "priority_rule", Counter(str(e["expected"]["priority_rule"]) for e in created))
    # 20 SLA attainment: met / (met + breached)
    def attainment(group):
        met = sum(1 for l in group if l["sla_outcome"] == "met")
        return met, met + sum(1 for l in group if l["sla_outcome"] == "breached")
    add(20, "total", "all", *attainment(assigned))
    for p in ("P1", "P2", "P3"):
        add(20, "priority", p, *attainment([l for l in assigned if l["initial_priority"] == p]))
    for c in sorted({l["country_code"] for l in assigned}):
        add(20, "country", c, *attainment([l for l in assigned if l["country_code"] == c]))
    # 21 SLA breaches
    add(21, "total", "all", sum(1 for l in assigned if l["sla_outcome"] == "breached"))
    # 22 At-risk: pending, due within the next 2 working hours
    add(22, "total", "all", sum(1 for l in assigned if l["sla_outcome"] == "pending"
                                and parse(l["sla_deadline"]) > cutoff
                                and working_minutes(cutoff, parse(l["sla_deadline"])) <= AT_RISK_MINUTES))
    # 23 Response-target hit rate: met / (met + missed)
    met = sum(1 for l in assigned if l["response_target_outcome"] == "met")
    add(23, "total", "all", met, met + sum(1 for l in assigned if l["response_target_outcome"] == "missed"))
    # 24 SLA met but response target missed
    add(24, "total", "all", sum(1 for l in assigned if l["sla_outcome"] == "met"
                                and l["response_target_outcome"] == "missed"))
    # 25 Median working minutes from assignment to the first qualifying follow-up, by priority when assigned
    for p in ("P1", "P2", "P3"):
        waits = [working_minutes(parse(l["assigned_at"]), parse(l["first_qualifying_followup_at"]))
                 for l in assigned if l["initial_priority"] == p and l["first_qualifying_followup_at"]
                 and parse(l["first_qualifying_followup_at"]) <= cutoff]
        add(25, "priority", p, statistics.median(waits))
    # 26 Late-logged follow-ups (none in LF-005)
    add(26, "total", "all", 0)
    # 28 Open review cases, by who must act and by reason
    cases = []
    for e in stored:
        x = e["expected"]
        if x.get("review_queue"):
            if x["review_queue"] == "participant_redirect_review":
                code = "NO_REDIRECT_RULE"
            else:
                code = next((c for c in x["reason_codes"] if c in ACTION_OWNER_BY_CODE), x["reason_codes"][0])
            cases.append((code, x.get("action_owner")))
        if x.get("parallel_review"):
            cases.append((x["parallel_review"]["reason_code"], x["parallel_review"]["action_owner"]))
    add(28, "total", "all", len(cases))
    add_counts(28, "action_owner", Counter(owner for _, owner in cases))
    add_counts(28, "reason", Counter(code for code, _ in cases))
    # 30 Absence alerts (none in LF-005)
    add(30, "total", "all", 0)
    # 31 CRM in sync: every lead's contact shows LeadFlow's values
    add(31, "total", "all", len(leads), len(leads))
    # 32 CRM updates waiting to retry or given up (none in LF-005)
    add(32, "total", "all", 0)
    return rows


def render(rows):
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=["kpi_id", "breakdown", "member", "numerator", "denominator"],
                            lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if the seed file is out of date")
    args = parser.parse_args()
    content = render(build_rows())
    if args.check:
        if not SEED.exists() or SEED.read_text(encoding="utf-8") != content:
            print(f"{SEED.relative_to(ROOT)} is out of date: run python tools/expected_kpis.py")
            return 1
        print("expected KPI seed is up to date")
        return 0
    SEED.parent.mkdir(parents=True, exist_ok=True)
    SEED.write_text(content, encoding="utf-8")
    print(f"wrote {SEED.relative_to(ROOT)} ({content.count(chr(10)) - 1} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
