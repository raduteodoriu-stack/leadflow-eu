"""LF-011: what the reporting layer relies on in the database and the engine.

The dbt project (reporting/) has its own tests (`dbt build`), including the comparison of
every KPI with the LF-005 answer key. These pytest tests cover the parts outside dbt:

- the working-time function (migration 006) gives the same minutes as the engine;
- every stored enquiry keeps its source channel (an unknown value is stored as 'unknown');
- a reconciliation run is recorded for the dashboard's trust badge;
- the answer-key seed for dbt is up to date with the dataset.

PostgreSQL tests run against leadflow_eu_test only (see tests/pg_support.py).
"""
import random
import subprocess
import sys
from collections import Counter
from datetime import datetime, timedelta

import pytest
from pg_support import DATASET, EXPECTED, RULES, ROOT, SETTINGS, connect, rebuild

from leadflow import ContactStore, batch, reconcile
from leadflow.business_time import WorkingCalendar
from leadflow.postgres import SOURCE_CHANNELS, process_and_record

CUTOFF = DATASET["metadata"]["sla_cutoff"]


@pytest.fixture(scope="module")
def lf005():
    conn = connect()
    rebuild(conn)
    batch.run(conn, DATASET, ContactStore(), RULES, SETTINGS, until=CUTOFF)
    yield conn
    conn.close()


def test_working_minutes_matches_the_engine(lf005):
    calendar = WorkingCalendar.from_rules(RULES)
    rng = random.Random(11)
    base = datetime.fromisoformat("2026-10-01T00:00:00+02:00")
    pairs = []
    for _ in range(3000):  # 10 weeks, both clock changes' sides, weekends, nights, seconds
        a = base + timedelta(minutes=rng.randrange(0, 60 * 24 * 70), seconds=rng.randrange(60))
        b = a + timedelta(minutes=rng.choice([rng.randrange(-120, 900), rng.randrange(0, 60 * 24 * 20)]))
        pairs.append((a, b))
    rows = lf005.execute(
        "SELECT working_minutes(a, b) FROM unnest(%s::timestamptz[], %s::timestamptz[]) WITH ORDINALITY AS t(a, b, n) "
        "ORDER BY n", ([a for a, _ in pairs], [b for _, b in pairs])).fetchall()
    wrong = [(a, b, got, calendar.working_minutes_between(a, b))
             for (a, b), (got,) in zip(pairs, rows) if got != calendar.working_minutes_between(a, b)]
    assert not wrong, wrong[:3]


def test_every_enquiry_keeps_its_source_channel(lf005):
    stored = {e["seq"] for e in EXPECTED["events"]
              if e["expected"]["outcome"] != "duplicate_event_ignored" and e["source_event_id"]}
    expected = Counter(e["input"]["source_channel"] for e in DATASET["events"] if e["seq"] in stored)
    actual = Counter(dict(lf005.execute(
        "SELECT source_channel, count(*) FROM ingestion_events WHERE source_event_id IS NOT NULL "
        "GROUP BY source_channel").fetchall()))
    assert actual == expected
    assert len(actual) == len(SOURCE_CHANNELS)  # the dataset uses every channel


class Rollback(Exception):
    pass


def test_an_unrecognised_channel_is_stored_as_unknown(lf005):
    # A new enquiry with a channel outside the list, saved and then rolled back, so the
    # LF-005 rows the other tests use are left exactly as they were.
    raw = dict(DATASET["events"][0]["input"], source_channel="fax", source_event_id="SYN-CHANNEL-TEST",
               email="channel.test@example.example")
    with pytest.raises(Rollback):
        with lf005.transaction():
            process_and_record(lf005, raw, DATASET["events"][0]["received_at"], ContactStore(), RULES, SETTINGS)
            stored = lf005.execute("SELECT source_channel FROM ingestion_events WHERE source_event_id = %s",
                                   ("SYN-CHANNEL-TEST",)).fetchall()
            assert stored == [("unknown",)]
            raise Rollback
    assert lf005.execute("SELECT count(*) FROM ingestion_events WHERE source_event_id = 'SYN-CHANNEL-TEST'"
                         ).fetchone()[0] == 0


def test_a_reconciliation_run_is_recorded(lf005):
    checks = reconcile.reconcile(lf005, DATASET, RULES)
    run_id = reconcile.record_run(lf005, checks, database="leadflow_eu_test", source="leads_100.json",
                                  rule_version=RULES.version, run_at=datetime.now().astimezone())
    count, failed, balanced = lf005.execute(
        "SELECT check_count, failed_checks, is_balanced FROM reconciliation_runs WHERE run_id = %s",
        (run_id,)).fetchone()
    assert (count, failed, balanced) == (28, 0, True)


def test_expected_kpi_seed_is_up_to_date():
    result = subprocess.run([sys.executable, str(ROOT / "tools/expected_kpis.py"), "--check"],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
