"""Unit tests: working-time calendar (Mon-Fri 09:00-18:00 Europe/Madrid)."""
from datetime import datetime

import pytest

from leadflow import load_rules
from leadflow.business_time import WorkingCalendar

CAL = WorkingCalendar.from_rules(load_rules())


def t(text):
    return datetime.fromisoformat(text)


@pytest.mark.parametrize("start, minutes, expected", [
    ("2026-11-03T10:00:00+01:00", 60, "2026-11-03T11:00:00+01:00"),   # simple
    ("2026-11-03T10:00:00+01:00", 480, "2026-11-03T18:00:00+01:00"),  # ends exactly at closing
    ("2026-11-06T17:55:00+01:00", 60, "2026-11-09T09:55:00+01:00"),   # Friday -> Monday (S-18)
    ("2026-11-07T11:00:00+01:00", 240, "2026-11-09T13:00:00+01:00"),  # Saturday arrival (S-19)
    ("2026-11-03T18:00:00+01:00", 60, "2026-11-04T10:00:00+01:00"),   # 18:00 is after hours (B-10)
    ("2026-11-03T08:30:00+01:00", 60, "2026-11-03T10:00:00+01:00"),   # before opening (B-11)
    ("2026-10-23T16:00:00+02:00", 480, "2026-10-26T15:00:00+01:00"),  # across the clock change (B-09)
])
def test_add_working_minutes(start, minutes, expected):
    assert CAL.add_working_minutes(t(start), minutes) == t(expected)


@pytest.mark.parametrize("a, b, minutes", [
    ("2026-11-02T10:00:00+01:00", "2026-11-02T17:58:00+01:00", 478),  # B-14
    ("2026-11-02T10:00:00+01:00", "2026-11-03T09:29:00+01:00", 509),  # B-15
    ("2026-11-06T17:00:00+01:00", "2026-11-09T10:00:00+01:00", 120),  # over a weekend
    ("2026-10-23T17:00:00+02:00", "2026-10-26T09:30:00+01:00", 90),   # over the clock change
    ("2026-11-03T12:00:00+01:00", "2026-11-03T11:00:00+01:00", 0),    # reversed
])
def test_working_minutes_between(a, b, minutes):
    assert CAL.working_minutes_between(t(a), t(b)) == minutes


def test_is_working_time():
    assert CAL.is_working_time(t("2026-11-03T09:00:00+01:00"))
    assert not CAL.is_working_time(t("2026-11-03T18:00:00+01:00"))
    assert not CAL.is_working_time(t("2026-11-07T11:00:00+01:00"))
