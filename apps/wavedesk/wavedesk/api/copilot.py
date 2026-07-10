# Copyright (c) 2026, WaveDesk
# License: proprietary
"""Agent Copilot API (master doc §Phase 4 feature 2).

Every endpoint is add-on gated (provider.complete enforces has_feature('ai_addon')
server-side and pauses on exhausted allowance/credits) and workspace-scoped. Any
member may use the copilot (agent-facing tool). Returns plain text for 1-click
insert/replace in the composer.
"""

import frappe
from frappe import _

from wavedesk.ai import copilot
from wavedesk.plan.gating import FeatureNotAvailableError, has_feature
from wavedesk.tenancy import get_active_workspace


def _require_ai(workspace: str) -> None:
    if not has_feature(workspace, "ai_addon"):
        frappe.throw(_("This feature requires the AI add-on."), FeatureNotAvailableError)


def _get_chat_checked(chat: str):
    doc = frappe.get_doc("WD Chat", chat)
    doc.check_permission("read")
    if doc.workspace != get_active_workspace():
        frappe.throw(_("Chat is outside the active workspace"), frappe.PermissionError)
    return doc


@frappe.whitelist()
def suggest_reply(chat: str) -> dict:
    workspace = get_active_workspace()
    _require_ai(workspace)
    _get_chat_checked(chat)
    return {"text": copilot.suggest_reply(workspace, chat)}


@frappe.whitelist()
def rewrite(text: str, mode: str = "polish") -> dict:
    workspace = get_active_workspace()
    _require_ai(workspace)
    if not (text or "").strip():
        frappe.throw(_("Nothing to rewrite"))
    return {"text": copilot.rewrite(workspace, text, mode)}


@frappe.whitelist()
def translate(text: str, target_lang: str, source_lang: str | None = None) -> dict:
    workspace = get_active_workspace()
    _require_ai(workspace)
    if not (text or "").strip():
        frappe.throw(_("Nothing to translate"))
    return {"text": copilot.translate(workspace, text, target_lang, source_lang)}


@frappe.whitelist()
def summarize(chat: str, since: str | None = None) -> dict:
    workspace = get_active_workspace()
    _require_ai(workspace)
    _get_chat_checked(chat)
    return {"text": copilot.summarize(workspace, chat, since)}
