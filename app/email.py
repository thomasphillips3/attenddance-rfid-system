"""Email sending for AttenDANCE — receipts, reminders, and message blasts.

Thin wrapper over smtplib so the rest of the app has one place to send mail.
All sends honor MAIL_REPLY_TO so parent replies go to the studio inbox.
"""

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from flask import current_app

logger = logging.getLogger(__name__)


def is_configured() -> bool:
    """True if an SMTP server is configured."""
    return bool(current_app.config.get("MAIL_SERVER"))


def send_email(to, subject: str, body: str) -> int:
    """Send a plaintext email to one or more recipients.

    Args:
        to: a single address (str) or an iterable of addresses.
        subject: email subject.
        body: plaintext body.

    Returns:
        Number of recipients the message was sent to.

    Raises:
        RuntimeError if SMTP is not configured.
        smtplib.SMTPException / OSError on send failure.
    """
    if isinstance(to, str):
        recipients = {to}
    else:
        recipients = {addr for addr in to if addr}
    if not recipients:
        return 0

    mail_server = current_app.config.get("MAIL_SERVER")
    if not mail_server:
        raise RuntimeError("SMTP not configured (MAIL_SERVER unset)")

    port = current_app.config.get("MAIL_PORT", 587)
    username = current_app.config.get("MAIL_USERNAME")
    password = current_app.config.get("MAIL_PASSWORD")
    reply_to = current_app.config.get("MAIL_REPLY_TO")
    sender = username or "noreply@attenddance.local"

    smtp = smtplib.SMTP(mail_server, port)
    try:
        if current_app.config.get("MAIL_USE_TLS", True):
            smtp.starttls()
        if username and password:
            smtp.login(username, password)
        for addr in recipients:
            m = MIMEMultipart()
            m["From"] = sender
            m["To"] = addr
            m["Subject"] = subject
            if reply_to:
                m["Reply-To"] = reply_to
            m.attach(MIMEText(body, "plain"))
            smtp.sendmail(sender, addr, m.as_string())
    finally:
        try:
            smtp.quit()
        except Exception:
            pass
    return len(recipients)
