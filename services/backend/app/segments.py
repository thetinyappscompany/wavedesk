"""Segments (P3.7 parity) — saved contact filters evaluated LIVE, never
materialized. Conditions: has_tag / attribute / opted_out / has_email /
name_contains / phone_prefix. match_type all=intersect, any=union."""

from sqlalchemy import select

from app.models import Contact, Segment


def matching_contacts(db, segment: Segment) -> set:
    conditions = segment.filters or []
    if not conditions:
        return set()
    sets = [_resolve(db, segment.workspace_id, cond) for cond in conditions]
    result = sets[0]
    for other in sets[1:]:
        result = result & other if (segment.match_type or "all") == "all" else result | other
    return result


def _resolve(db, workspace_id, cond: dict) -> set:
    ctype = cond.get("type")
    value = cond.get("value")
    rows = db.execute(
        select(Contact).where(Contact.workspace_id == workspace_id)
    ).scalars().all()
    if ctype == "has_tag":
        needle = (value or "").strip().lower()
        return {
            c.id for c in rows
            if needle and needle in [t.strip().lower() for t in (c.tags or "").split(",")]
        }
    if ctype == "attribute":
        key = cond.get("key") or ""
        return {c.id for c in rows if (c.custom_attributes or {}).get(key) == value}
    if ctype == "opted_out":
        want = bool(value)
        return {c.id for c in rows if bool(c.opt_out) == want}
    if ctype == "has_email":
        want = bool(value)
        return {c.id for c in rows if bool(c.email) == want}
    if ctype == "name_contains":
        needle = (value or "").lower()
        return {c.id for c in rows if needle and needle in (c.full_name or "").lower()}
    if ctype == "phone_prefix":
        prefix = value or ""
        return {c.id for c in rows if prefix and c.phone.startswith(prefix)}
    return set()
