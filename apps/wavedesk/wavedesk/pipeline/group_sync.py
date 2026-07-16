"""Group registry sync (Phase 2 feature 1) — applies group.* events from
wa:events into WD Group + WD Group Member.

Rules:
  - Upserts are idempotent on (workspace, wa_group_id) — every reconnect
    re-publishes the full registry and only heals drift.
  - Membership history is kept: leaving sets left_at, rejoining clears it.
  - Group members NEVER auto-create WD Contacts (contacts are born on first
    message) — we only link when a matching contact already exists.
  - PII: log group counts and ids only, never subjects/participant numbers.
"""

import frappe
from frappe.utils import now_datetime

INVITE_URL_PREFIX = "https://chat.whatsapp.com/"


def apply_group_event(event: dict) -> None:
    workspace = event.get("workspace_hint")
    if not workspace or not frappe.db.exists("WD Workspace", workspace):
        return
    wa_group_id = event.get("wa_chat_id") or ""
    if not wa_group_id.endswith("@g.us"):
        return
    payload = event.get("payload") or {}

    etype = event.get("type")
    if etype == "group.upsert":
        _upsert_group(workspace, wa_group_id, payload)
    elif etype == "group.update":
        _patch_group(workspace, wa_group_id, payload.get("update") or {})
    elif etype == "group.participants":
        _apply_participants(workspace, wa_group_id, payload)


def _get_group(workspace: str, wa_group_id: str) -> str | None:
    return frappe.db.get_value(
        "WD Group", {"workspace": workspace, "wa_group_id": wa_group_id}
    )


def _emit(workspace: str, group: str) -> None:
    from wavedesk.realtime import emit_group_updated

    emit_group_updated(workspace, group)


def _upsert_group(workspace: str, wa_group_id: str, payload: dict) -> None:
    group_data = payload.get("group") or {}
    participants = group_data.get("participants") or []
    values = {
        "subject": (group_data.get("subject") or "").strip() or wa_group_id,
        "description": (group_data.get("desc") or "").strip() or None,
        "member_count": len(participants),
        "owned_by_us": 1 if payload.get("owned_by_us") else 0,
        "last_synced_at": now_datetime(),
    }
    invite_code = payload.get("invite_code")
    if invite_code:
        values["invite_link"] = f"{INVITE_URL_PREFIX}{invite_code}"

    name = _get_group(workspace, wa_group_id)
    if name:
        number = _resolve_number(workspace, payload)
        if number and not frappe.db.get_value("WD Group", name, "number"):
            values["number"] = number
        frappe.db.set_value("WD Group", name, values, update_modified=True)
    else:
        doc = frappe.new_doc("WD Group")
        doc.update(
            {
                "workspace": workspace,
                "wa_group_id": wa_group_id,
                "number": _resolve_number(workspace, payload),
                **values,
            }
        )
        doc.insert(ignore_permissions=True)
        name = doc.name

    _sync_members(workspace, name, participants)
    _link_chat(workspace, wa_group_id, name)
    _emit(workspace, name)


def _patch_group(workspace: str, wa_group_id: str, update: dict) -> None:
    name = _get_group(workspace, wa_group_id)
    if not name:
        return  # not synced yet — the next full sync creates it
    values: dict = {"last_synced_at": now_datetime()}
    if update.get("subject"):
        values["subject"] = update["subject"]
    if "desc" in update:
        values["description"] = (update.get("desc") or "").strip() or None
    frappe.db.set_value("WD Group", name, values, update_modified=True)
    _emit(workspace, name)


def _apply_participants(workspace: str, wa_group_id: str, payload: dict) -> None:
    name = _get_group(workspace, wa_group_id)
    if not name:
        return  # unknown group — healed by the next reconnect sync
    action = payload.get("action")
    participant_ids = payload.get("participants") or []
    now = now_datetime()

    for pid in participant_ids:
        row = frappe.db.get_value(
            "WD Group Member",
            {"group": name, "participant_id": pid},
            ["name", "left_at"],
            as_dict=True,
        )
        if action == "add":
            if row:
                frappe.db.set_value(
                    "WD Group Member", row.name, {"left_at": None, "joined_at": now}
                )
            else:
                _insert_member(workspace, name, pid, "member", now)
        elif action == "remove" and row:
            frappe.db.set_value("WD Group Member", row.name, "left_at", now)
        elif action in ("promote", "demote") and row:
            frappe.db.set_value(
                "WD Group Member", row.name, "role", "admin" if action == "promote" else "member"
            )

    _refresh_member_count(name)
    _emit(workspace, name)

    from wavedesk import monitoring

    monitoring.evaluate_member_change(workspace, name, action or "", participant_ids)


def _sync_members(workspace: str, group: str, participants: list[dict]) -> None:
    existing = {
        row.participant_id: row
        for row in frappe.get_all(
            "WD Group Member",
            filters={"group": group},
            fields=["name", "participant_id", "role", "left_at"],
        )
    }
    now = now_datetime()
    seen: set[str] = set()
    for participant in participants:
        pid = participant.get("id")
        if not pid:
            continue
        seen.add(pid)
        role = "admin" if participant.get("admin") else "member"
        row = existing.get(pid)
        if row:
            updates: dict = {}
            if row.role != role:
                updates["role"] = role
            if row.left_at:
                updates["left_at"] = None  # rejoined since the last sync
            if updates:
                frappe.db.set_value("WD Group Member", row.name, updates)
        else:
            _insert_member(workspace, group, pid, role, now)

    for pid, row in existing.items():
        if pid not in seen and not row.left_at:
            frappe.db.set_value("WD Group Member", row.name, "left_at", now)


def _insert_member(workspace: str, group: str, pid: str, role: str, joined_at) -> None:
    doc = frappe.new_doc("WD Group Member")
    doc.update(
        {
            "workspace": workspace,
            "group": group,
            "participant_id": pid,
            "contact": _match_contact(workspace, pid),
            "role": role,
            "joined_at": joined_at,
        }
    )
    doc.insert(ignore_permissions=True)


def _match_contact(workspace: str, pid: str) -> str | None:
    if not pid.endswith("@s.whatsapp.net"):
        return None
    digits = pid.split("@")[0].split(":")[0]
    if not digits.isdigit():
        return None
    return frappe.db.get_value("WD Contact", {"workspace": workspace, "phone": digits})


def _refresh_member_count(group: str) -> None:
    from wavedesk.groups import active_member_count

    frappe.db.set_value(
        "WD Group", group, "member_count", active_member_count(group), update_modified=False
    )


def _resolve_number(workspace: str, payload: dict) -> str | None:
    session_ref = payload.get("session_id")
    if not session_ref:
        return None
    return frappe.db.get_value(
        "WD WhatsApp Number", {"workspace": workspace, "session_ref": session_ref}
    )


def _link_chat(workspace: str, wa_group_id: str, group: str) -> None:
    """Group chats created before the registry existed get back-linked."""
    chat = frappe.db.get_value(
        "WD Chat", {"workspace": workspace, "wa_chat_id": wa_group_id}, ["name", "group"], as_dict=True
    )
    if chat and not chat.group:
        frappe.db.set_value("WD Chat", chat.name, "group", group, update_modified=False)
