import json

from leadtrace.ops.ai_prefill.cli import main


def test_cli_smoke_uses_offline_json_commands(capsys) -> None:
    assert main(["doctor"]) == 0
    doctor = json.loads(capsys.readouterr().out)
    assert doctor["offline"] is True
    assert doctor["database"] == "not checked"

    assert main(["contract", "export"]) == 0
    contract = json.loads(capsys.readouterr().out)
    assert contract["title"] == "CandidateEnvelope"
