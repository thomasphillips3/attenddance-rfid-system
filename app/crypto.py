"""Reversible encryption for secrets at rest (e.g. the Square access token).

Values are stored with a scheme prefix so they're self-describing on decrypt:
  - ``enc:`` Fernet ciphertext (preferred — requires the ``cryptography`` package)
  - ``plain:`` stored as-is (fallback when ``cryptography`` is unavailable)

The Fernet key is derived from the app's ``SECRET_KEY`` so no extra key
management is required. If ``SECRET_KEY`` changes, previously-encrypted values
can no longer be decrypted (they'll come back empty) — re-enter them in Settings.
"""

import base64
import hashlib
import logging

from flask import current_app

logger = logging.getLogger(__name__)

ENC_PREFIX = "enc:"
PLAIN_PREFIX = "plain:"


def _fernet():
    """Return a Fernet instance keyed off SECRET_KEY, or None if unavailable."""
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        return None
    secret = current_app.config.get("SECRET_KEY", "")
    if not secret:
        return None
    # Derive a 32-byte urlsafe-base64 key from the secret
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt(value: str) -> str:
    """Encrypt a plaintext string for storage. Returns a scheme-prefixed string."""
    if not value:
        return ""
    f = _fernet()
    if f is None:
        logger.warning("cryptography unavailable — storing secret without encryption")
        return PLAIN_PREFIX + value
    token = f.encrypt(value.encode("utf-8")).decode("ascii")
    return ENC_PREFIX + token


def decrypt(stored: str) -> str:
    """Decrypt a stored value. Returns plaintext, or '' if it can't be read."""
    if not stored:
        return ""
    if stored.startswith(ENC_PREFIX):
        f = _fernet()
        if f is None:
            logger.error("Cannot decrypt secret — cryptography unavailable")
            return ""
        try:
            from cryptography.fernet import InvalidToken
            return f.decrypt(stored[len(ENC_PREFIX):].encode("ascii")).decode("utf-8")
        except InvalidToken:
            logger.error("Cannot decrypt secret — invalid token (SECRET_KEY changed?)")
            return ""
        except Exception:
            logger.exception("Unexpected error decrypting secret")
            return ""
    if stored.startswith(PLAIN_PREFIX):
        return stored[len(PLAIN_PREFIX):]
    # Legacy value stored before encryption was introduced — treat as plaintext
    return stored
