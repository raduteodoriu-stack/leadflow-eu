"""Working-time arithmetic (Monday-Friday 09:00-18:00, Europe/Madrid in LF-RULES-v1.0).

Working time runs from the start time up to, but not including, the end time.
All results are returned in the rules' time zone.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta


class WorkingCalendar:
    def __init__(self, tz, weekdays, start, end):
        self.tz = tz
        self.weekdays = frozenset(weekdays)
        self.start = start
        self.end = end

    @classmethod
    def from_rules(cls, rules):
        return cls(rules.timezone, rules.work_weekdays, rules.work_start, rules.work_end)

    def _window(self, day):
        return (datetime.combine(day, self.start, self.tz), datetime.combine(day, self.end, self.tz))

    def is_working_time(self, moment):
        local = moment.astimezone(self.tz)
        return local.weekday() in self.weekdays and self.start <= local.time() < self.end

    def next_working_moment(self, moment):
        """The moment itself if it is working time, otherwise the next working start."""
        local = moment.astimezone(self.tz)
        day = local.date()
        while True:
            if day.weekday() in self.weekdays:
                opens, closes = self._window(day)
                if local < closes:
                    return max(local, opens)
            day += timedelta(days=1)
            local = datetime.combine(day, time(0), self.tz)

    def add_working_minutes(self, start, minutes):
        """Moment reached after `minutes` of working time from `start`."""
        if minutes < 0:
            raise ValueError("minutes must not be negative")
        current = self.next_working_moment(start)
        remaining = timedelta(minutes=minutes)
        while True:
            _, closes = self._window(current.date())
            room = closes - current
            if remaining <= room:
                return current + remaining
            remaining -= room
            current = self.next_working_moment(closes)

    def working_minutes_between(self, earlier, later):
        """Whole minutes of working time between two moments (0 if `later` is not after `earlier`)."""
        if later <= earlier:
            return 0
        a, b = earlier.astimezone(self.tz), later.astimezone(self.tz)
        total = timedelta(0)
        day = a.date()
        while day <= b.date():
            if day.weekday() in self.weekdays:
                opens, closes = self._window(day)
                lo, hi = max(a, opens), min(b, closes)
                if hi > lo:
                    total += hi - lo
            day += timedelta(days=1)
        return int(total.total_seconds() // 60)
