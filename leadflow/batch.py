"""Run a batch of inbound events and follow-up activities, in time order, saving each one.

A batch file has the LF-005 shape: {"metadata": {...settings...}, "events": [{"seq",
"received_at", "input"}], "followup_activities": [{...}]}. Items run in time order; an
activity at the same moment as an event goes first. `start`/`stop` select a slice of that
order, so a run can stop part-way and continue later (after `reload.load_store`).
"""
from __future__ import annotations

from datetime import datetime

from leadflow import postgres
from leadflow.crm import CrmWriter
from leadflow.sla import SlaTracker

SIMULATED = object()  # default: log CRM updates without contacting a CRM


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


def run(conn, dataset, store, rules, settings=None, start=0, stop=None, until=None, crm=SIMULATED):
    """Process items [start:stop] of the timeline; return {seq: decision} for the events run.

    Before each item the SLA tracker catches up to its time (breaches, missed targets,
    owner-unavailable alerts). `until`: also catch up to that moment at the end (a cut-off).
    After each step, the CRM writer (LF-010; simulated unless another writer is given,
    None to switch it off) brings the touched contacts up to date, in its own transaction.
    """
    settings = settings or settings_from(dataset)
    tracker = SlaTracker(store, rules, settings)
    writer = CrmWriter() if crm is SIMULATED else crm
    decisions = {}

    def to_crm(touched):
        if writer is not None and touched:
            writer.sync(conn, touched)

    for kind, item in timeline(dataset)[start:stop]:
        if kind == "activity":
            to_crm(touched_by(postgres.track(conn, tracker, "activity", item)))
        else:
            to_crm(touched_by(postgres.track(conn, tracker, "advance", item["received_at"])))
            prepared, decisions[item["seq"]] = postgres.process_and_record(
                conn, item["input"], item["received_at"], store, rules, settings)
            lead_key = postgres.lead_key_of(prepared)
            to_crm({lead_key: datetime.fromisoformat(item["received_at"])} if lead_key else {})
    if until is not None:
        to_crm(touched_by(postgres.track(conn, tracker, "advance", until)))
    return decisions


def touched_by(changes):
    """{lead: latest change time} for the SLA tracker's changes."""
    touched = {}
    for change in changes:
        if change.get("lead_key"):
            at = change["at"]
            touched[change["lead_key"]] = max(at, touched.get(change["lead_key"], at))
    return touched
