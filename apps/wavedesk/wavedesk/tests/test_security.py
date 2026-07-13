"""P5 acceptance — 2FA (TOTP) enrollment/verify/recovery + active-session mgmt."""

import time
import uuid

import frappe

try:
    from frappe.tests import IntegrationTestCase
except ImportError:  # pre-v16 fallback
    from frappe.tests.utils import FrappeTestCase as IntegrationTestCase

from wavedesk.auth import sessions, twofa

USER = "Administrator"


class TestTwoFactor(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user(USER)
        frappe.db.delete("WD User 2FA", {"user": USER})  # clean slate (commits persist)
        frappe.db.commit()

    def test_totp_is_rfc6238_stable(self):
        secret = twofa.random_secret()
        at = 1_600_000_000
        self.assertEqual(twofa._totp(secret, at), twofa._totp(secret, at + 5))  # same 30s window
        self.assertTrue(twofa.verify_totp(secret, twofa._totp(secret, at), at=at))

    def test_enroll_confirm_returns_recovery_codes(self):
        begun = twofa.begin_enroll(USER)
        self.assertIn("otpauth://totp/", begun["otpauth_uri"])
        self.assertFalse(twofa.is_enabled(USER))  # not yet
        code = twofa._totp(begun["secret"], time.time())
        out = twofa.confirm_enroll(USER, code)
        self.assertTrue(out["enabled"])
        self.assertEqual(len(out["recovery_codes"]), twofa.RECOVERY_COUNT)
        self.assertTrue(twofa.is_enabled(USER))

    def test_confirm_rejects_wrong_code(self):
        twofa.begin_enroll(USER)
        with self.assertRaises(frappe.ValidationError):
            twofa.confirm_enroll(USER, "000000")
        self.assertFalse(twofa.is_enabled(USER))

    def test_verify_accepts_totp_and_consumes_recovery(self):
        begun = twofa.begin_enroll(USER)
        out = twofa.confirm_enroll(USER, twofa._totp(begun["secret"], time.time()))
        # valid TOTP passes
        self.assertTrue(twofa.verify(USER, twofa._totp(begun["secret"], time.time())))
        # a recovery code passes once, then is spent
        recovery = out["recovery_codes"][0]
        self.assertTrue(twofa.verify(USER, recovery))
        self.assertFalse(twofa.verify(USER, recovery))

    def test_verify_true_when_disabled(self):
        self.assertTrue(twofa.verify(USER, "whatever"))  # 2FA off → nothing to check

    def test_disable_requires_valid_code(self):
        begun = twofa.begin_enroll(USER)
        twofa.confirm_enroll(USER, twofa._totp(begun["secret"], time.time()))
        with self.assertRaises(frappe.ValidationError):
            twofa.disable(USER, "000000")
        twofa.disable(USER, twofa._totp(begun["secret"], time.time()))
        self.assertFalse(twofa.is_enabled(USER))

    def test_secret_is_encrypted_at_rest(self):
        begun = twofa.begin_enroll(USER)
        stored = frappe.db.get_value("WD User 2FA", USER, "secret")
        self.assertNotEqual(stored, begun["secret"])  # ciphertext, not plaintext


class TestSessionManagement(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user(USER)

    def _mk_session(self, sid: str) -> None:
        frappe.db.sql(
            """insert into `tabSessions` (sid, user, ipaddress, lastupdate, status)
               values (%s, %s, %s, now(), 'Active')""",
            (sid, USER, "1.2.3.4"),
        )
        frappe.db.commit()

    def test_list_and_revoke_session(self):
        sid = f"sess-{uuid.uuid4().hex}"
        self._mk_session(sid)
        listed = sessions.list_sessions(USER)
        mine = [s for s in listed if s["sid_tail"] == sid[-6:]]
        self.assertEqual(len(mine), 1)
        self.assertEqual(mine[0]["ip"], "1.2.3.4")

        sessions.revoke_session(USER, sid[-6:])
        remaining = frappe.db.sql_list("select sid from `tabSessions` where sid = %s", (sid,))
        self.assertEqual(remaining, [])

    def test_revoke_other_sessions_keeps_current(self):
        keep = f"sess-{uuid.uuid4().hex}"
        drop = f"sess-{uuid.uuid4().hex}"
        self._mk_session(keep)
        self._mk_session(drop)
        from unittest.mock import patch

        with patch("wavedesk.auth.sessions._current_sid", return_value=keep):
            out = sessions.revoke_other_sessions(USER)
        self.assertGreaterEqual(out["revoked"], 1)
        self.assertTrue(frappe.db.sql_list("select sid from `tabSessions` where sid = %s", (keep,)))
        self.assertFalse(frappe.db.sql_list("select sid from `tabSessions` where sid = %s", (drop,)))
