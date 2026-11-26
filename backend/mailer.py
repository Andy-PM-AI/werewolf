"""Minimal SMTP sender for login codes.

The project already had an SMTP account for the shared notification service.
This module sends the werewolf lab's own branded code email and falls back to
a dry-run outbox when SMTP is absent or WEREWOLF_MAIL_MODE=dry_run, so the full
login flow can be tested without sending real mail.
"""
from __future__ import annotations

import json
import os
import secrets
import smtplib
import ssl
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate

_HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.environ.get("WEREWOLF_SMTP_CONFIG", os.path.join(_HERE, "config", "smtp.json"))
OUTBOX_DIR = os.environ.get("WEREWOLF_OUTBOX", os.path.join(_HERE, "data", "outbox"))


class MailError(RuntimeError):
    pass


class Mailer:
    def __init__(self, config_path=None):
        path = config_path or CONFIG_PATH
        try:
            with open(path, encoding="utf-8") as fh:
                cfg = json.load(fh)
        except (FileNotFoundError, ValueError):
            cfg = {}
        self.host = str(cfg.get("host") or "")
        self.port = int(cfg.get("port") or 465)
        self.user = str(cfg.get("user") or "")
        self.password = str(cfg.get("password") or "")
        self.sender = str(cfg.get("from") or self.user)
        self.name = str(cfg.get("from_name") or "人格狼人杀实验室")
        self.use_ssl = bool(cfg.get("use_ssl", self.port == 465))
        self.timeout = int(cfg.get("timeout_seconds") or 15)
        mode = os.environ.get("WEREWOLF_MAIL_MODE", "").strip().lower()
        self.dry_run = mode == "dry_run" or bool(cfg.get("dry_run")) or not self.host
        self.outbox = OUTBOX_DIR
        if self.dry_run:
            os.makedirs(self.outbox, exist_ok=True)

    def send(self, to, subject, html, code="", sensitive=False):
        if self.dry_run:
            return self._dry_run(to, subject, html, code, sensitive)
        message = MIMEMultipart("alternative")
        message["Subject"] = subject
        message["From"] = formataddr((self.name, self.sender)) if self.name else self.sender
        message["To"] = to
        message["Date"] = formatdate(localtime=True)
        message.attach(MIMEText(html, "html", "utf-8"))
        try:
            if self.use_ssl:
                server = smtplib.SMTP_SSL(
                    self.host, self.port, timeout=self.timeout,
                    context=ssl.create_default_context(),
                )
            else:
                server = smtplib.SMTP(self.host, self.port, timeout=self.timeout)
            try:
                if not self.use_ssl:
                    server.starttls(context=ssl.create_default_context())
                if self.user and self.password:
                    server.login(self.user, self.password)
                server.sendmail(self.sender, [to], message.as_string())
            finally:
                server.quit()
        except (smtplib.SMTPException, OSError, ssl.SSLError) as exc:
            raise MailError(str(exc)) from exc
        return True

    def _dry_run(self, to, subject, html, code, sensitive=False):
        stamp = time.strftime("%Y%m%d-%H%M%S")
        safe = "".join(ch if ch.isalnum() else "_" for ch in to)[:40]
        path = os.path.join(self.outbox, "%s-%s-%s.json" % (
            stamp, safe, secrets.token_hex(3)))
        record = {"to": to, "subject": subject, "html": html,
                  "secret" if sensitive else "code": code}
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(record, fh, ensure_ascii=False, indent=2)
        print("[mailer] DRY-RUN code=%s -> %s (saved %s)" % (code, to, path), flush=True)
        return True


_MAILER = None


def mailer():
    global _MAILER
    if _MAILER is None:
        _MAILER = Mailer()
    return _MAILER


def login_code_html(code, ttl_minutes):
    return """<!doctype html>
<html><body style="margin:0;padding:0;background:#f7f5f0;font-family:-apple-system,BlinkMacSystemFont,'PingFang SC','Microsoft YaHei',sans-serif;color:#14120f;">
  <div style="max-width:560px;margin:0 auto;padding:32px 20px;">
    <div style="background:#14120f;color:#f7f5f0;border-radius:16px 16px 0 0;padding:22px 26px;">
      <div style="font-size:11px;letter-spacing:2px;color:#c9803f;font-weight:700;">PERSONA WEREWOLF LAB</div>
      <div style="font-size:22px;font-weight:700;margin-top:6px;">人格狼人杀实验室</div>
    </div>
    <div style="background:#ffffff;border:1px solid #e6e2d8;border-top:0;border-radius:0 0 16px 16px;padding:28px 26px;">
      <p style="margin:0 0 18px;font-size:14px;line-height:1.7;color:#3f3b36;">你正在登录人格狼人杀实验室。请在页面输入下面的验证码：</p>
      <div style="font-size:34px;letter-spacing:10px;font-weight:700;color:#9a5518;background:#fbf1e6;border:1px solid #e7d2b9;border-radius:10px;padding:14px 18px;text-align:center;font-family:Menlo,Consolas,monospace;">%s</div>
      <p style="margin:18px 0 0;font-size:12px;line-height:1.7;color:#6b655d;">验证码 %d 分钟内有效，只能使用一次。如果不是你本人操作，请忽略这封邮件。</p>
      <p style="margin:22px 0 0;padding-top:14px;border-top:1px dashed #e6e2d8;font-size:11px;line-height:1.6;color:#8a847c;">这是受邀请制的内部实验，登录后可访问玩家库、模拟台和历史记录。请勿把邀请码或验证码转发给他人。</p>
    </div>
  </div>
</body></html>""" % (code, ttl_minutes)
