"""LF-007: contact priority (LF-002 decision table, rules 2-7; rule 1 = blocking, handled in routing)."""
from __future__ import annotations


def decide_priority(fit, engagement, relationship, rules):
    """Return (priority, rule number, reason code). The first matching rule wins."""
    complete = fit["status"] == "complete"
    if engagement["explicit_request"]:
        rule = 2
    elif complete and fit["band"] == "high" and engagement["band"] == "high":
        rule = 3
    elif engagement["band"] == "high":
        rule = 4
    elif complete and (fit["band"] == "high" or (fit["band"] == "medium" and engagement["band"] == "medium")):
        rule = 5
    elif not complete or engagement["status"] == "unknown" or relationship == "unknown":
        rule = 6
    else:
        rule = 7
    priority = {2: "P1", 3: "P1", 4: "P2", 5: "P2", 6: "P2", 7: "P3"}[rule]
    return priority, rule, rules.data["priority_reason_codes"][str(rule)]
