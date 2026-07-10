# Copyright (c) 2026, WaveDesk
# License: proprietary
"""Knowledge ingest job (master doc §Phase 4 feature 3).

RQ job: chunk + embed + upsert a WD Knowledge Doc into its workspace Qdrant
collection, then stamp embedding_status. Failures are recorded on the doc (no PII
in logs, non-negotiable #6) and never crash the queue.
"""

import frappe

from wavedesk.ai import rag


def index_knowledge_doc(doc: str) -> None:
    d = frappe.get_doc("WD Knowledge Doc", doc)
    try:
        count = rag.index_doc(d.workspace, d.name, d.content)
        frappe.db.set_value(
            "WD Knowledge Doc", doc,
            {"embedding_status": "embedded" if count else "pending", "chunk_count": count, "error": None},
            update_modified=False,
        )
    except Exception as exc:  # noqa: BLE001 - record + move on; queue must not wedge
        frappe.db.set_value(
            "WD Knowledge Doc", doc,
            {"embedding_status": "failed", "error": str(exc)[:500]},
            update_modified=False,
        )
        frappe.logger("wavedesk.ai").error({"event": "kb_index_failed", "doc": doc})
    frappe.db.commit()
