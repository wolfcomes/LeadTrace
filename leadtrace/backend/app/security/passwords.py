from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from argon2.low_level import Type


class PasswordPolicyError(ValueError):
    """Raised when a proposed password does not meet the local policy."""


_PASSWORD_HASHER = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=4,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)


def validate_password(password: str) -> None:
    if len(password) < 6:
        raise PasswordPolicyError("Password must contain at least 6 characters")


def hash_password(password: str) -> str:
    validate_password(password)
    return _PASSWORD_HASHER.hash(password)


def verify_password(encoded_password: str, candidate: str) -> bool:
    try:
        return _PASSWORD_HASHER.verify(encoded_password, candidate)
    except (InvalidHashError, VerificationError):
        return False
