from __future__ import annotations

import pytest

from app.security.passwords import (
    PasswordPolicyError,
    hash_password,
    validate_password,
    verify_password,
)


def test_password_is_stored_as_argon2id_and_never_as_plaintext() -> None:
    plaintext = "A strong reviewer passphrase 2026!"

    encoded = hash_password(plaintext)

    assert encoded.startswith("$argon2id$")
    assert plaintext not in encoded
    assert verify_password(encoded, plaintext) is True
    assert verify_password(encoded, "incorrect password") is False


@pytest.mark.parametrize(
    "password",
    [
        "short",
        "onlylowercaseletters",
        "ONLYUPPERCASELETTERS",
        "1234567890123456",
    ],
)
def test_password_policy_rejects_weak_initial_passwords(password: str) -> None:
    with pytest.raises(PasswordPolicyError):
        validate_password(password)


def test_password_policy_accepts_long_mixed_passphrase() -> None:
    validate_password("Reviewer passphrase 2026!")

