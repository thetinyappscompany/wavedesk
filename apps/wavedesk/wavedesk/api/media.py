# Copyright (c) 2026, WaveDesk
# License: proprietary
"""Media serving API (P4.5 / media pipeline).

The SPA never touches WhatsApp or S3 directly: it asks Frappe for a short-lived
presigned URL to a message's media, gated by the caller's permission on the
owning chat (workspace-scoped, non-negotiable #1). The bucket stays private.
"""

import frappe

from wavedesk.pipeline import media_store
from wavedesk.tenancy import get_active_workspace

MEDIA_FIELDS = [
    "chat",
    "workspace",
    "message_type",
    "media_key",
    "media_mimetype",
    "media_filename",
    "media_size",
    "media_duration",
    "is_voice",
]


def _check_chat(chat: str, workspace: str) -> None:
    """Read permission on the owning chat + active-workspace scoping."""
    doc = frappe.get_doc("WD Chat", chat)
    doc.check_permission("read")
    if doc.workspace != get_active_workspace() or workspace != doc.workspace:
        frappe.throw("Media is outside the active workspace", frappe.PermissionError)


@frappe.whitelist()
def media_url(message: str) -> dict:
    """A short-lived URL (+ metadata) for a message's media, or url=None when the
    media never downloaded / the object store is unconfigured."""
    row = frappe.db.get_value("WD Message", message, MEDIA_FIELDS, as_dict=True)
    if not row:
        frappe.throw("Unknown message", frappe.DoesNotExistError)
    if not row.chat:
        frappe.throw("Message has no chat", frappe.PermissionError)
    _check_chat(row.chat, row.workspace)

    url = media_store.presigned_url(row.media_key) if row.media_key else None
    return {
        "message": message,
        "message_type": row.message_type,
        "url": url,
        "mimetype": row.media_mimetype,
        "filename": row.media_filename,
        "size": row.media_size,
        "duration": row.media_duration,
        "is_voice": bool(row.is_voice),
        "available": bool(url),
    }
