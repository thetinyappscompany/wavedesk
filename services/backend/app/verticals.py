"""Per-vertical onboarding starter packs (P5). Idempotent seeding of labels +
canned responses + keyword automation rules. Skips existing by title/shortcode/
rule-name; never overwrites."""

from sqlalchemy import select

from app.models import AutomationRule, CannedResponse, Label

VERTICALS = {
    "d2c": {
        "labels": ["order", "refund", "shipping"],
        "canned": [("track", "You can track your order here: {{link}}")],
        "rules": [("refund keyword", "refund", "refund")],
    },
    "agency": {
        "labels": ["lead", "client", "billing"],
        "canned": [("intro", "Thanks for reaching out! How can we help your brand?")],
        "rules": [("lead keyword", "quote", "lead")],
    },
    "community": {
        "labels": ["question", "feedback", "spam"],
        "canned": [("welcome", "Welcome to the community! 🎉")],
        "rules": [],
    },
    "support": {
        "labels": ["bug", "how-to", "urgent"],
        "canned": [("ack", "Thanks, we're on it and will update you shortly.")],
        "rules": [("urgent keyword", "urgent", "urgent")],
    },
}


def apply(db, workspace_id, vertical: str) -> dict:
    spec = VERTICALS.get(vertical)
    if not spec:
        return {"applied": False, "reason": "unknown vertical"}
    created = {"labels": 0, "canned": 0, "rules": 0}
    existing_labels = {
        r.title for r in db.execute(
            select(Label).where(Label.workspace_id == workspace_id)
        ).scalars()
    }
    for title in spec["labels"]:
        if title not in existing_labels:
            db.add(Label(workspace_id=workspace_id, title=title))
            created["labels"] += 1
    existing_canned = {
        r.shortcode for r in db.execute(
            select(CannedResponse).where(CannedResponse.workspace_id == workspace_id)
        ).scalars()
    }
    for shortcode, content in spec["canned"]:
        if shortcode not in existing_canned:
            db.add(CannedResponse(workspace_id=workspace_id, shortcode=shortcode, content=content))
            created["canned"] += 1
    existing_rules = {
        r.rule_name for r in db.execute(
            select(AutomationRule).where(AutomationRule.workspace_id == workspace_id)
        ).scalars()
    }
    for rule_name, keyword, label in spec["rules"]:
        if rule_name not in existing_rules:
            db.add(AutomationRule(
                workspace_id=workspace_id, rule_name=rule_name, trigger="message_received",
                conditions=[{"type": "keyword", "value": keyword}],
                actions=[{"type": "add_label", "value": label}],
            ))
            created["rules"] += 1
    return {"applied": True, "vertical": vertical, "created": created}
