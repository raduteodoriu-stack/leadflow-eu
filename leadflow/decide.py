"""LF-007: decide what happens to a prepared event (LF-002 steps 6-9, in memory).

`decide` takes the prepared event from LF-006 and returns the decision in the same shape as
the LF-004/LF-005 expected outcomes. `process_event` runs both halves. `record_activity`
registers follow-ups, because a priority increase before first contact shortens the target.
"""
from __future__ import annotations

from datetime import datetime

from leadflow.business_time import WorkingCalendar
from leadflow.normalise import normalise_country
from leadflow.prepare import prepare_event
from leadflow.priority import decide_priority
from leadflow.routing import RepDirectory, next_in_rotation
from leadflow.scoring import engagement_score, fit_score

RANK = {"P1": 1, "P2": 2, "P3": 3}


def _at(value):
    return value if isinstance(value, datetime) else datetime.fromisoformat(value)


def _iso(moment):
    return moment.isoformat(timespec="seconds") if moment else None


def _public(engagement):
    return {"total": engagement["total"], "status": engagement["status"], "band": engagement["band"]}


class Context:
    def __init__(self, store, rules, settings, calendar=None):
        self.store, self.rules, self.settings = store, rules, settings or {}
        self.calendar = calendar or WorkingCalendar.from_rules(rules)
        self.reps = RepDirectory.from_settings(self.settings)
        for country, rep in (self.settings.get("initial_rotation") or {}).items():
            store.rotation.setdefault(country, rep)
        self.routing = rules.data["review_routing"]
        self.sla = rules.data["sla"]

    def pointer(self, country):
        if country not in self.rules.supported_countries:
            return None
        reps = self.reps.reps_for(country)
        return self.store.rotation.get(country, reps[0] if reps else None)

    def action_owner(self, codes):
        for code in codes:
            if code in self.routing["action_owner_by_code"]:
                return self.routing["action_owner_by_code"][code]
        return None


def process_event(raw, received_at, store, rules, settings=None, calendar=None):
    """Prepare (LF-006) and decide (LF-007) one event. Returns (prepared, decision)."""
    ctx = Context(store, rules, settings, calendar)
    prepared = prepare_event(raw, received_at, store, rules, ctx.settings, ctx.calendar)
    return prepared, decide(prepared, ctx, raw)


def record_activity(store, rules, activity):
    """Register a follow-up; only a human call or individual email by the lead's owner counts."""
    cfg = rules.data["qualifying_followup"]
    lead = store.contact((activity.get("lead_email") or "").strip().lower())
    if not lead or not lead.get("owner") or not lead.get("assigned_at"):
        return False
    if activity.get("type") not in cfg["types"] or (cfg["exclude_automated"] and activity.get("automated")):
        return False
    if cfg["by_owner_only"] and activity.get("owner") != lead["owner"]:
        return False
    at = _at(activity["occurred_at"])
    if at < lead["assigned_at"]:
        return False
    if lead["first_followup_at"] is None or at < lead["first_followup_at"]:
        lead["first_followup_at"] = at
    return True


def decide(prepared, ctx, raw=None):
    t = _at(prepared["event"]["received_at"])
    status = prepared["status"]
    codes = list(prepared["reason_codes"])
    if status == "rejected":
        country = normalise_country((raw or {}).get("business_country"), ctx.rules)[0]
        return {"outcome": "rejected", "event_stored": True, "processing_status": "rejected",
                "error_code": "SOURCE_EVENT_INVALID", "lead_created": False, "owner": None,
                "review_queue": ctx.routing["blocked_queue"], "action_owner": ctx.action_owner(codes),
                "round_robin_advanced": False, "round_robin_next_after": ctx.pointer(country),
                "fit": None, "engagement": None, "priority": None, "priority_rule": None,
                "reason_codes": codes, "sla": None, "response_target": None}
    if status == "duplicate":
        return _replay(prepared, ctx, codes, raw)
    if status == "participant":
        return _participant(prepared, ctx, codes)

    match = prepared["identity"]["match"]
    store = ctx.store
    lead = store.contact(prepared["identity"]["lead_key"] or prepared["contact"]["normalised_email"]) \
        if match != "unresolved" else None
    events = lead["engagement_events"] if lead else prepared["engagement"]["events"]
    fit = fit_score(prepared["company"], ctx.rules)
    engagement = engagement_score(events, prepared["engagement"]["coverage"], t, ctx.rules)
    priority, rule, priority_code = decide_priority(fit, engagement, prepared["relationship"], ctx.rules)
    score_codes = [priority_code]
    if fit["status"] == "incomplete":
        score_codes.append("FIT_INCOMPLETE")
    if engagement["status"] == "unknown":
        score_codes.append("ENGAGEMENT_UNKNOWN")
    scored = {"fit": fit, "engagement": _public(engagement), "priority": priority, "priority_rule": rule}
    country = prepared["country"]["code"]

    if match == "unresolved":  # invalid email: no lead can be created
        decision = {"outcome": "review", "processing_status": "review_required", "normalised_email": None,
                    "country_code": country if country in ctx.rules.supported_countries else None,
                    "lead_created": False, "owner": None}
        decision.update(_waiting(ctx, codes, country, t))
        decision.update(scored, reason_codes=codes + score_codes)
        return decision
    if match in ("existing", "recontact", "crm_match"):
        return _returning(prepared, ctx, lead, codes, score_codes, scored, priority, rule, t)
    return _new_lead(prepared, ctx, lead, codes, score_codes, scored, priority, rule, t)


