"""P4.5 acceptance — voice transcription orchestration (whisper + media store mocked)."""

import json
import uuid
from unittest.mock import patch

import frappe

try:
    from frappe.tests import IntegrationTestCase
except ImportError:  # pre-v16 fallback
    from frappe.tests.utils import FrappeTestCase as IntegrationTestCase

from wavedesk.ai import transcription
from wavedesk.setup.install import seed_defaults
from wavedesk.tenancy import set_active_workspace


def _workspace(ai_addon: bool = True) -> str:
    ws = frappe.new_doc("WD Workspace")
    ws.workspace_name = f"Trans WS {uuid.uuid4().hex[:8]}"
    ws.plan = "Trial"
    ws.append("members", {"user": "Administrator", "role": "Owner"})
    ws.insert(ignore_permissions=True)
    sub = frappe.db.get_value("WD Subscription", {"workspace": ws.name})
    frappe.db.set_value(
        "WD Subscription", sub, "addons", json.dumps({"ai_addon": True} if ai_addon else {})
    )
    frappe.local.wd_membership_cache = {}
    set_active_workspace(ws.name)
    return ws.name


def _voice_msg(ws: str, transcript=None, is_voice: int = 1, media_key: str = "media/x/y"):
    chat = frappe.new_doc("WD Chat")
    chat.update({"workspace": ws, "chat_type": "dm", "wa_chat_id": f"wa-{uuid.uuid4().hex[:8]}"})
    chat.insert(ignore_permissions=True)
    msg = frappe.new_doc("WD Message")
    msg.update({
        "workspace": ws, "chat": chat.name, "direction": "in", "message_type": "audio",
        "wa_message_id": f"WAMID.{uuid.uuid4().hex[:10]}", "is_voice": is_voice,
        "media_key": media_key, "media_mimetype": "audio/ogg", "transcript": transcript,
    })
    msg.insert(ignore_permissions=True)
    return chat.name, msg.name


class TestTranscription(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        seed_defaults()

    def test_on_inbound_enqueues_only_for_voice_with_media(self):
        ws = _workspace()
        _, plain = _voice_msg(ws, is_voice=0)
        with patch("frappe.enqueue") as enq:
            transcription.on_inbound(ws, "C", plain, "dm")
        enq.assert_not_called()

        c, v = _voice_msg(ws)
        with patch("frappe.enqueue") as enq2:
            transcription.on_inbound(ws, c, v, "dm")
        enq2.assert_called_once()
        self.assertEqual(enq2.call_args.args[0], "wavedesk.ai.transcription.evaluate")

    def test_on_inbound_skips_voice_without_downloaded_media(self):
        ws = _workspace()
        c, v = _voice_msg(ws, media_key=None)
        with patch("frappe.enqueue") as enq:
            transcription.on_inbound(ws, c, v, "dm")
        enq.assert_not_called()

    def test_evaluate_gated_without_addon(self):
        ws = _workspace(ai_addon=False)
        c, v = _voice_msg(ws)
        with patch("wavedesk.pipeline.media_store.download_bytes") as dl:
            self.assertIsNone(transcription.evaluate(ws, c, v, "dm"))
        dl.assert_not_called()

    def test_evaluate_transcribes_and_stores(self):
        ws = _workspace()
        c, v = _voice_msg(ws)
        with patch("wavedesk.pipeline.media_store.download_bytes", return_value=b"audio"), \
                patch.object(transcription, "transcribe_bytes", return_value="hello there"), \
                patch("frappe.enqueue"):
            out = transcription.evaluate(ws, c, v, "dm")
        self.assertEqual(out, "hello there")
        self.assertEqual(frappe.db.get_value("WD Message", v, "transcript"), "hello there")

    def test_evaluate_idempotent_when_already_transcribed(self):
        ws = _workspace()
        c, v = _voice_msg(ws, transcript="already done")
        with patch("wavedesk.pipeline.media_store.download_bytes") as dl:
            self.assertIsNone(transcription.evaluate(ws, c, v, "dm"))
        dl.assert_not_called()

    def test_evaluate_reruns_text_pipelines_on_transcript(self):
        ws = _workspace()
        c, v = _voice_msg(ws)
        with patch("wavedesk.pipeline.media_store.download_bytes", return_value=b"a"), \
                patch.object(transcription, "transcribe_bytes", return_value="refund please"), \
                patch("wavedesk.ai.flagging.on_inbound") as fl, \
                patch("wavedesk.ai.agent.on_inbound_dm") as ag, \
                patch("wavedesk.ai.autoticket.on_inbound") as at:
            transcription.evaluate(ws, c, v, "dm")
        fl.assert_called_once_with(ws, c, v, "refund please")
        ag.assert_called_once()
        at.assert_called_once()

    def test_transcribe_bytes_posts_to_whisper(self):
        class _Resp:
            def raise_for_status(self):
                pass

            def json(self):
                return {"text": " hi there ", "language": "en"}

        with patch("requests.post", return_value=_Resp()) as post:
            self.assertEqual(transcription.transcribe_bytes(b"audio", "audio/ogg"), "hi there")
        self.assertTrue(post.called)

    def test_transcribe_bytes_none_on_container_error(self):
        with patch("requests.post", side_effect=OSError("connection refused")):
            self.assertIsNone(transcription.transcribe_bytes(b"audio", "audio/ogg"))
