from __future__ import annotations

from argparse import Namespace

from app.cli.audit import verify


def test_audit_verify_command_reports_chain_status(
    auth_session_factory, capsys
) -> None:
    result = verify(Namespace(), session_factory=auth_session_factory)

    assert result == 0
    assert capsys.readouterr().out == "valid=true events=0 first_invalid_sequence=none\n"
