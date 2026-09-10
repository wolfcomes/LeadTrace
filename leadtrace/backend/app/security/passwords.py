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
    if len(password) < 16:
        raise PasswordPolicyError("Password must contain at least 16 characters")
    character_classes = (
        any(character.islower() for character in password),
        any(character.isupper() for character in password),
        any(character.isdigit() for character in password),
        any(not character.isalnum() and not character.isspace() for character in password),
    )
    if sum(character_classes) < 3:
        raise PasswordPolicyError("Password must contain at least three character classes")


def hash_password(password: str) -> str:
    validate_password(password)
    return _PASSWORD_HASHER.hash(password)


def verify_password(encoded_password: str, candidate: str) -> bool:
    try:
        return _PASSWORD_HASHER.verify(encoded_password, candidate)
    except (InvalidHashError, VerificationError):
        return False

