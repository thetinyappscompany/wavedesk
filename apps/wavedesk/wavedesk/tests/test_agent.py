"""P4.3 acceptance — AI Auto-Agent + RAG (embeddings/Qdrant/provider mocked)."""

import json
import os
import uuid
from unittest.mock import patch

import frappe

try:
    from frappe.tests import IntegrationTestCase
except ImportError:  # pre-v16 fallback
    from frappe.tests.utils import FrappeTestCase as IntegrationTestCase

from wavedesk.ai import agent, embeddings, ingest, provider, rag
from wavedesk.plan.gating import FeatureNotAvailableError
from wavedesk.setup.install import seed_defaults
from wavedesk.tenancy import set_active_workspace


def _workspace(ai_addon: bool = True, threshold: float = 0.6) -> str:
    ws = frappe.new_doc("WD Workspace")
    ws.workspace_name = f"Agent WS {uuid.uuid4().hex[:8]}"
    ws.plan = "Trial"
    ws.append("members", {"user": "Administrator", "role": "Owner"})
    ws.insert(ignore_permissions=True)
    sub = frappe.db.get_value("WD Subscription", {"workspace": ws.name})
    frappe.db.set_value(
        "WD Subscription", sub, "addons", json.dumps({"ai_addon": True} if ai_addon else {})
    )
    cfg = frappe.new_doc("WD AI Agent Config")
    cfg.update({"workspace": ws.name, "enabled": 1, "confidence_threshold": threshold})
    cfg.insert(ignore_permissions=True)
    frappe.local.wd_membership_cache = {}
    set_active_workspace(ws.name)
    return ws.name


class _FakeResp:
    def __init__(self, text):
        self.content = [type("B", (), {"type": "text", "text": text})()]
        self.usage = type("U", (), {"input_tokens": 800, "output_tokens": 60})()


class _FakeClient:
    def __init__(self, text):
        self._text = text
        self.messages = self

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return _FakeResp(self._text)


class TestRag(IntegrationTestCase):
    def test_chunk_text_overlaps(self):
        self.assertEqual(rag.chunk_text(""), [])
        text = "x" * 2500
        chunks = rag.chunk_text(text)
        self.assertGreaterEqual(len(chunks), 3)  # 1000-char windows over 2500
        self.assertTrue(all(len(c) <= rag.CHUNK_CHARS for c in chunks))

    def test_index_doc_embeds_and_upserts(self):
        calls = []

        def fake_qdrant(method, path, **kwargs):
            calls.append((method, path))
            return {}

        with patch.object(embeddings, "embed_texts", lambda texts, input_type="passage": [[0.1, 0.2, 0.3, 0.4]] * len(texts)), \
             patch.object(rag, "_qdrant", fake_qdrant):
            n = rag.index_doc("WS-1", "KDOC-1", "Return policy is 7 days. " * 100)
        self.assertGreater(n, 0)
        self.assertTrue(any(m == "PUT" and "points" in p for m, p in calls))

    def test_search_maps_hits(self):
        def fake_qdrant(method, path, **kwargs):
            return {"result": [{"payload": {"text": "7 day returns", "doc": "KDOC-1"}, "score": 0.82}]}

        with patch.object(embeddings, "embed_texts", lambda texts, input_type="query": [[0.1, 0.2, 0.3, 0.4]]), \
             patch.object(rag, "_qdrant", fake_qdrant):
            hits = rag.search("WS-1", "what is the return window?")
        self.assertEqual(hits[0]["text"], "7 day returns")
        self.assertAlmostEqual(hits[0]["score"], 0.82)


class TestAgentAnswer(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        seed_defaults()

    def _answer(self, ws, question, hits, model_text):
        fake = _FakeClient(model_text)
        with patch.object(rag, "search", lambda w, q, top_k=rag.TOP_K: hits), \
             patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-pool"}), \
             patch.object(provider, "_client", lambda key: fake):
            return agent.answer(ws, question), fake

    def test_confident_answer_replies_via_sonnet(self):
        ws = _workspace()
        hits = [{"text": "Our return policy is 7 days.", "doc": "KDOC-1", "score": 0.9}]
        out, fake = self._answer(ws, "how many days to return?", hits, "You can return within 7 days.")
        self.assertEqual(out["action"], "reply")
        self.assertEqual(out["text"], "You can return within 7 days.")
        self.assertEqual(fake.last_kwargs["model"], provider.MODEL_SONNET)  # customer reply → Sonnet
        self.assertIn("cache_control", json.dumps(fake.last_kwargs.get("system", "")))

    def test_low_confidence_hands_off_without_model_call(self):
        ws = _workspace(threshold=0.6)
        hits = [{"text": "something", "doc": "KDOC-1", "score": 0.2}]
        with patch.object(rag, "search", lambda w, q, top_k=rag.TOP_K: hits), patch.object(
            provider, "complete"
        ) as complete:
            out = agent.answer(ws, "unrelated question")
        self.assertEqual(out["action"], "handoff")
        self.assertEqual(out["reason"], "low_confidence")
        complete.assert_not_called()  # never spent a token

    def test_no_hits_hands_off(self):
        ws = _workspace()
        with patch.object(rag, "search", lambda w, q, top_k=rag.TOP_K: []):
            out = agent.answer(ws, "anything")
        self.assertEqual(out["action"], "handoff")

    def test_model_handoff_marker_routes_to_human(self):
        ws = _workspace()
        hits = [{"text": "policy text", "doc": "KDOC-1", "score": 0.95}]
        out, _ = self._answer(ws, "can I get a discount?", hits, agent.HANDOFF_MARK)
        self.assertEqual(out["action"], "handoff")
        self.assertEqual(out["reason"], "model_declined")


class TestIngestAndApi(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        seed_defaults()

    def test_ingest_sets_embedded_status(self):
        ws = _workspace()
        kb = frappe.new_doc("WD Knowledge Doc")
        kb.update({"workspace": ws, "title": "Returns", "source_type": "text",
                   "content": "Return policy is 7 days.", "embedding_status": "pending"})
        kb.insert(ignore_permissions=True)
        with patch.object(rag, "index_doc", lambda w, d, c: 3):
            ingest.index_knowledge_doc(kb.name)
        self.assertEqual(frappe.db.get_value("WD Knowledge Doc", kb.name, "embedding_status"), "embedded")
        self.assertEqual(frappe.db.get_value("WD Knowledge Doc", kb.name, "chunk_count"), 3)

    def test_ingest_records_failure(self):
        ws = _workspace()
        kb = frappe.new_doc("WD Knowledge Doc")
        kb.update({"workspace": ws, "title": "x", "content": "y", "embedding_status": "pending"})
        kb.insert(ignore_permissions=True)

        def boom(w, d, c):
            raise RuntimeError("embed down")

        with patch.object(rag, "index_doc", boom):
            ingest.index_knowledge_doc(kb.name)
        self.assertEqual(frappe.db.get_value("WD Knowledge Doc", kb.name, "embedding_status"), "failed")

    def test_preview_answer_gated(self):
        from wavedesk.api.agent import preview_answer

        _workspace(ai_addon=False)
        with self.assertRaises(FeatureNotAvailableError):
            preview_answer("hi")
