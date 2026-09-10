from __future__ import annotations

from pathlib import Path
import stat
import subprocess
import sys

import pytest

from app.cli.users import SecretFileError, read_password_file


BACKEND_ROOT = Path(__file__).resolve().parents[2]


def test_cli_never_accepts_a_plaintext_password_argument() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "app.cli.users", "create", "--help"],
        cwd=BACKEND_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert "--password-file" in completed.stdout
    assert "--password " not in completed.stdout


def test_password_file_must_not_be_group_or_world_accessible(tmp_path: Path) -> None:
    secret_file = tmp_path / "initial-password.txt"
    secret_file.write_text("Initial CLI password 2026!\n", encoding="utf-8")
    secret_file.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP)

    with pytest.raises(SecretFileError, match="permissions"):
        read_password_file(secret_file)


def test_password_file_is_read_when_owner_only(tmp_path: Path) -> None:
    secret_file = tmp_path / "initial-password.txt"
    secret_file.write_text("Initial CLI password 2026!\n", encoding="utf-8")
    secret_file.chmod(stat.S_IRUSR | stat.S_IWUSR)

    assert read_password_file(secret_file) == "Initial CLI password 2026!"
