"""Load the versioned business rules (LF-RULES-v*.json)."""
from __future__ import annotations

import json
import pathlib
import re
from datetime import time
from zoneinfo import ZoneInfo

RULES_DIR = pathlib.Path(__file__).resolve().parent / "rules"
DEFAULT_VERSION = "LF-RULES-v1.0"


class Rules:
    """Read-only view of one rules file."""

    def __init__(self, data):
        self.data = data
        self.version = data["rule_version"]
        self.timezone = ZoneInfo(data["timezone"])
        hours = data["working_hours"]
        self.work_weekdays = frozenset(hours["weekdays"])
        self.work_start = time.fromisoformat(hours["start"])
        self.work_end = time.fromisoformat(hours["end"])
        self.recontact_window = data["recontact_window_business_minutes"]
        self.same_company_window = data["same_company_window_business_minutes"]
        self.supported_countries = frozenset(data["supported_countries"])
        self.country_aliases = {alias.casefold(): code
                                for code, aliases in data["country_aliases"].items() for alias in aliases}
        self.email_re = re.compile(data["email_pattern"])
        self.unknown = data["unknown_value"]
        self.allowed = {field: frozenset(values) for field, values in data["allowed_values"].items()}
        self.readiness_fields = tuple(data["readiness_fields"])
        self.event_name_map = dict(data["engagement_event_name_map"])


def load_rules(version=DEFAULT_VERSION):
    path = RULES_DIR / f"{version}.json"
    if not path.exists():
        raise FileNotFoundError(f"No rules file for {version} in {RULES_DIR}")
    return Rules(json.loads(path.read_text(encoding="utf-8")))
