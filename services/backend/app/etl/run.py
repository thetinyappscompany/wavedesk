"""ETL runner. Streams Frappe rows through the specs and upserts them into the
new schema. Idempotent: deterministic ids + ON CONFLICT DO UPDATE mean a
re-run heals a partial run instead of duplicating.

The source is pluggable so the transform/remap logic is testable without a
second live database:
    * PgSource  — wraps a real Frappe-Postgres DSN (production cutover).
    * any object with rows(table_name) -> Iterable[Mapping] works (tests use a
      plain dict-backed source).
"""

import json
import uuid
from collections.abc import Iterable, Mapping
from datetime import date, datetime
from functools import lru_cache

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.etl.idmap import to_uuid
from app.etl.spec import SPECS, Spec
from app.security import hash_password

# Unusable placeholder hash for every migrated user. Frappe stores pbkdf2 hashes
# in a separate __Auth table with a format bcrypt can't verify — so passwords
# CANNOT transfer. Every user must reset via the password-reset flow after
# cutover. This value verifies against nothing (bcrypt of a random secret).
_UNUSABLE_PASSWORD = hash_password(uuid.uuid4().hex)


class PgSource:
    """Reads rows from a live Frappe-Postgres database (read-only)."""

    def __init__(self, dsn: str):
        import psycopg  # imported lazily so tests don't need a source DB
        from psycopg.rows import dict_row

        self._conn = psycopg.connect(dsn, row_factory=dict_row, autocommit=True)

    def rows(self, table: str) -> Iterable[Mapping]:
        # Quote the table name — Frappe table names contain spaces.
        with self._conn.cursor() as cur:
            cur.execute(f'select * from "{table}"')  # noqa: S608 — table from static spec
            yield from cur

    def close(self) -> None:
        self._conn.close()


def _convert(kind: str, val: object) -> object:
    if val is None:
        return None
    if kind == "B":
        return bool(val)
    if kind == "J":
        if isinstance(val, (dict, list)):
            return val
        if not val:
            return {}
        try:
            return json.loads(val)
        except (ValueError, TypeError):
            return {}
    if kind.startswith("L:"):
        return to_uuid(kind[2:], val if isinstance(val, str) else str(val))
    return val  # scalars / numbers / datetimes pass through


@lru_cache
def _nonnull_defaults(model: type) -> dict:
    """Model defaults for NOT NULL columns that have a Python-side default and no
    server default. A raw upsert doesn't run ORM defaults, so a Frappe column
    that is NULL in the source (e.g. an empty settings/suspended) would otherwise
    violate NOT NULL. We fill these in ourselves."""
    out: dict = {}
    for col in model.__table__.columns:  # type: ignore[attr-defined]
        if col.nullable or col.primary_key or col.server_default is not None:
            continue
        if col.default is None:
            continue
        arg = col.default.arg
        if callable(arg):
            try:
                out[col.name] = arg()
            except TypeError:
                out[col.name] = arg(None)
        else:
            out[col.name] = arg
    return out


def _build_values(spec: Spec, row: Mapping) -> dict:
    vals: dict = {"id": to_uuid(spec.doctype, row["name"])}

    if spec.parent_link is not None:
        dst_col, parent_dt = spec.parent_link
        vals[dst_col] = to_uuid(parent_dt, row.get("parent"))
    elif spec.has_workspace:
        vals["workspace_id"] = to_uuid("WD Workspace", row.get("workspace"))

    for dst, src, kind in spec.fields:
        vals[dst] = _convert(kind, row.get(src))

    if spec.doctype == "User":
        vals["password_hash"] = _UNUSABLE_PASSWORD

    # Carry Frappe audit timestamps onto the new tz-aware columns.
    for src_col, dst_col in (("creation", "created_at"), ("modified", "updated_at")):
        ts = row.get(src_col)
        if isinstance(ts, (datetime, date, str)) and ts:
            vals[dst_col] = ts

    # Fill NOT NULL columns the source left empty with the model's own default,
    # so a raw upsert doesn't hit a null-violation (ORM defaults don't run here).
    for col_name, dflt in _nonnull_defaults(spec.model).items():
        if vals.get(col_name) is None:
            vals[col_name] = dflt
    return vals


def _upsert(session: Session, model: type, values: dict) -> None:
    stmt = insert(model.__table__).values(**values)
    update_cols = {k: stmt.excluded[k] for k in values if k != "id"}
    stmt = stmt.on_conflict_do_update(index_elements=["id"], set_=update_cols)
    session.execute(stmt)


def migrate(
    source, session: Session, *, specs: list[Spec] = SPECS, batch: int = 500
) -> dict[str, int]:
    """Run the full ETL. Returns {doctype: rows_migrated}. Commits per table so
    a crash leaves completed tables durable and a re-run resumes cleanly."""
    counts: dict[str, int] = {}
    for spec in specs:
        n = 0
        pending = 0
        for row in source.rows(spec.table):
            _upsert(session, spec.model, _build_values(spec, row))
            n += 1
            pending += 1
            if pending >= batch:
                session.commit()
                pending = 0
        session.commit()
        counts[spec.doctype] = n
    return counts
