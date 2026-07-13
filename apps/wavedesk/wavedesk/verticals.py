# Copyright (c) 2026, WaveDesk
# License: proprietary
"""Per-vertical onboarding starter packs (master doc §Phase 5 feature 4).

A workspace can adopt a vertical template (D2C, agency, community, support) at
signup or later from Settings. Applying seeds a curated set of labels, canned
responses, and automation rules so a new team isn't staring at an empty inbox.

Idempotent: re-applying (or applying a second pack) skips anything that already
exists by title / shortcode / rule name — never duplicates, never overwrites the
user's own edits."""

import json

import frappe

# Each vertical: labels [(title, color)], canned [(shortcode, content)],
# automation [{rule_name, keyword, label}] (a keyword→add_label starter rule).
VERTICALS: dict[str, dict] = {
    "d2c": {
        "label": "D2C / E-commerce",
        "description": "Online store support: orders, shipping, returns.",
        "labels": [
            ("order", "#2563eb"), ("shipping", "#0891b2"),
            ("refund", "#dc2626"), ("vip", "#f59e0b"),
        ],
        "canned": [
            ("thanks", "Thanks for shopping with us! How can I help? 🛍️"),
            ("track", "You can track your order here: {{tracking_link}}"),
            ("refund", "We've initiated your refund — it reflects in 5–7 business days."),
        ],
        "automation": [
            {"rule_name": "Tag refund requests", "keyword": "refund", "label": "refund"},
            {"rule_name": "Tag shipping queries", "keyword": "shipping", "label": "shipping"},
        ],
    },
    "agency": {
        "label": "Agency / Services",
        "description": "Client comms: leads, projects, invoices.",
        "labels": [
            ("lead", "#16a34a"), ("project", "#2563eb"),
            ("invoice", "#f59e0b"), ("urgent", "#dc2626"),
        ],
        "canned": [
            ("intro", "Hi! Thanks for reaching out to {{workspace}}. What can we help with?"),
            ("proposal", "I'll share a proposal shortly. Anything specific to include?"),
            ("invoice", "Here's your invoice: {{invoice_link}}. Let me know if you have questions."),
        ],
        "automation": [
            {"rule_name": "Tag new leads", "keyword": "quote", "label": "lead"},
            {"rule_name": "Flag urgent", "keyword": "urgent", "label": "urgent"},
        ],
    },
    "community": {
        "label": "Community / Groups",
        "description": "Group management: questions, announcements, moderation.",
        "labels": [
            ("question", "#2563eb"), ("announcement", "#7c3aed"),
            ("feedback", "#16a34a"), ("moderation", "#dc2626"),
        ],
        "canned": [
            ("welcome", "Welcome to the community! 👋 Please read the pinned guidelines."),
            ("rules", "A quick reminder of our community guidelines: be kind, stay on topic."),
            ("answered", "Marked as answered ✅ — thanks everyone!"),
        ],
        "automation": [
            {"rule_name": "Tag questions", "keyword": "?", "label": "question"},
            {"rule_name": "Flag for moderation", "keyword": "spam", "label": "moderation"},
        ],
    },
    "support": {
        "label": "Customer Support",
        "description": "Helpdesk: tickets, escalations, resolutions.",
        "labels": [
            ("bug", "#dc2626"), ("billing", "#f59e0b"),
            ("how-to", "#2563eb"), ("escalation", "#7c3aed"),
        ],
        "canned": [
            ("greet", "Hi! I'm here to help. Could you describe the issue you're facing?"),
            ("investigating", "Thanks — I'm looking into this and will update you shortly."),
            ("resolved", "Glad that's sorted! I'll close this out. Reach out anytime. 🙏"),
        ],
        "automation": [
            {"rule_name": "Tag bug reports", "keyword": "bug", "label": "bug"},
            {"rule_name": "Tag billing issues", "keyword": "billing", "label": "billing"},
        ],
    },
}


def list_verticals() -> list[dict]:
    return [
        {
            "key": key,
            "label": v["label"],
            "description": v["description"],
            "labels": [t for t, _ in v["labels"]],
            "canned": [s for s, _ in v["canned"]],
            "automation": [r["rule_name"] for r in v["automation"]],
        }
        for key, v in VERTICALS.items()
    ]


def apply(workspace: str, vertical: str) -> dict:
    """Seed the vertical's labels/canned/automation into a workspace (idempotent)."""
    v = VERTICALS.get(vertical)
    if not v:
        frappe.throw(f"Unknown vertical: {vertical}", frappe.ValidationError)
    added = {"labels": 0, "canned": 0, "automation": 0}

    for title, color in v["labels"]:
        if not frappe.db.exists("WD Label", {"workspace": workspace, "title": title}):
            frappe.get_doc({
                "doctype": "WD Label", "workspace": workspace, "title": title, "color": color,
            }).insert(ignore_permissions=True)
            added["labels"] += 1

    for shortcode, content in v["canned"]:
        if not frappe.db.exists(
            "WD Canned Response", {"workspace": workspace, "shortcode": shortcode}
        ):
            frappe.get_doc({
                "doctype": "WD Canned Response", "workspace": workspace,
                "shortcode": shortcode, "content": content,
            }).insert(ignore_permissions=True)
            added["canned"] += 1

    for rule in v["automation"]:
        if not frappe.db.exists(
            "WD Automation Rule", {"workspace": workspace, "rule_name": rule["rule_name"]}
        ):
            frappe.get_doc({
                "doctype": "WD Automation Rule", "workspace": workspace,
                "rule_name": rule["rule_name"], "enabled": 1,
                "trigger_event": "message_received",
                "conditions": json.dumps([{"type": "keyword", "value": rule["keyword"]}]),
                "actions": json.dumps([{"type": "add_label", "label": rule["label"]}]),
            }).insert(ignore_permissions=True)
            added["automation"] += 1

    frappe.db.commit()
    return {"vertical": vertical, "added": added}
