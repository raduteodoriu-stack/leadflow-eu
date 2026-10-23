"""Rebuild docs/test_scenarios.md from tests/fixtures/scenarios/*.json.

Run from the repo root:  python3 tools/scenario_summary.py
The JSON files are the source of truth; this page is a read-only view.
"""
import json
import pathlib
from datetime import datetime

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "tests" / "fixtures" / "scenarios"
OUT = ROOT / "docs" / "test_scenarios.md"


def when(ts):
    if not ts:
        return "—"
    return datetime.fromisoformat(ts).strftime("%a %d %b %H:%M")


def cell(text):
    return str(text).replace("|", "\\|") if text not in (None, "") else "—"


def row(s):
    e = s["expected"]
    sla = e.get("sla") or {}
    if "sla_outcome" in e:
        result = f"SLA {e['sla_outcome']}"
        handled = e.get("qualifying_followup_at") and f"follow-up {when(e['qualifying_followup_at'])}"
        deadline = "—"
    else:
        result = e.get("outcome", "—")
        handled = e.get("owner") or e.get("review_queue") or "—"
        if e.get("parallel_review"):
            handled += f" + {e['parallel_review']['reason_code']}"
        if sla.get("deadline"):
            deadline = when(sla["deadline"])
        elif sla.get("new_sla_created") is False:
            deadline = "no new SLA"
        else:
            deadline = "—"
    prio = e.get("priority")
    prio = f"{prio} (rule {e.get('priority_rule')})" if prio else "—"
    codes = ", ".join(e.get("reason_codes", [])) or "—"
    reviewed = "yes" if s["label"].get("reviewed_by") else "no"
    return (f"| {s['id']} | {cell(s['title'])} | {when(s['evaluation_time'])} | {cell(result)} | {cell(handled)} "
            f"| {prio} | {deadline} | {cell(codes)} | {reviewed} |")


def main():
    files = sorted(SRC.glob("*.json"))
    scenarios = [json.loads(f.read_text()) for f in files]
    head = ("| ID | Scenario | Evaluated | Outcome | Owner / queue | Priority | SLA deadline | Reason codes | Reviewed |\n"
            "|---|---|---|---|---|---|---|---|---|")
    groups = [("Scenarios", "S-"), ("Boundary tests", "B-")]
    lines = [
        "# LF-004 Test scenarios",
        "",
        "Generated from `tests/fixtures/scenarios/*.json` by `tools/scenario_summary.py`. "
        "Do not edit by hand: change the JSON and rerun the script.",
        "",
        "Times are Europe/Madrid. Expected outcomes are hand-labelled from LF-001, LF-002 "
        "and the 2026-10-23 rule clarifications (rule version LF-RULES-v1.0).",
        "",
    ]
    for title, prefix in groups:
        subset = [s for s in scenarios if s["id"].startswith(prefix)]
        lines += [f"## {title} ({len(subset)})", "", head] + [row(s) for s in subset] + [""]
    reviewed = sum(1 for s in scenarios if s["label"].get("reviewed_by"))
    lines += [f"**Review status:** {reviewed} of {len(scenarios)} labels independently reviewed.", ""]
    OUT.write_text("\n".join(lines))
    print(f"Wrote {OUT.relative_to(ROOT)} ({len(scenarios)} scenarios)")


if __name__ == "__main__":
    main()
