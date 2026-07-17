"""Message templates (P3.8 parity) — name validation (Meta rules),
sequential positional {{n}} vars, render, local-vs-live submission."""

import re

from sqlalchemy import select

from app.models import MessageTemplate, WhatsAppNumber

_NAME_RE = re.compile(r"^[a-z0-9_]+$")
_VAR_RE = re.compile(r"\{\{(\d+)\}\}")


def normalize_name(name: str) -> str:
    return (name or "").strip().lower().replace(" ", "_")


def validate(template: MessageTemplate) -> None:
    template.template_name = normalize_name(template.template_name)
    if not _NAME_RE.match(template.template_name):
        raise ValueError("Template name may only contain a-z, 0-9 and underscores")
    if not (template.body or "").strip():
        raise ValueError("Template body is required")
    # Distinct positional vars must be 1..N (a body may legitimately reuse
    # {{1}} several times — dedupe before the sequential check).
    variables = sorted({int(m) for m in _VAR_RE.findall(template.body)})
    if variables != list(range(1, len(variables) + 1)):
        raise ValueError("Positional variables must be sequential: {{1}}, {{2}}, …")
    template.variable_count = len(variables)


def render(body: str, values: list) -> str:
    def sub(match):
        idx = int(match.group(1)) - 1
        return str(values[idx]) if idx < len(values) else match.group(0)

    return _VAR_RE.sub(sub, body or "")


def submit(db, template: MessageTemplate) -> dict:
    """LOCAL path: no Cloud API number connected → pending + gating note.
    LIVE path (post Meta verification) posts via the gateway."""
    cloud = db.execute(
        select(WhatsAppNumber).where(
            WhatsAppNumber.workspace_id == template.workspace_id,
            WhatsAppNumber.connection_type == "cloud_api",
            WhatsAppNumber.status == "connected",
        )
    ).scalar_one_or_none()
    template.status = "pending"
    if cloud is None:
        return {
            "status": "pending",
            "live": False,
            "note": (
                "Saved locally. Template submission to Meta requires a connected "
                "Cloud API number (Meta Business Verification)."
            ),
        }
    from app import gateway

    gateway._request(  # noqa: SLF001 — template submit shares the request core
        "POST",
        f"/cloud/{cloud.phone_number_id}/templates",
        {
            "name": template.template_name,
            "category": template.category,
            "language": template.language,
            "body": template.body,
        },
    )
    return {"status": "pending", "live": True, "note": None}
