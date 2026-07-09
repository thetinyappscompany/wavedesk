"""WhatsApp message templates (Phase 3 feature 8 — Cloud API completion).

Local template management + rendering. Submitting a template to Meta for
approval, and sending an approved template as a true Cloud API `template`
message, both require a Cloud-API number with a verified WABA + permanent token
(gated on the founder's Meta Business Verification). Until a Cloud number is
connected, submit_template marks the template pending locally and flags that the
live submission is unavailable — the rest (authoring, variable validation,
rendering to text for preview / Baileys sends) works today.
"""

import re

import frappe

_VAR_RE = re.compile(r"\{\{\s*(\d+)\s*\}\}")


def variable_count(body: str | None) -> int:
    return len({int(n) for n in _VAR_RE.findall(body or "")})


def render(body: str | None, values: list | None = None) -> str:
    """Fill positional {{1}}, {{2}} … with `values` (1-indexed)."""
    values = values or []

    def sub(match: re.Match) -> str:
        idx = int(match.group(1)) - 1
        return str(values[idx]) if 0 <= idx < len(values) else match.group(0)

    return _VAR_RE.sub(sub, body or "")


def _cloud_number(workspace: str) -> str | None:
    """A connected Cloud-API number in the workspace, if any (needed to submit
    templates to Meta)."""
    return frappe.db.get_value(
        "WD WhatsApp Number",
        {"workspace": workspace, "connection_type": "cloud_api", "status": "connected"},
        "name",
    )


def submit_template(template_doc) -> dict:
    """Submit a template to Meta for approval. Requires a connected Cloud-API
    number; otherwise the template is marked pending locally and the caller is
    told the live submission is unavailable."""
    number = _cloud_number(template_doc.workspace)
    if not number:
        template_doc.status = "pending"
        template_doc.save(ignore_permissions=True)
        return {
            "status": "pending",
            "live": False,
            "note": "No connected Cloud API number — template saved as pending. "
            "Connect a Cloud API number (Meta Business Verification required) to "
            "submit for approval.",
        }
    # Live path: hand the template spec to the gateway's Cloud API adapter.
    from wavedesk import gateway_client

    payload = {
        "name": template_doc.template_name,
        "category": template_doc.category,
        "language": template_doc.language or "en",
        "header": template_doc.header_text,
        "body": template_doc.body_text,
        "footer": template_doc.footer_text,
    }
    result = gateway_client.submit_template(number, payload)
    template_doc.status = "pending"
    template_doc.meta_template_id = result.get("id")
    template_doc.save(ignore_permissions=True)
    return {"status": "pending", "live": True, "meta_template_id": result.get("id")}
