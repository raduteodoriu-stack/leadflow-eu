"""LF-008/LF-009: reconcile a processed batch against the database and write a report.

Usage (from the repo root, .venv active):

    python tools/reconcile.py --dsn "dbname=leadflow_eu_test user=postgres"
    python tools/reconcile.py --dsn "..." --run     # rebuild leadflow_eu_test, process LF-005, then reconcile

--run wipes the database, so it is only allowed on leadflow_eu_test. The report is
printed and saved to docs/evidence/reconciliation_<date>_<time>.md. Exit code 0 only
when every check balances.
"""
import argparse
import json
import pathlib
import sys
from datetime import datetime

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import psycopg  # noqa: E402

from leadflow import ContactStore, load_rules, postgres  # noqa: E402
from leadflow import batch, reconcile  # noqa: E402

SEED_FROM = "2026-10-01T00:00:00+02:00"


def rebuild(conn, rules, settings):
    if conn.execute("SELECT current_database()").fetchone()[0] != "leadflow_eu_test":
        sys.exit("--run wipes the database: connect to leadflow_eu_test")
    conn.execute("DROP SCHEMA IF EXISTS public CASCADE")
    conn.execute("CREATE SCHEMA public")
    for migration in sorted((ROOT / "SQL").glob("[0-9][0-9][0-9]_*.sql")):
        conn.execute(migration.read_text(encoding="utf-8"))
    postgres.seed_reference_data(conn, rules, settings, SEED_FROM)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dsn", required=True)
    parser.add_argument("--source", default=str(ROOT / "data/synthetic/leads_100.json"))
    parser.add_argument("--run", action="store_true", help="rebuild leadflow_eu_test and process the batch first")
    args = parser.parse_args()

    rules = load_rules()
    dataset = json.loads(pathlib.Path(args.source).read_text(encoding="utf-8"))
    settings = batch.settings_from(dataset)
    with psycopg.connect(args.dsn, autocommit=True) as conn:
        if args.run:
            rebuild(conn, rules, settings)
            batch.run(conn, dataset, ContactStore(), rules, settings,
                      until=dataset["metadata"].get("sla_cutoff"))  # SLA statuses as at the cut-off
        database = conn.execute("SELECT current_database()").fetchone()[0]
        checks = reconcile.reconcile(conn, dataset, rules)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    context = (f"Database `{database}` · source `{pathlib.Path(args.source).name}` · rules `{rules.version}` · "
               f"run {stamp.replace('_', ' ')}")
    text = reconcile.report_markdown(checks, context=context)
    out = ROOT / "docs/evidence" / f"reconciliation_{stamp}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(text)
    print(f"Saved: {out.relative_to(ROOT)}")
    return 0 if all(c["difference"] == 0 for c in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
