"""R8 one-time cutover ETL.

Maps the Frappe-Postgres `tabWD *` tables onto the new snake_case schema.
Deterministic uuid5 id remapping (idmap.py) lets us resolve every Frappe
Link (which stores the target row's `name`) to the new UUID primary key
without holding a giant in-memory map — and makes the whole run idempotent
(re-running upserts the same ids in place).

Entry points:
    python -m app.etl --source <frappe_pg_dsn>     # real cutover
    app.etl.run.migrate(source, session)           # programmatic / tests
"""

from app.etl.run import PgSource, migrate
from app.etl.spec import SPECS

__all__ = ["PgSource", "migrate", "SPECS"]
