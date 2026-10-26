"""Unit tests: round-robin and availability (LF-007)."""
from datetime import datetime

from leadflow import ContactStore
from leadflow.routing import RepDirectory, next_in_rotation

T = datetime.fromisoformat("2026-11-03T10:00:00+01:00")


def test_rotation_alternates_in_id_order():
    store, reps = ContactStore(), RepDirectory()
    owners = [next_in_rotation(store, "ES", T, reps)[0] for _ in range(3)]
    assert owners == ["ES-01", "ES-02", "ES-01"]


def test_inactive_rep_is_skipped_and_pointer_moves_past_the_chosen_rep():
    store = ContactStore()
    reps = RepDirectory(active_reps=["ES-02", "PT-01", "PT-02", "FR-01", "FR-02"])
    assert next_in_rotation(store, "ES", T, reps) == ("ES-02", ["ES-01"])
    assert store.rotation["ES"] == "ES-01"


def test_no_eligible_owner_leaves_pointer_unchanged():
    store = ContactStore()
    reps = RepDirectory(unavailability=[{"rep": r, "from": "2026-11-03T00:00:00+01:00", "until": "2026-11-04T00:00:00+01:00"}
                                        for r in ("PT-01", "PT-02")])
    store.rotation["PT"] = "PT-02"
    assert next_in_rotation(store, "PT", T, reps) == (None, ["PT-02", "PT-01"])
    assert store.rotation["PT"] == "PT-02"


def test_open_ended_unavailability():
    reps = RepDirectory(unavailability=[{"rep": "FR-02", "from": "2026-11-02T00:00:00+01:00", "until": None}])
    assert reps.is_active("FR-02", datetime.fromisoformat("2026-10-30T10:00:00+01:00"))
    assert not reps.is_active("FR-02", T)
