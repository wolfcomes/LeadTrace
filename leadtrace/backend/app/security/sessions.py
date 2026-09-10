from __future__ import annotations

import hashlib
import hmac
import secrets


def generate_session_token() -> str:
    return secrets.token_urlsafe(48)


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def keyed_token_hash(token: str, secret: str, *, purpose: str) -> str:
    key = hmac.new(secret.encode(), purpose.encode(), hashlib.sha256).digest()
    return hmac.new(key, token.encode(), hashlib.sha256).hexdigest()

