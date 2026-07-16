# Copyright (c) 2026, WaveDesk
# License: proprietary

import frappe
from frappe.model.document import Document


class WDKnowledgeDoc(Document):
    def on_update(self) -> None:
        # Re-embed when content changes (or first insert). Skipped in tests, which
        # exercise wavedesk.ai.ingest.index_knowledge_doc directly (no RQ/Qdrant).
        if frappe.flags.in_test or self.flags.get("skip_index"):
            return
        if self.has_value_changed("content") or self.embedding_status == "pending":
            frappe.enqueue(
                "wavedesk.ai.ingest.index_knowledge_doc", queue="long", doc=self.name
            )

    def on_trash(self) -> None:
        from wavedesk.ai import rag

        try:
            rag.delete_doc(self.workspace, self.name)
        except Exception:  # noqa: BLE001 - vector cleanup is best-effort
            pass
