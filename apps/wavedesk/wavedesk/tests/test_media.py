"""Media pipeline acceptance — consumer stores media, media API gates + presigns."""

import uuid
from unittest.mock import patch

import frappe

try:
    from frappe.tests import IntegrationTestCase
except ImportError:  # pre-v16 fallback
    from frappe.tests.utils import FrappeTestCase as IntegrationTestCase

from wavedesk.api import media as media_api
from wavedesk.api import messages as messages_api
from wavedesk.pipeline import consumer
from wavedesk.setup.install import seed_defaults
from wavedesk.tenancy import set_active_workspace


def _workspace() -> str:
    ws = frappe.new_doc("WD Workspace")
    ws.workspace_name = f"Media WS {uuid.uuid4().hex[:8]}"
    ws.plan = "Trial"
    ws.append("members", {"user": "Administrator", "role": "Owner"})
    ws.insert(ignore_permissions=True)
    frappe.local.wd_membership_cache = {}
    set_active_workspace(ws.name)
    return ws.name


def _media_event(ws: str, msg_id: str, phone: str, content: dict, media: dict) -> dict:
    return {
        "transport": "baileys",
        "type": "message.received",
        "workspace_hint": ws,
        "wa_chat_id": f"{phone}@s.whatsapp.net",
        "wa_message_id": msg_id,
        "payload": {"session_id": "s1", "message": {"message": content}, "media": media},
        "ts": "2026-07-11T12:00:00Z",
    }


class TestMediaPipeline(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        seed_defaults()

    def test_consumer_stores_image_media(self):
        ws = _workspace()
        msg_id = f"WAMID.{uuid.uuid4().hex[:10]}"
        key = f"media/{ws}/{msg_id}"
        with patch("frappe.enqueue"):
            consumer.apply_event(_media_event(
                ws, msg_id, "919990001111",
                {"imageMessage": {"caption": "look", "mimetype": "image/jpeg"}},
                {"type": "image", "key": key, "mimetype": "image/jpeg", "filename": None,
                 "size": 2048, "duration": 0, "isVoice": False},
            ))
        row = frappe.db.get_value(
            "WD Message", {"workspace": ws, "wa_message_id": msg_id},
            ["message_type", "media_key", "media_mimetype", "media_size", "is_voice", "body"],
            as_dict=True,
        )
        self.assertEqual(row.message_type, "image")
        self.assertEqual(row.media_key, key)
        self.assertEqual(row.media_mimetype, "image/jpeg")
        self.assertEqual(row.media_size, 2048)
        self.assertEqual(row.is_voice, 0)
        self.assertEqual(row.body, "look")

    def test_voice_note_sets_is_voice_and_enqueues_transcription(self):
        ws = _workspace()
        msg_id = f"WAMID.{uuid.uuid4().hex[:10]}"
        key = f"media/{ws}/{msg_id}"
        with patch("frappe.enqueue") as enq:
            consumer.apply_event(_media_event(
                ws, msg_id, "919990002222",
                {"audioMessage": {"mimetype": "audio/ogg", "seconds": 7, "ptt": True}},
                {"type": "audio", "key": key, "mimetype": "audio/ogg", "filename": None,
                 "size": 1024, "duration": 7, "isVoice": True},
            ))
        row = frappe.db.get_value(
            "WD Message", {"workspace": ws, "wa_message_id": msg_id},
            ["message_type", "is_voice", "media_duration"], as_dict=True,
        )
        self.assertEqual(row.message_type, "audio")
        self.assertEqual(row.is_voice, 1)
        self.assertEqual(row.media_duration, 7)
        calls = [c for c in enq.call_args_list
                 if c.args and c.args[0] == "wavedesk.ai.transcription.evaluate"]
        self.assertEqual(len(calls), 1)

    def test_media_url_presigns_and_scopes(self):
        ws = _workspace()
        msg_id = f"WAMID.{uuid.uuid4().hex[:10]}"
        key = f"media/{ws}/{msg_id}"
        with patch("frappe.enqueue"):
            consumer.apply_event(_media_event(
                ws, msg_id, "919990003333",
                {"imageMessage": {"mimetype": "image/png"}},
                {"type": "image", "key": key, "mimetype": "image/png", "filename": None,
                 "size": 10, "duration": 0, "isVoice": False},
            ))
        msg = frappe.db.get_value("WD Message", {"workspace": ws, "wa_message_id": msg_id})
        with patch("wavedesk.pipeline.media_store.presigned_url", return_value="https://s/u") as ps:
            out = media_api.media_url(msg)
        ps.assert_called_once_with(key)
        self.assertEqual(out["url"], "https://s/u")
        self.assertEqual(out["mimetype"], "image/png")
        self.assertTrue(out["available"])

    def test_media_url_no_key_returns_unavailable(self):
        ws = _workspace()
        chat = frappe.new_doc("WD Chat")
        chat.update({"workspace": ws, "chat_type": "dm", "wa_chat_id": f"wa-{uuid.uuid4().hex[:8]}"})
        chat.insert(ignore_permissions=True)
        msg = frappe.new_doc("WD Message")
        msg.update({"workspace": ws, "chat": chat.name, "direction": "in",
                    "message_type": "image", "wa_message_id": f"WAMID.{uuid.uuid4().hex[:8]}"})
        msg.insert(ignore_permissions=True)
        out = media_api.media_url(msg.name)
        self.assertIsNone(out["url"])
        self.assertFalse(out["available"])

    def test_messages_api_hides_raw_key(self):
        ws = _workspace()
        msg_id = f"WAMID.{uuid.uuid4().hex[:10]}"
        key = f"media/{ws}/{msg_id}"
        with patch("frappe.enqueue"):
            consumer.apply_event(_media_event(
                ws, msg_id, "919990004444",
                {"audioMessage": {"mimetype": "audio/ogg", "seconds": 3, "ptt": True}},
                {"type": "audio", "key": key, "mimetype": "audio/ogg", "filename": None,
                 "size": 10, "duration": 3, "isVoice": True},
            ))
        chat = frappe.db.get_value("WD Message", {"workspace": ws, "wa_message_id": msg_id}, "chat")
        out = messages_api.list_messages(chat)
        m = out["messages"][-1]
        self.assertTrue(m["has_media"])
        self.assertTrue(m["is_voice"])
        self.assertNotIn("media_key", m)
