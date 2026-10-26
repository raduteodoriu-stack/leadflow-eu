"""LF-007: representatives, availability and round-robin."""
from __future__ import annotations

from datetime import datetime

DEFAULT_REPRESENTATIVES = {"ES": ["ES-01", "ES-02"], "PT": ["PT-01", "PT-02"], "FR": ["FR-01", "FR-02"]}


class RepDirectory:
    """Who can receive leads, and when.

    settings keys: representatives {country: [rep, ...]}, active_reps [rep, ...] (optional),
    unavailability [{rep, from, until}] (optional; until may be null).
    """

    def __init__(self, representatives=None, active_reps=None, unavailability=()):
        self.representatives = {c: sorted(r) for c, r in (representatives or DEFAULT_REPRESENTATIVES).items()}
        self.active = set(active_reps) if active_reps is not None else None
        self.periods = [(u["rep"], _at(u["from"]), _at(u["until"]) if u.get("until") else None)
                        for u in unavailability]

    @classmethod
    def from_settings(cls, settings):
        return cls(settings.get("representatives"), settings.get("active_reps"), settings.get("unavailability", ()))

    def reps_for(self, country):
        return self.representatives.get(country, [])

    def is_active(self, rep, moment):
        if self.active is not None and rep not in self.active:
            return False
        return not any(r == rep and start <= moment and (end is None or moment < end) for r, start, end in self.periods)


def _at(value):
    return value if isinstance(value, datetime) else datetime.fromisoformat(value)


def next_in_rotation(store, country, moment, directory):
    """Pick the next active rep in ID order; advance the pointer only when someone is chosen.

    Returns (rep or None, skipped reps).
    """
    reps = directory.reps_for(country)
    if not reps:
        return None, []
    pointer = store.rotation.setdefault(country, reps[0])
    start = reps.index(pointer) if pointer in reps else 0
    skipped = []
    for step in range(len(reps)):
        rep = reps[(start + step) % len(reps)]
        if directory.is_active(rep, moment):
            store.rotation[country] = reps[(start + step + 1) % len(reps)]
            return rep, skipped
        skipped.append(rep)
    return None, skipped
