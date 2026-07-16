# Copyright (c) 2026, WaveDesk
# License: proprietary
"""AI Auto-Agent API (master doc §Phase 4 feature 3).

Owner/Admin configure the agent + manage knowledge; any member reads. Answer
preview is add-on gated + metered via the provider. Nothing exposes pricing config.
"""

import frappe
from frappe import _

from wavedesk.ai import agent
from wavedesk.plan.gating import FeatureNotAvailableError, has_feature
from wavedesk.tenancy import get_active_workspace, get_workspace_role

KNOWLEDGE_FIELDS = ["name", "title", "source_type", "source_ref", "embedding_status", "chunk_count"]


def _require_manager(workspace: str) -> None:
    if frappe.session.user == "Administrator":
        return
    if get_workspace_role(workspace) not in ("Owner", "Admin"):
        frappe.throw(_("Only workspace owners/admins manage the AI agent"), frappe.PermissionError)


def _config_doc(workspace: str):
    name = frappe.db.get_value("WD AI Agent Config", {"workspace": workspace})
    if name:
        return frappe.get_doc("WD AI Agent Config", name)
    doc = frappe.new_doc("WD AI Agent Config")
    doc.update({"workspace": workspace, "enabled": 0, "confidence_threshold": 0.6})
    doc.insert(ignore_permissions=True)
    return doc


def _serialize_config(doc) -> dict:
    return {
        "name": doc.name,
        "enabled": bool(doc.enabled),
        "persona_prompt": doc.persona_prompt,
        "confidence_threshold": doc.confidence_threshold,
        "handoff_team": doc.handoff_team,
        "after_hours_only": bool(doc.after_hours_only),
        "greeting": doc.greeting,
        "auto_ticket": bool(doc.auto_ticket),
    }


@frappe.whitelist()
def get_agent_config() -> dict:
    return _serialize_config(_config_doc(get_active_workspace()))


@frappe.whitelist()
def update_agent_config(
    enabled: int | bool | None = None,
    persona_prompt: str | None = None,
    confidence_threshold: float | None = None,
    handoff_team: str | None = None,
    after_hours_only: int | bool | None = None,
    greeting: str | None = None,
    auto_ticket: int | bool | None = None,
) -> dict:
    workspace = get_active_workspace()
    _require_manager(workspace)
    doc = _config_doc(workspace)
    for field, value in {
        "enabled": None if enabled is None else int(bool(int(enabled))),
        "persona_prompt": persona_prompt,
        "confidence_threshold": confidence_threshold,
        "handoff_team": handoff_team,
        "after_hours_only": None if after_hours_only is None else int(bool(int(after_hours_only))),
        "greeting": greeting,
        "auto_ticket": None if auto_ticket is None else int(bool(int(auto_ticket))),
    }.items():
        if value is not None:
            setattr(doc, field, value)
    doc.save(ignore_permissions=True)
    return _serialize_config(doc)


@frappe.whitelist()
def list_knowledge() -> list[dict]:
    workspace = get_active_workspace()
    return frappe.get_all(
        "WD Knowledge Doc", filters={"workspace": workspace},
        fields=KNOWLEDGE_FIELDS, order_by="creation desc",
    )


@frappe.whitelist()
def create_knowledge(
    title: str, content: str, source_type: str = "text", source_ref: str | None = None
) -> dict:
    workspace = get_active_workspace()
    _require_manager(workspace)
    doc = frappe.new_doc("WD Knowledge Doc")
    doc.update({
        "workspace": workspace, "title": title, "content": content,
        "source_type": source_type, "source_ref": source_ref, "embedding_status": "pending",
    })
    doc.insert(ignore_permissions=True)
    return {"name": doc.name, "embedding_status": doc.embedding_status}


@frappe.whitelist()
def delete_knowledge(doc: str) -> dict:
    workspace = get_active_workspace()
    _require_manager(workspace)
    kb = frappe.get_doc("WD Knowledge Doc", doc)
    if kb.workspace != workspace:
        frappe.throw(_("Knowledge doc is outside the active workspace"), frappe.PermissionError)
    kb.delete(ignore_permissions=True)
    return {"deleted": doc}


@frappe.whitelist()
def preview_answer(question: str) -> dict:
    """Test the agent on a question (add-on gated + metered)."""
    workspace = get_active_workspace()
    if not has_feature(workspace, "ai_addon"):
        frappe.throw(_("This feature requires the AI add-on."), FeatureNotAvailableError)
    if not (question or "").strip():
        frappe.throw(_("Question is required"))
    return agent.answer(workspace, question)
