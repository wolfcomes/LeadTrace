from __future__ import annotations

import hmac

from app.security.sessions import keyed_token_hash


def hash_csrf_token(token: str, secret: str) -> str:
    return keyed_token_hash(token, secret, purpose="csrf")


def validate_csrf_token(token: str, expected_hash: str, secret: str) -> bool:
    if not token or not expected_hash:
        return False
    return hmac.compare_digest(hash_csrf_token(token, secret), expected_hash)

