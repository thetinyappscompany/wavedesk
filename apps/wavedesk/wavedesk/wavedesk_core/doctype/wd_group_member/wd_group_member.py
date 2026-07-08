# Copyright (c) 2026, WaveDesk
# License: proprietary

import frappe
from frappe.model.document import Document


class WDGroupMember(Document):
    pass


def on_doctype_update() -> None:
    # One membership row per (group, participant); leave/rejoin toggles left_at.
    # Raw DDL because `group` is a reserved word — frappe.db.add_unique does not
    # backtick-quote column names.
    existing = frappe.db.sql(
        "show index from `tabWD Group Member` where Key_name = 'unique_group_participant'"
    )
    if not existing:
        frappe.db.sql_ddl(
            "alter table `tabWD Group Member` "
            "add unique index unique_group_participant(`group`, `participant_id`)"
        )
