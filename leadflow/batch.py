"""Run a batch of inbound events and follow-up activities, in time order, saving each one.

A batch file has the LF-005 shape: {"metadata": {...settings...}, "events": [{"seq",
"received_at", "input"}], "followup_activities": [{...}]}. Items run in time order; an
activity at the same moment as an event goes first. `start`/`stop` select a slice of that
order, so a run can stop part-way and continue later (after `reload.load_store`).
"""
from __future__ import annotations

from datetime import datetime

from leadflow import postgres


def settings_from(dataset):
    meta = dataset["metadata"]
    return {"representatives": meta["representatives"], "initial_rotation": meta["initial_rotation"],
            "unavailability": meta.get("unavailability", []),
            "supplier_redirect_rules": meta.get("supplier_redirect_rules", {})}


def timeline(dataset):
    """[(kind, item)] in processing order; kind is 'event' or 'activity'."""
    items = [(datetime.fromisoformat(e["received_at"]), 1, i, "event", e) for i, e in enumerate(dataset["events"])]
    items += [(datetime.fromisoformat(a["occurred_at"]), 0, i, "activity", a)
              for i, a in enumerate(dataset.get("followup_activities", []))]
    return [(kind, item) for *_, kind, item in sorted(items, key=lambda x: x[:3])]


def run(conn, dataset, store, rules, settings=None, start=0, stop=None):
    """Process items [start:stop] of the timeline; return {seq: decision} for the events run."""
    settings = settings or settings_from(dataset)
    decisions = {}
    for kind, item in timeline(dataset)[start:stop]:
        if kind == "activity":
            postgres.record_and_save_activity(conn, item, store, rules)
        else:
            decisions[item["seq"]] = postgres.process_and_record(
                conn, item["input"], item["received_at"], store, rules, settings)[1]
    return decisions
