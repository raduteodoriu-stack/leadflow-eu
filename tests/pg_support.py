"""Shared set-up for the PostgreSQL integration tests (LF-008 onwards).

The tests WIPE the database they use, so they only run against leadflow_eu_test,
given in LEADFLOW_TEST_DSN, and are skipped when psycopg or the server is missing.
"""
import json
import os
import pathlib

import pytest

psycopg = pytest.importorskip("psycopg", reason="psycopg not installed (pip install -r requirements.txt)")

from leadflow import load_rules, postgres  # noqa: E402
from leadflow import batch  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
RULES = load_rules()
DATASET = json.loads((ROOT / "data/synthetic/leads_100.json").read_text(encoding="utf-8"))
EXPECTED = json.loads((ROOT / "data/synthetic/expected_outcomes.json").read_text(encoding="utf-8"))
SETTINGS = batch.settings_from(DATASET)
SEED_FROM = "2026-10-01T00:00:00+02:00"


def connect():
    dsn = os.environ.get("LEADFLOW_TEST_DSN")
    if not dsn:
        pytest.skip("LEADFLOW_TEST_DSN not set")
    try:
        conn = psycopg.connect(dsn, autocommit=True)
    except psycopg.OperationalError as error:
        pytest.skip(f"cannot reach PostgreSQL: {error}")
    name = conn.execute("SELECT current_database()").fetchone()[0]
    if name != "leadflow_eu_test":
        conn.close()
        pytest.fail(f"refusing to wipe database {name!r}: point LEADFLOW_TEST_DSN at leadflow_eu_test")
    return conn


def rebuild(conn, seed=True):
    """Empty the test database, apply every migration in number order, seed LF-005 reference data."""
    conn.execute("DROP SCHEMA IF EXISTS public CASCADE")
    conn.execute("CREATE SCHEMA public")
    for migration in sorted((ROOT / "SQL").glob("[0-9][0-9][0-9]_*.sql")):
        conn.execute(migration.read_text(encoding="utf-8"))
    if seed:
        postgres.seed_reference_data(conn, RULES, SETTINGS, SEED_FROM)


def snapshot(conn):
    """Every row of every table, as comparable text, to prove two runs wrote the same thing."""
    tables = [t for (t,) in conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' "
        "AND table_type = 'BASE TABLE' ORDER BY table_name").fetchall()]
    return {t: sorted(r for (r,) in conn.execute(f"SELECT to_jsonb(x)::text FROM {t} x").fetchall())
            for t in tables}