def _waiting(ctx, codes, country, t):
    return {"review_queue": ctx.routing["blocked_queue"], "action_owner": ctx.action_owner(codes),
            "round_robin_advanced": False, "round_robin_next_after": ctx.pointer(country),
            "sla": None, "response_target": None, "waiting_since": _iso(t)}


def _new_lead(prepared, ctx, lead, codes, score_codes, scored, priority, rule, t):
    country = prepared["country"]["code"]
    lead.update(priority=priority, priority_rule=rule, initial_priority=priority)
    decision = {"normalised_email": prepared["contact"]["normalised_email"], "country_code": country,
                "lead_created": True}
    if "SUPPLIER_REVIEW" in codes:
        decision["parallel_review"] = {"reason_code": "SUPPLIER_REVIEW",
                                       "action_owner": ctx.routing["parallel_cases"]["SUPPLIER_REVIEW"]}
    owner, skipped, outcome = None, [], None
    if not prepared["blocking"]:
        colleague = prepared["identity"]["same_company_colleague"]
        colleague_lead = ctx.store.contact(colleague["lead_key"]) if colleague else None
        if colleague_lead and colleague_lead["owner"] and ctx.reps.is_active(colleague_lead["owner"], t):
            owner, outcome = colleague_lead["owner"], "assigned_to_company_owner"
            codes.append("SAME_COMPANY_RECENT_CONTACT")
        else:
            owner, skipped = next_in_rotation(ctx.store, country, t, ctx.reps)
            if owner is None:
                codes.append("NO_ELIGIBLE_OWNER")
            else:
                outcome = "assigned"
    if owner is None:
        decision.update(outcome="review", owner=None)
        decision.update(_waiting(ctx, codes, country, t))
        decision.update(scored, reason_codes=codes + score_codes)
        return decision
    sla_cfg = ctx.sla
    allowance = sla_cfg["response_target_business_minutes"][priority]
    lead.update(owner=owner, assigned_at=t,
                sla_deadline=ctx.calendar.add_working_minutes(t, sla_cfg["deadline_business_minutes"]),
                target_at=ctx.calendar.add_working_minutes(t, allowance))
    decision.update(outcome=outcome, owner=owner, review_queue=None,
                    round_robin_advanced=outcome == "assigned", round_robin_next_after=ctx.pointer(country))
    decision.update(scored, reason_codes=codes + score_codes)
    decision["sla"] = {"starts": _iso(t), "business_clock_starts": _iso(ctx.calendar.next_working_moment(t)),
                       "allowance_business_minutes": sla_cfg["deadline_business_minutes"],
                       "deadline": _iso(lead["sla_deadline"])}
    decision["response_target"] = {"priority": priority, "allowance_business_minutes": allowance,
                                   "target_at": _iso(lead["target_at"])}
    if skipped:
        decision["rotation_skipped"] = skipped
    return decision


