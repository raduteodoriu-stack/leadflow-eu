"""LF-009: SLA tracking, response targets, owner-unavailable alerts and reassignment.

The SLA tracker keeps every assigned lead's first-follow-up SLA up to date as time passes
and as follow-ups, absences and reassignments arrive. It works on the same in-memory
store as the decision engine and returns a list of CHANGES (status changes, alerts,
owner changes) that `leadflow/postgres.py` saves.

Rules (LF-002, option C 2026-10-23, decisions 2026-10-28):
- SLA: met if the first qualifying follow-up happened on or before the deadline (the
  deadline minute is on time); breached once the deadline has passed without one. A
  breach is spotted one minute after the deadline (the check runs every minute);
  `breached_at` is always the deadline itself.
- Response target: met / missed / pending, the same way. Measured, never a breach.
- A follow-up counts at the time it happened. If it is logged after the deadline but
  happened before it, the verdict is corrected (`evidence_corrected` when a breach had
  already been recorded) and LATE_LOGGED_FOLLOWUP is flagged to the Sales Manager.
- A follow-up after a breach is recorded in the history; the breach stays.
- Owner-unavailable alert: when a salesperson's absence starts (or when it is recorded,
  if later), every lead of theirs that is still pending gets an OWNER_UNAVAILABLE_PENDING
  review case for the Sales Manager, suggesting the next available salesperson in the
  country's rotation. Nobody is reassigned automatically.
- Reassignment keeps the original deadline and target and resolves the lead's open
  alerts. Only the owner at the time of a follow-up can satisfy the SLA.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from leadflow.decide import record_activity
from leadflow.routing import RepDirectory

MINUTE = timedelta(minutes=1)
ALERT = "OWNER_UNAVAILABLE_PENDING"
LATE = "LATE_LOGGED_FOLLOWUP"
ACTION_OWNER = "sales_manager"


def _at(value):
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


def _iso(moment):
    return moment.isoformat(timespec="seconds") if moment else None


def alert_key(lead_key, rep, starts):
    return f"{ALERT}:{lead_key}:{rep}:{_iso(_at(starts))}"


class SlaTracker:
    """Keeps SLA state current. Call `advance(moment)` before anything happening at `moment`.

    settings["unavailability"] is shared with the decision engine, so an absence recorded
    here also stops the rotation from picking that salesperson.
    """

    def __init__(self, store, rules, settings):
        self.store, self.rules, self.settings = store, rules, settings
        settings.setdefault("unavailability", [])

    # ------------------------------------------------------------------ helpers
    def _leads(self):
        return [lead for lead in self.store.contacts.values() if lead.get("owner") and lead.get("sla_deadline")]

    def _directory(self):
        return RepDirectory.from_settings(self.settings)

    @staticmethod
    def _trigger(absence):
        starts, recorded = _at(absence["from"]), _at(absence.get("recorded_at"))
        return max(starts, recorded) if recorded else starts

    # ------------------------------------------------------------------ time
    def advance(self, to):
        """Apply everything due up to and including `to`: breaches, missed targets, alerts."""
        to = _at(to)
        since = self.store.clock
        due = []
        for lead in self._leads():
            if lead.get("response_target_status") == "pending" and lead.get("target_at") \
                    and lead.get("first_followup_at") is None and lead["target_at"] + MINUTE <= to:
                due.append((lead["target_at"] + MINUTE, 1, "target", lead, None))
            if lead.get("sla_status") == "pending" and lead.get("first_followup_at") is None \
                    and lead["sla_deadline"] + MINUTE <= to:
                due.append((lead["sla_deadline"] + MINUTE, 0, "breach", lead, None))
        for absence in self.settings["unavailability"]:
            trigger = self._trigger(absence)
            if trigger <= to and (since is None or trigger > since):
                due.append((trigger, 2, "absence", None, absence))
        changes = []
        ordered = sorted(due, key=lambda d: (d[0], d[1], (d[3] or {}).get("lead_key", "")))
        # Everything due at the same moment is applied together, so each saved change carries the
        # lead's complete state at that moment (a P3 target and its deadline fall due together).
        for moment in sorted({d[0] for d in ordered}):
            group = [d for d in ordered if d[0] == moment]
            for _, _, kind, lead, _ in group:
                if kind == "target":
                    lead["response_target_status"] = "missed"
                elif kind == "breach":
                    lead.update(sla_status="breached", breach_detected_at=moment)
            for _, _, kind, lead, absence in group:
                if kind == "breach":
                    changes.append({"kind": "status", "lead_key": lead["lead_key"], "at": moment,
                                    "event_type": "status_changed", "previous_status": "pending",
                                    "new_status": "breached", "activity": None, **_state(lead)})
                elif kind == "target":
                    changes.append({"kind": "target", "lead_key": lead["lead_key"], "at": moment,
                                    "status": "missed", **_state(lead)})
                else:
                    changes += self._alerts(absence, moment)
        if since is None or to > since:
            self.store.clock = to
        return changes

    def _alerts(self, absence, moment):
        rep, until = absence["rep"], _at(absence.get("until"))
        if until is not None and moment >= until:
            return []
        directory = self._directory()
        changes = []
        for lead in sorted(self._leads(), key=lambda l: l["lead_key"]):
            if lead["owner"] != rep or lead.get("sla_status") != "pending" or lead["assigned_at"] > moment \
                    or moment > lead["sla_deadline"]:
                continue
            key = alert_key(lead["lead_key"], rep, absence["from"])
            if key in self.store.alerts:
                continue
            suggested = self._suggest(lead, rep, moment, directory)
            self.store.alerts[key] = {"lead_key": lead["lead_key"], "status": "open"}
            change = {"kind": "case_opened", "key": key, "lead_key": lead["lead_key"], "at": moment,
                      "reason_code": ALERT, "action_owner": ACTION_OWNER, "suggested_owner": suggested,
                      "absent_owner": rep, "absence_from": _iso(_at(absence["from"])),
                      "absence_until": _iso(until), "sla_deadline": _iso(lead["sla_deadline"])}
            if suggested is None:
                change["note"] = f"no available salesperson in {lead.get('country_code')}"
            changes.append(change)
        return changes

    def _suggest(self, lead, absent, moment, directory):
        reps = directory.reps_for(lead.get("country_code"))
        if not reps:
            return None
        pointer = self.store.rotation.get(lead.get("country_code"))
        start = reps.index(pointer) if pointer in reps else 0
        for step in range(len(reps)):
            rep = reps[(start + step) % len(reps)]
            if rep != absent and directory.is_active(rep, moment):
                return rep
        return None

    # ------------------------------------------------------------------ inputs
    def activity(self, activity):
        """A follow-up arrives (at `logged_at`, default its occurred time). Returns changes."""
        logged = _at(activity.get("logged_at") or activity["occurred_at"])
        changes = self.advance(logged)
        email = (activity.get("lead_email") or "").strip().lower()
        lead = self.store.contact(email)
        first_before = lead["first_followup_at"] if lead else None
        qualifying = record_activity(self.store, self.rules, activity)
        changes.append({"kind": "activity", "lead_key": lead["lead_key"] if lead else None, "at": logged,
                        "activity": activity, "qualifying": qualifying})
        if not qualifying or lead["first_followup_at"] == first_before or not lead.get("sla_deadline"):
            return changes
        first, deadline, previous = lead["first_followup_at"], lead["sla_deadline"], lead.get("sla_status")
        if first <= deadline:
            new = "met"
            event = {"breached": "evidence_corrected", "pending": "status_changed"}.get(previous, "followup_recorded")
        else:
            new = "breached"
            event = "status_changed" if previous == "pending" else "followup_recorded"
            if lead.get("breach_detected_at") is None:
                lead["breach_detected_at"] = logged
        lead["sla_status"] = new
        target = lead.get("target_at")
        target_changed = False
        if target is not None:
            status = "met" if first <= target else "missed"
            target_changed = status != lead.get("response_target_status")
            lead["response_target_status"] = status
        changes.append({"kind": "status", "lead_key": lead["lead_key"], "at": logged, "event_type": event,
                        "previous_status": previous, "new_status": new, "activity": activity, **_state(lead)})
        if target_changed:
            changes.append({"kind": "target", "lead_key": lead["lead_key"], "at": logged,
                            "status": lead["response_target_status"], **_state(lead)})
        if first <= deadline < logged:
            changes.append({"kind": "case_opened", "key": f"{LATE}:{lead['lead_key']}:{_iso(first)}",
                            "lead_key": lead["lead_key"], "at": logged, "reason_code": LATE,
                            "action_owner": ACTION_OWNER, "occurred_at": _iso(first), "logged_at": _iso(logged),
                            "sla_deadline": _iso(deadline), "owner": activity.get("owner")})
        return changes

    def absence(self, absence):
        """A salesperson's absence is recorded. Alerts fire now if it has already started."""
        recorded = _at(absence.get("recorded_at") or absence["from"])
        changes = self.advance(recorded)
        self.settings["unavailability"].append(absence)
        changes.append({"kind": "absence", "at": recorded, "absence": absence})
        trigger = self._trigger(absence)
        if trigger <= self.store.clock:
            changes += self._alerts(absence, trigger)
        return changes

    def reassign(self, lead_key, to, at, by):
        """The Sales Manager moves a lead to another salesperson. Deadline and target stay."""
        at = _at(at)
        changes = self.advance(at)
        lead = self.store.contact(lead_key)
        previous = lead["owner"]
        lead["owner"] = to
        history = lead.get("owner_history") or [{"owner": previous, "from": lead["assigned_at"]}]
        lead["owner_history"] = history + [{"owner": to, "from": at}]
        resolved = [key for key, alert in sorted(self.store.alerts.items())
                    if alert["lead_key"] == lead_key and alert["status"] == "open"]
        for key in resolved:
            self.store.alerts[key]["status"] = "resolved"
        changes.append({"kind": "owner_changed", "lead_key": lead_key, "at": at, "previous_owner": previous,
                        "new_owner": to, "by": by, "resolved_alerts": resolved})
        return changes


def _state(lead):
    """The lead's SLA state as it stands at a change, so the change can be saved on its own."""
    return {"state": {"sla_status": lead.get("sla_status"), "response_target_status": lead.get("response_target_status"),
                      "breach_detected_at": lead.get("breach_detected_at"),
                      "first_followup_at": lead.get("first_followup_at")}}


def outcome(lead):
    """The lead's SLA and response-target outcome as reported (after `advance`)."""
    first, deadline = lead.get("first_followup_at"), lead.get("sla_deadline")
    return {"sla_outcome": lead.get("sla_status"), "response_target_outcome": lead.get("response_target_status"),
            "qualifying_followup_at": _iso(first), "late_followup": bool(first and deadline and first > deadline),
            "breached_at": _iso(deadline) if lead.get("sla_status") == "breached" else None,
            "breach_detected_at": _iso(lead.get("breach_detected_at"))}
