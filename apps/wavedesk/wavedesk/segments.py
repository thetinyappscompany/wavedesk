"""Segments — dynamic contact filters (Phase 3 feature 7).

A segment is a saved set of conditions over a workspace's contacts. It's
evaluated live (never materialized) so it always reflects the current data, and
is consumed by broadcasts (audience_type='segment') and automation rules
(the in_segment condition).

Supported conditions (each {type, key?, value}):
  has_tag         value in the contact's comma-separated tags
  attribute       custom_attributes[key] == value
  opted_out       opt_out == value (bool)
  has_email       email present == value (bool)
  name_contains   full_name contains value
  phone_prefix    phone starts with value (digits)
  last_seen_days  had an inbound message within the last value days
  in_group        member of WD Group `value`
match_type 'all' intersects the conditions; 'any' unions them.
"""

import json
import re

import frappe
from frappe.utils import add_to_date, cint, now_datetime


def _parse(value) -> list[dict]:
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value or "[]")
    except (TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []


def matching_contacts(segment_doc) -> list[str]:
    """Contact names matching the segment, evaluated live."""
    workspace = segment_doc.workspace
    conditions = _parse(segment_doc.filters)
    if not conditions:
        return frappe.get_all("WD Contact", filters={"workspace": workspace}, pluck="name")

    result: set[str] | None = None
    union = (segment_doc.match_type or "all") == "any"
    for cond in conditions:
        matched = _contacts_for(workspace, cond)
        if result is None:
            result = matched
        elif union:
            result |= matched
        else:
            result &= matched
    return sorted(result or set())


def count(segment_doc) -> int:
    return len(matching_contacts(segment_doc))


def _contacts_for(workspace: str, cond: dict) -> set[str]:
    ctype = cond.get("type")
    value = cond.get("value")

    if ctype == "opted_out":
        return _names(workspace, {"opt_out": 1 if _as_bool(value) else 0})
    if ctype == "has_email":
        op = ("is", "set") if _as_bool(value) else ("in", (None, ""))
        return _names(workspace, {"email": op})
    if ctype == "name_contains":
        return _names(workspace, {"full_name": ("like", f"%{value or ''}%")})
    if ctype == "phone_prefix":
        return _names(workspace, {"phone": ("like", f"{re.sub(r'[^0-9+]', '', str(value or ''))}%")})
    if ctype == "has_tag":
        return _names(workspace, {"tags": ("like", f"%{value or ''}%")})
    if ctype == "attribute":
        return _by_attribute(workspace, cond.get("key"), value)
    if ctype == "last_seen_days":
        return _seen_within(workspace, cint(value) or 30)
    if ctype == "in_group":
        return _in_group(workspace, value)
    return set()


def _names(workspace: str, extra: dict) -> set[str]:
    return set(
        frappe.get_all(
            "WD Contact", filters={"workspace": workspace, **extra}, pluck="name",
            ignore_permissions=True,
        )
    )


def _by_attribute(workspace: str, key, value) -> set[str]:
    if not key:
        return set()
    rows = frappe.get_all(
        "WD Contact", filters={"workspace": workspace}, fields=["name", "custom_attributes"],
        ignore_permissions=True,
    )
    out = set()
    for row in rows:
        attrs = row.custom_attributes
        if isinstance(attrs, str):
            try:
                attrs = json.loads(attrs or "{}")
            except (TypeError, ValueError):
                attrs = {}
        if isinstance(attrs, dict) and str(attrs.get(key, "")) == str(value):
            out.add(row.name)
    return out


def _seen_within(workspace: str, days: int) -> set[str]:
    since = add_to_date(now_datetime(), days=-days)
    m = frappe.qb.DocType("WD Message")
    c = frappe.qb.DocType("WD Chat")
    rows = (
        frappe.qb.from_(m)
        .join(c)
        .on(m.chat == c.name)
        .select(c.contact)
        .distinct()
        .where(
            (c.workspace == workspace)
            & (m.direction == "in")
            & c.contact.isnotnull()
            & (m.creation >= since)
        )
    ).run(pluck=True)
    return {r for r in rows if r}


def _in_group(workspace: str, group) -> set[str]:
    if not group:
        return set()
    rows = frappe.get_all(
        "WD Group Member",
        filters={"group": group, "left_at": ("is", "not set"), "contact": ("is", "set")},
        pluck="contact",
        ignore_permissions=True,
    )
    # scope to workspace contacts
    if not rows:
        return set()
    valid = set(
        frappe.get_all(
            "WD Contact", filters={"workspace": workspace, "name": ("in", rows)}, pluck="name",
            ignore_permissions=True,
        )
    )
    return valid


def _as_bool(value) -> bool:
    return value in (True, 1, "1", "true", "True", "yes")