def _returning(prepared, ctx, lead, codes, score_codes, scored, priority, rule, t):
    match = prepared["identity"]["match"]
    country = prepared["country"]["code"]
    owner = lead.get("owner")
    inactive = bool(owner) and not ctx.reps.is_active(owner, t)
    if inactive and match != "crm_match":
        codes.append("OWNER_REVIEW")
    first = lead.get("first_followup_at")
    followed = first is not None and first <= t
    previous_priority, previous_target = lead.get("priority"), lead.get("target_at")
    changed = False
    if previous_target and previous_priority and not followed and RANK[priority] < RANK[previous_priority]:
        candidate = min(previous_target, ctx.calendar.add_working_minutes(
            t, ctx.sla["response_target_business_minutes"][priority]))
        if candidate < previous_target:
            lead["target_changes"].append({"at": _iso(t), "from": _iso(previous_target), "to": _iso(candidate),
                                           "new_priority": priority})
            lead["target_at"] = candidate
            changed = True
    lead.update(priority=priority, priority_rule=rule)
    deadline = lead.get("sla_deadline")
    if deadline is None:
        existing = None
    elif first is not None and first <= deadline:
        existing = "met"
    elif first is not None or t > deadline:
        existing = "breached"
    else:
        existing = "pending"
    if match == "crm_match":
        outcome = "attached_to_existing_contact"
    else:
        outcome = "review" if inactive else "existing_owner_kept"
    decision = {"outcome": outcome, "lead_created": False,
                "normalised_email": prepared["contact"]["normalised_email"], "country_code": country,
                "owner": owner, "review_queue": ctx.routing["blocked_queue"] if outcome == "review" else None,
                "action_owner": "sales_manager" if outcome == "review" else None,
                "round_robin_advanced": False, "round_robin_next_after": ctx.pointer(country)}
    decision.update(scored, reason_codes=codes + score_codes)
    decision["sla"] = {"new_sla_created": False, "starts": _iso(lead.get("assigned_at")),
                       "allowance_business_minutes": ctx.sla["deadline_business_minutes"] if deadline else None,
                       "deadline": _iso(deadline), "deadline_changed": False,
                       "followed_up_before_event": followed, "existing_outcome": existing}
    decision["response_target"] = None if followed else {
        "previous_priority": previous_priority, "previous_target_at": _iso(previous_target), "priority": priority,
        "allowance_business_minutes": ctx.sla["response_target_business_minutes"][priority],
        "target_at": _iso(lead.get("target_at")), "target_changed": changed}
    if match == "crm_match":
        decision["stored_email_kept"] = lead["lead_key"]
        decision["parallel_review"] = {"reason_code": "IDENTITY_REVIEW",
                                       "action_owner": ctx.routing["parallel_cases"]["IDENTITY_REVIEW"]}
    return decision


def _replay(prepared, ctx, codes, raw=None):
    lead = ctx.store.contact(prepared["identity"]["lead_key"]) if prepared["identity"]["lead_key"] else None
    lead = lead or {}
    country = lead.get("country_code") or normalise_country((raw or {}).get("business_country"), ctx.rules)[0]
    return {"outcome": "duplicate_event_ignored", "event_stored_again": False, "new_decision": False,
            "lead_created": False, "owner": lead.get("owner"), "review_queue": None, "round_robin_advanced": False,
            "round_robin_next_after": ctx.pointer(country),
            "priority": lead.get("priority"), "priority_rule": lead.get("priority_rule"), "reason_codes": codes,
            "sla": {"deadline": _iso(lead.get("sla_deadline")), "deadline_changed": False},
            "response_target": {"priority": lead.get("priority"), "target_at": _iso(lead.get("target_at")),
                                "target_changed": False}}


def _participant(prepared, ctx, codes):
    country = prepared["country"]["code"]
    rule = prepared["redirect_rule"]
    decision = {"normalised_email": None, "country_code": country, "lead_created": False, "owner": None,
                "round_robin_advanced": False, "round_robin_next_after": ctx.pointer(country),
                "fit": None, "engagement": None, "priority": None, "priority_rule": None,
                "reason_codes": codes, "sla": None, "response_target": None}
    method = ctx.rules.data["participant_referral_method"]
    if rule:
        decision.update(outcome="redirected", processing_status="redirected", review_queue=None,
                        referral={"referral_method": method, "attempt_status": "simulated",
                                  "supplier_code": rule.get("supplier_code"),
                                  "destination_url": rule.get("destination_url"), "personal_data_transferred": False})
    else:
        decision.update(outcome="review", processing_status="review_required",
                        review_queue=ctx.routing["participant_queue"], action_owner="revops",
                        referral={"referral_method": method, "attempt_status": "review_required",
                                  "error_code": "NO_REDIRECT_RULE", "personal_data_transferred": False})
    return decision
