# Copyright (c) 2026, WaveDesk
# License: proprietary

import frappe
from frappe.model.document import Document


class WDGroupMember(Document):
    pass


def on_doctype_update() -> None:
    # One membership row per (group, participant); leave/rejoin toggles left_at.
    # `group` is a reserved word, so this is raw DDL (frappe.db.add_unique does
    # not quote column names). Index introspection + syntax differ per backend.
    index_name = "unique_group_participant"
    if frappe.db.db_type == "postgres":
        exists = frappe.db.sql(
            "select 1 from pg_indexes where indexname = %s", (index_name,)
        )
        if not exists:
            frappe.db.sql_ddl(
                f'create unique index {index_name} '
                'on "tabWD Group Member" ("group", participant_id)'
            )
    else:
        exists = frappe.db.sql(
            "show index from `tabWD Group Member` where Key_name = %s", (index_name,)
        )
        if not exists:
            frappe.db.sql_ddl(
                "alter table `tabWD Group Member` "
                f"add unique index {index_name}(`group`, `participant_id`)"
            )
