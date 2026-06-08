"""SMS sending via Twilio's REST API (no SDK dependency — uses requests).

Credentials live in Settings (Account SID + Auth Token encrypted, From number),
so the studio configures them in the UI. Gracefully no-ops when unconfigured.
"""

import logging

import requests
from flask import current_app

logger = logging.getLogger(__name__)

TWILIO_API = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"


def _creds():
    from app.crypto import decrypt
    from app.models import Setting
    sid = decrypt(Setting.get('sms_twilio_sid', ''))
    token = decrypt(Setting.get('sms_twilio_token', ''))
    from_number = Setting.get('sms_from_number', '')
    return sid, token, from_number


def is_configured() -> bool:
    from app.models import Setting
    if not Setting.get_bool('sms_enabled'):
        return False
    sid, token, from_number = _creds()
    return bool(sid and token and from_number)


def send_sms(to: str, body: str) -> bool:
    """Send a single SMS. Returns True on success. Never raises."""
    if not to:
        return False
    sid, token, from_number = _creds()
    if not (sid and token and from_number):
        return False
    try:
        resp = requests.post(
            TWILIO_API.format(sid=sid),
            data={'To': to, 'From': from_number, 'Body': body[:1500]},
            auth=(sid, token),
            timeout=15,
        )
        if resp.status_code in (200, 201):
            return True
        logger.error("Twilio send failed (%s): %s", resp.status_code, resp.text[:300])
        return False
    except Exception:
        logger.exception("Twilio request error sending to %s", to)
        return False


def test_connection():
    """Verify Twilio credentials by fetching the account. Returns (ok, message)."""
    sid, token, from_number = _creds()
    if not (sid and token):
        return False, "Account SID and Auth Token are required."
    if not from_number:
        return False, "A 'From' number is required."
    try:
        resp = requests.get(
            f"https://api.twilio.com/2010-04-01/Accounts/{sid}.json",
            auth=(sid, token), timeout=15,
        )
        if resp.status_code == 200:
            name = resp.json().get('friendly_name', sid)
            return True, f"Connected to Twilio account '{name}'."
        return False, f"Twilio rejected the credentials ({resp.status_code})."
    except Exception as e:  # noqa: BLE001
        return False, f"Connection failed: {e}"
