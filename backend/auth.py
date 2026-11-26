"""Invite-gated email-code login for the werewolf lab.

Public API surface:
  lookup(email)                 -> {'registered': bool}
  request_code(email, invite)   -> sends a 6-digit code, returns timing metadata
  verify_code(email, code, inv) -> creates the first-time user or logs in,
                                   returns (user, session_token, registered)
  current_user(handler)         -> user dict from the HttpOnly session cookie
  logout(handler)               -> deletes the session and clears the cookie

Every other API route is guarded by server.py; static assets and /api/health
remain public so the login page can load.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone

import mailer
import store

_HERE = os.path.dirname(os.path.abspath(__file__))
AUTH_CONFIG = os.environ.get("WEREWOLF_AUTH_CONFIG", os.path.join(_HERE, "config", "auth.json"))

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_RATE_LOCK = threading.Lock()
_RATE: dict[str, list[float]] = {}


class AuthError(Exception):
    def __init__(self, message, status=400, code="AUTH_ERROR"):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code


def _load_config():
    try:
        with open(AUTH_CONFIG, encoding="utf-8") as fh:
            data = json.load(fh)
    except (FileNotFoundError, ValueError):
        data = {}
    return data


CONFIG = _load_config()
COOKIE_NAME = str(CONFIG.get("cookie_name") or "werewolf_session")
SESSION_DAYS = int(CONFIG.get("session_days") or 30)
CODE_TTL = int(CONFIG.get("code_ttl_seconds") or 600)
RESEND_AFTER = int(CONFIG.get("resend_seconds") or 60)
MAX_ATTEMPTS = int(CONFIG.get("max_verify_attempts") or 6)
COOKIE_SECURE = bool(CONFIG.get("cookie_secure"))
SECRET = str(CONFIG.get("secret") or "werewolf-lab-dev-secret")
INVITES = {str(x).strip().upper() for x in (CONFIG.get("invite_codes") or []) if str(x).strip()}


def normalize_email(email):
    return str(email or "").strip().lower()


def valid_email(email):
    email = normalize_email(email)
    return bool(email and len(email) <= 200 and _EMAIL_RE.match(email))


def _iso_after(seconds):
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat(timespec="seconds")


def _expired(iso):
    try:
        return datetime.fromisoformat(iso) <= datetime.now(timezone.utc)
    except (TypeError, ValueError):
        return True


def _code_hash(email, code):
    return hmac.new(SECRET.encode("utf-8"),
                    (normalize_email(email) + ":" + str(code)).encode("utf-8"),
                    hashlib.sha256).hexdigest()


def _allow(key, limit, window):
    now = time.time()
    with _RATE_LOCK:
        bucket = [t for t in _RATE.get(key, []) if now - t < window]
        if len(bucket) >= limit:
            _RATE[key] = bucket
            return False
        bucket.append(now)
        _RATE[key] = bucket
        return True


def invite_valid(code):
    # Invite codes are reusable: the config list is the allow-list. Each user
    # still records which code they used (users.invite_code) for audit.
    code = str(code or "").strip().upper()
    return bool(code and code in INVITES)


def require_invite(code):
    if not INVITES:
        raise AuthError("当前未配置邀请码，注册已关闭", 403, "INVITE_DISABLED")
    if not invite_valid(code):
        raise AuthError("首次注册需要有效邀请码", 403, "INVITE_REQUIRED")


def _mail_code(email, code):
    ttl_minutes = max(1, CODE_TTL // 60)
    try:
        mailer.mailer().send(
            email,
            "人格狼人杀实验室 · 登录验证码",
            mailer.login_code_html(code, ttl_minutes),
            code=code,
        )
    except mailer.MailError as exc:
        store.invalidate_auth_codes(email)
        raise AuthError("验证码邮件发送失败，请稍后重试：%s" % exc, 502, "MAIL_FAILED") from exc


def lookup(email, ip=""):
    if not valid_email(email):
        raise AuthError("请输入有效的邮箱地址", 400, "EMAIL_INVALID")
    if not _allow("lookup:ip:" + (ip or "-"), 40, 60):
        raise AuthError("查询过于频繁，请稍后再试", 429, "RATE_LIMITED")
    return {"registered": bool(store.get_user_by_email(normalize_email(email)))}


def request_code(email, invite_code="", ip=""):
    email = normalize_email(email)
    if not valid_email(email):
        raise AuthError("请输入有效的邮箱地址", 400, "EMAIL_INVALID")
    registered = bool(store.get_user_by_email(email))
    if not registered:
        require_invite(invite_code)
    previous = store.latest_auth_code(email)
    if previous:
        created = previous.get("created_at") or ""
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(created)).total_seconds()
        except (TypeError, ValueError):
            age = RESEND_AFTER
        if age < RESEND_AFTER:
            raise AuthError("验证码刚发送，请 %d 秒后再试" % max(1, int(RESEND_AFTER - age)),
                            429, "COOLDOWN")
    if not _allow("send:email:" + email, 5, 3600):
        raise AuthError("该邮箱请求验证码过于频繁，请稍后再试", 429, "RATE_LIMITED")
    if not _allow("send:ip:" + (ip or "-"), 30, 3600):
        raise AuthError("当前网络请求验证码过于频繁，请稍后再试", 429, "RATE_LIMITED")
    code = "%06d" % secrets.randbelow(1_000_000)
    store.create_auth_code(email, _code_hash(email, code), _iso_after(CODE_TTL))
    _mail_code(email, code)
    body = {
        "ok": True,
        "registered": registered,
        "expires_in": CODE_TTL,
        "resend_after": RESEND_AFTER,
    }
    if mailer.mailer().dry_run and (not ip or ip in ("127.0.0.1", "::1")):
        # Dry-run from a loopback client only. The login page ignores this
        # field; automated tests and local curl use it. Real SMTP mode never
        # returns the code, and a proxied deployment does not see it either.
        body["debug_code"] = code
    return body


def verify_code(email, code, invite_code="", ip="", user_agent=""):
    email = normalize_email(email)
    code = str(code or "").strip()
    if not valid_email(email):
        raise AuthError("请输入有效的邮箱地址", 400, "EMAIL_INVALID")
    if not code:
        raise AuthError("请输入验证码", 400, "CODE_REQUIRED")
    row = store.latest_auth_code(email)
    if not row:
        raise AuthError("请先获取验证码", 400, "NO_CODE")
    if _expired(row.get("expires_at")):
        store.consume_auth_code(row["id"])
        raise AuthError("验证码已过期，请重新获取", 400, "CODE_EXPIRED")
    attempts = int(row.get("attempts") or 0)
    if attempts >= MAX_ATTEMPTS:
        store.consume_auth_code(row["id"])
        raise AuthError("验证码错误次数过多，请重新获取", 429, "TOO_MANY_ATTEMPTS")
    if not hmac.compare_digest(str(row.get("code_hash") or ""), _code_hash(email, code)):
        count = store.bump_auth_code(row["id"])
        if count >= MAX_ATTEMPTS:
            store.consume_auth_code(row["id"])
            raise AuthError("验证码错误次数过多，请重新获取", 429, "TOO_MANY_ATTEMPTS")
        raise AuthError("验证码不正确，还可尝试 %d 次" % (MAX_ATTEMPTS - count),
                        401, "CODE_MISMATCH")
    store.consume_auth_code(row["id"])
    user = store.get_user_by_email(email)
    registered = bool(user)
    if not user:
        require_invite(invite_code)
        user = store.register_user(email, str(invite_code or "").strip().upper())
        if not user:
            raise AuthError("注册失败，请稍后重试", 500, "REGISTER_FAILED")
        registered = True
    if not int(user.get("active", 1)):
        raise AuthError("该账号已被停用", 403, "ACCOUNT_DISABLED")
    store.touch_user_login(user["id"])
    store.delete_expired_sessions()
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    store.create_session(token_hash, user["id"], _iso_after(SESSION_DAYS * 86400),
                         user_agent=user_agent, ip=ip)
    return public_user(user), token, registered


def public_user(user):
    return {
        "id": user.get("id"),
        "email": user.get("email"),
        "created_at": user.get("created_at"),
        "last_login_at": user.get("last_login_at"),
    }


def _cookie_token(handler):
    raw = handler.headers.get("Cookie") or ""
    for part in raw.split(";"):
        name, _, value = part.strip().partition("=")
        if name == COOKIE_NAME and value:
            return value
    return ""


def current_user(handler):
    token = _cookie_token(handler)
    if not token:
        return None
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    session = store.get_session(token_hash)
    if not session:
        return None
    last_seen = session.get("last_seen_at") or ""
    try:
        stale = (datetime.now(timezone.utc) - datetime.fromisoformat(last_seen)).total_seconds() > 300
    except (TypeError, ValueError):
        stale = True
    if stale:
        store.touch_session(token_hash)
    return public_user({
        "id": session["user_id"],
        "email": session["email"],
        "created_at": session.get("user_created_at"),
        "last_login_at": session.get("user_last_login"),
    })


def logout(handler):
    token = _cookie_token(handler)
    if token:
        store.delete_session(hashlib.sha256(token.encode("utf-8")).hexdigest())


def session_cookie(token, handler=None):
    secure = COOKIE_SECURE
    if handler is not None:
        forwarded = (handler.headers.get("X-Forwarded-Proto") or "").lower()
        secure = secure or forwarded == "https"
    parts = [
        "%s=%s" % (COOKIE_NAME, token),
        "Path=/",
        "HttpOnly",
        "SameSite=Lax",
        "Max-Age=%d" % (SESSION_DAYS * 86400),
    ]
    if secure:
        parts.append("Secure")
    return "; ".join(parts)


def clear_cookie():
    return "%s=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0" % COOKIE_NAME


def is_public_api(path):
    return path in ("/api/health",) or path.startswith("/api/auth/")
