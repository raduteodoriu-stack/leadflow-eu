"""LF-008: prove that the database totals match the source batch.

Two kinds of check, each reporting expected, actual and the difference:

- Source vs database (S checks): every inbound event, follow-up and engagement action
  in the source batch is accounted for, and nothing in the database is unexplained.
  Events received = events stored + repeats ignored.
- Database consistency (C checks, SQL/reconciliation/lf008_consistency_checks.sql):
  one decision per event, one owner and one SLA per assigned lead, a review case for
  every exception, the round-robin position matching the last assignment, no orphans.

A clean run has zero differences everywhere. `reconcile` only reads.
"""
from __future__ import annotations

import pathlib

from leadflow.normalise import clean_text, normalise_source_system
from leadflow.validate import standardise_engagement

SQL_FILE = pathlib.Path(__file__).resolve().parents[1] / "SQL/reconciliation/lf008_consistency_checks.sql"


def _check(check_id, description, expected, actual, examples=()):
    return {"id": check_id, "check": description, "expected": expected, "actual": actual,
            "difference": actual - expected, "examples": ", ".join(map(str, list(examples)[:3]))}


def source_checks(conn, dataset, rules):
    events = dataset["events"]
    seen, stored_keys, repeats, without_id = set(), set(), 0, 0
    for item in sorted(events, key=lambda e: (e["received_at"], e["seq"])):
        raw = item["input"]
        system, event_id = normalise_source_system(raw.get("source_system")), clean_text(raw.get("source_event_id"))
        if not system or not event_id:
            without_id += 1
            continue
        if (system, event_id) in seen:
            repeats += 1
            continue
        seen.add((system, event_id))
    stored_keys = seen
    db_keys = {(s, e) for s, e in conn.execute(
        "SELECT source_system, source_event_id FROM ingestion_events WHERE source_event_id IS NOT NULL").fetchall()}
    db_without_id = conn.execute(
        "SELECT count(*) FROM ingestion_events WHERE source_event_id IS NULL").fetchone()[0]
    stored = conn.execute("SELECT count(*) FROM ingestion_events").fetchone()[0]

    activities = {(a["source_system"], a["activity_id"]) for a in dataset.get("followup_activities", [])}
    db_activities = {tuple(r) for r in conn.execute(
        "SELECT source_system, source_activity_id FROM followup_activities").fetchall()}

    # Engagement: every action carried by an event that resolved to a lead is stored on that lead.
    engagement = {(s, e): lead for s, e, lead in conn.execute(
        "SELECT source_system, source_event_id, lead_id FROM engagement_events").fetchall()}
    missing_engagement, expected_engagement = [], 0
    for system, raw, lead_id in conn.execute(
            "SELECT source_system, raw_payload, lead_id FROM ingestion_events WHERE lead_id IS NOT NULL").fetchall():
        kept = standardise_engagement(raw.get("engagement_events"), None, rules, [])["events"]
        for action in kept:
            if not action.get("id") or not action.get("occurred_at"):
                continue
            expected_engagement += 1
            if engagement.get((system, action["id"])) != lead_id:
                missing_engagement.append(action["id"])

    return [
        _check("S01", "Events received = events stored + repeats ignored", len(events), stored + repeats),
        _check("S02", "Every source event with an ID is stored", len(stored_keys), len(stored_keys & db_keys),
               sorted(e for _, e in stored_keys - db_keys)),
        _check("S03", "No stored event is missing from the source", 0, len(db_keys - stored_keys),
               sorted(e for _, e in db_keys - stored_keys)),
        _check("S04", "Events without an ID are stored as rejected", without_id, db_without_id),
        _check("S05", "Every follow-up activity is stored", len(activities), len(activities & db_activities),
               sorted(a for _, a in activities - db_activities)),
        _check("S06", "No stored follow-up is missing from the source", 0, len(db_activities - activities),
               sorted(a for _, a in db_activities - activities)),
        _check("S07", "Every engagement action is stored on its lead", expected_engagement,
               expected_engagement - len(missing_engagement), missing_engagement),
    ]


def consistency_checks(conn):
    rows = conn.execute(SQL_FILE.read_text(encoding="utf-8")).fetchall()
    return [_check(cid, description, 0, problems, [examples] if examples else ())
            for cid, description, problems, examples in rows]


def reconcile(conn, dataset, rules):
    """All checks, source first. A clean database has difference 0 in every row."""
    return source_checks(conn, dataset, rules) + consistency_checks(conn)


def report_markdown(checks, title="LeadFlow EU reconciliation", context=""):
    bad = [c for c in checks if c["difference"]]
    lines = [f"# {title}", ""]
    if context:
        lines += [context, ""]
    lines += [f"**Result: {'BALANCED' if not bad else f'{len(bad)} check(s) with differences'}** "
              f"({len(checks)} checks)", "",
              "| Check | What it proves | Expected | Actual | Difference | Examples |",
              "| --- | --- | ---: | ---: | ---: | --- |"]
    for c in checks:
        lines.append(f"| {c['id']} | {c['check']} | {c['expected']} | {c['actual']} | {c['difference']} | "
                     f"{c['examples']} |")
    return "\n".join(lines) + "\n"


def record_run(conn, checks, *, database, source, rule_version, run_at, report_path=None):
    """Save one reconciliation result in reconciliation_runs (LF-011), for the dashboard's trust badge.

    Returns the run id. Needs migration 006.
    """
    from psycopg.types.json import Jsonb

    failed = sum(1 for c in checks if c["difference"])
    return conn.execute(
        """INSERT INTO reconciliation_runs (run_at, database_name, source_name, rule_version, check_count,
               failed_checks, is_balanced, results, report_path)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING run_id""",
        (run_at, database, source, rule_version, len(checks), failed, failed == 0, Jsonb(checks),
         report_path)).fetchone()[0]
