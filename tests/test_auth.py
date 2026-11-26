"""Invite-gated email-code login tests. No real mail is sent."""
import hashlib
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "backend"))

import auth  # noqa: E402
import store  # noqa: E402


class FakeHandler:
    def __init__(self, cookie=""):
        self.headers = {
            "Cookie": cookie,
            "User-Agent": "auth-test",
            "X-Forwarded-Proto": "http",
        }

    def client_address(self):
        return ("127.0.0.1", 0)


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_db = store.DB_PATH
        self.old_invites = auth.INVITES
        self.old_secret = auth.SECRET
        self.old_resend = auth.RESEND_AFTER
        store.DB_PATH = os.path.join(self.tmp.name, "auth.db")
        store.init_db()
        auth.INVITES = {"TEST-INVITE"}
        auth.SECRET = "test-secret"
        auth.RESEND_AFTER = 0
        auth._RATE.clear()
        self.codes = []
        self.mail_patch = patch.object(auth.mailer, "mailer", return_value=SimpleNamespace(dry_run=True))
        self.mail_patch.start()
        self.code_patch = patch.object(auth, "_mail_code", side_effect=lambda email, code: self.codes.append((email, code)))
        self.code_patch.start()

    def tearDown(self):
        self.code_patch.stop()
        self.mail_patch.stop()
        store.DB_PATH = self.old_db
        auth.INVITES = self.old_invites
        auth.SECRET = self.old_secret
        auth.RESEND_AFTER = self.old_resend
        auth._RATE.clear()
        self.tmp.cleanup()

    def _user_count(self):
        with store._conn() as conn:
            return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    def test_first_registration_requires_invite_then_login_needs_only_email(self):
        self.assertFalse(auth.lookup("new@example.com")["registered"])
        with self.assertRaises(auth.AuthError) as missing:
            auth.request_code("new@example.com", "")
        self.assertEqual(missing.exception.status, 403)

        sent = auth.request_code("new@example.com", "TEST-INVITE")
        self.assertFalse(sent["registered"])
        self.assertEqual(len(self.codes), 1)
        code = self.codes[-1][1]
        user, token, registered = auth.verify_code("new@example.com", code, "TEST-INVITE")
        self.assertTrue(registered)
        self.assertEqual(user["email"], "new@example.com")
        self.assertEqual(self._user_count(), 1)
        self.assertEqual(store.get_user_by_email("new@example.com")["invite_code"], "TEST-INVITE")
        self.assertTrue(token)

        # A second login for the same email does not need the invite again.
        sent2 = auth.request_code("new@example.com", "")
        self.assertTrue(sent2["registered"])
        code2 = self.codes[-1][1]
        user2, token2, registered2 = auth.verify_code("new@example.com", code2, "")
        self.assertTrue(registered2)
        self.assertEqual(user2["email"], "new@example.com")
        self.assertTrue(token2)

    def test_wrong_code_is_rejected_and_correct_code_still_works(self):
        auth.request_code("wrong@example.com", "TEST-INVITE")
        code = self.codes[-1][1]
        bad = "000000" if code != "000000" else "111111"
        with self.assertRaises(auth.AuthError) as mismatch:
            auth.verify_code("wrong@example.com", bad, "TEST-INVITE")
        self.assertEqual(mismatch.exception.status, 401)
        user, token, _ = auth.verify_code("wrong@example.com", code, "TEST-INVITE")
        self.assertEqual(user["email"], "wrong@example.com")
        self.assertTrue(token)

    def test_invite_can_be_reused(self):
        auth.request_code("a@example.com", "TEST-INVITE")
        code = self.codes[-1][1]
        user_a, _, _ = auth.verify_code("a@example.com", code, "TEST-INVITE")
        self.assertEqual(user_a["email"], "a@example.com")

        # The same invite code registers a second, different email.
        auth.request_code("b@example.com", "TEST-INVITE")
        code_b = self.codes[-1][1]
        user_b, _, _ = auth.verify_code("b@example.com", code_b, "TEST-INVITE")
        self.assertEqual(user_b["email"], "b@example.com")
        self.assertEqual(self._user_count(), 2)

    def test_session_cookie_round_trip_and_logout(self):
        auth.request_code("session@example.com", "TEST-INVITE")
        code = self.codes[-1][1]
        user, token, _ = auth.verify_code("session@example.com", code, "TEST-INVITE")
        handler = FakeHandler("werewolf_session=" + token)
        current = auth.current_user(handler)
        self.assertIsNotNone(current)
        self.assertEqual(current["email"], user["email"])
        cookie = auth.session_cookie(token, handler)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Lax", cookie)
        auth.logout(handler)
        self.assertIsNone(auth.current_user(handler))

    def test_public_and_private_api_classification(self):
        self.assertTrue(auth.is_public_api("/api/health"))
        self.assertTrue(auth.is_public_api("/api/auth/me"))
        self.assertTrue(auth.is_public_api("/api/auth/request-code"))
        self.assertFalse(auth.is_public_api("/api/players"))
        self.assertFalse(auth.is_public_api("/api/simulations"))


if __name__ == "__main__":
    unittest.main()
