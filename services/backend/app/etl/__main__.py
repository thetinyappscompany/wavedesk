"""CLI for the R8 cutover ETL.

    python -m app.etl --source "postgresql://user:pw@host:5432/frappe_db"

Target defaults to the app's own WD_DATABASE_URL; override with --target.
Idempotent — safe to re-run (it upserts). Run against a STAGING target first
(the runbook walks the full sequence).
"""

import argparse
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import get_settings
from app.etl.run import PgSource, migrate
from app.etl.spec import NOT_MIGRATED


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.etl", description="Frappe→new-schema cutover ETL")
    parser.add_argument("--source", required=True, help="Frappe-Postgres DSN (read-only)")
    parser.add_argument("--target", default=None, help="target DSN (default: WD_DATABASE_URL)")
    parser.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    args = parser.parse_args(argv)

    target_url = args.target or get_settings().database_url
    if not args.yes:
        print(f"About to migrate\n  FROM {args.source}\n  INTO {target_url}")
        print("Not migrated (regenerable/ephemeral):", ", ".join(NOT_MIGRATED))
        if input("Proceed? [y/N] ").strip().lower() != "y":
            print("Aborted.")
            return 1

    source = PgSource(args.source)
    engine = create_engine(target_url, pool_pre_ping=True)
    try:
        with Session(engine) as session:
            counts = migrate(source, session)
    finally:
        source.close()

    total = sum(counts.values())
    width = max(len(k) for k in counts)
    for doctype, n in counts.items():
        print(f"  {doctype:<{width}}  {n:>8,}")
    print(f"\nMigrated {total:,} rows across {len(counts)} tables.")
    print("REMINDER: every user must reset their password (hashes did not transfer).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
