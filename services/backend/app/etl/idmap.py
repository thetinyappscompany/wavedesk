"""Deterministic id remapping: Frappe `name` (varchar PK) → new UUID PK.

A Frappe Link column stores the *name* of the row it points at (e.g. a chat's
`workspace` column holds "WS-90359"). We turn every name into a UUID with
uuid5 over a fixed namespace + the doctype, so:

  * the same name always maps to the same UUID (idempotent re-runs), and
  * a Link can be resolved to its target UUID from the name alone — no lookup
    table, no ordering dependency between the referrer and the referent.

The doctype is part of the key so that two different doctypes that happen to
share a name (unlikely, but possible for Frappe hash-names) never collide.
"""

import uuid

# Fixed, arbitrary namespace for the WaveDesk cutover. NEVER change this after
# a production run — every id in the new database is derived from it.
NAMESPACE = uuid.UUID("6f9b8e2a-4c1d-5e7a-9b3f-2a1c0d4e6f80")


def to_uuid(doctype: str, name: str | None) -> uuid.UUID | None:
    """Map a Frappe row/link name to its deterministic UUID.

    Empty / NULL links map to None (Frappe stores an unset Link as "" or NULL).
    """
    if name is None or name == "":
        return None
    return uuid.uuid5(NAMESPACE, f"{doctype}:{name}")
