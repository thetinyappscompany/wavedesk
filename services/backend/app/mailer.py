"""Transactional email over SMTP (Zoho by default).

Deliberately tiny: one `send()` that never raises into a request path. When SMTP
is unconfigured (`WD_SMTP_HOST` blank) `send()` returns False and callers degrade
— the password-reset admin path surfaces the link instead so the operator isn't
blocked before email is set up.

PII: recipient addresses are NEVER logged (non-negotiable #6 in spirit — logs
carry ids and outcomes, not identities).
"""

import logging
import smtplib
import ssl
from email.message import EmailMessage

from app.config import get_settings

log = logging.getLogger("wavedesk.mailer")


def is_configured() -> bool:
    return bool(get_settings().smtp_host)


def _from_address() -> str:
    s = get_settings()
    return s.smtp_from or s.smtp_user


def send(to: str, subject: str, body: str) -> bool:
    """Best-effort send. True = handed to the SMTP server, False = not sent
    (unconfigured or the server rejected it). Never raises."""
    s = get_settings()
    if not s.smtp_host:
        log.info("smtp not configured — email suppressed (%s)", subject)
        return False

    message = EmailMessage()
    message["From"] = _from_address()
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)

    try:
        if s.smtp_starttls:
            with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15) as server:
                server.starttls(context=ssl.create_default_context())
                if s.smtp_user:
                    server.login(s.smtp_user, s.smtp_password)
                server.send_message(message)
        else:  # implicit TLS (Zoho port 465)
            with smtplib.SMTP_SSL(
                s.smtp_host, s.smtp_port, timeout=15, context=ssl.create_default_context()
            ) as server:
                if s.smtp_user:
                    server.login(s.smtp_user, s.smtp_password)
                server.send_message(message)
    except Exception:  # noqa: BLE001 — email must never break the caller
        log.exception("smtp send failed (%s)", subject)
        return False
    log.info("email sent (%s)", subject)
    return True
