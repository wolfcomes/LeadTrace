import json
from pathlib import Path

import pytest

from app.ai_prefill.assistance_evaluation import SECTIONS
from app.ai_prefill.assistance_validation import validate_candidate
from leadtrace.ops.ai_prefill.cli import main
from .test_workspace_db_export import _apply


@pytest.fixture
def workspace_cli(preview_ai_context, preview_settings, tmp_path):
    parent, application_id = _apply(preview_ai_context, preview_settings)
    profile = tmp_path / 'runtime.json'
    data = preview_settings.model_dump(mode='json')
    data['session_secret'] = preview_settings.session_secret.get_secret_value()
    profile.write_text(json.dumps(data))
    profile.chmod(0o600)
    candidate = tmp_path / 'parent.json'
    candidate.write_text(parent.model_dump_json())
    report = tmp_path / 'report.json'
    report.write_text(validate_candidate(parent, report_id='report:cli').model_dump_json())
    coverage = tmp_path / 'coverage.json'
    coverage.write_text(json.dumps({section: 'partial' for section in SECTIONS}))
    evaluation = tmp_path / 'evaluation.json'
    child = tmp_path / 'child.json'
    artifacts = tmp_path / 'selected-artifacts'
    common = ['--profile', str(profile), '--application-id', str(application_id),
              '--expected-workspace-version', '2', '--reviewer', 'cli-reviewer',
              '--artifact-root', str(artifacts)]
    record = ['evaluation', 'record', str(candidate), *common, '--report', str(report),
              '--evaluation-id', 'evaluation:cli', '--decision', 'needs_revision',
              '--coverage', str(coverage), '--output', str(evaluation)]
    export = ['candidate', 'export-workspace', str(candidate), *common,
              '--candidate-id', 'candidate:cli-child', '--evaluation', str(evaluation),
              '--output', str(child)]
    return record, export, evaluation, child, artifacts, parent


@pytest.mark.parametrize('operation', ['record', 'export'])
def test_cli_recovers_existing_artifact_after_output_loss_without_changing_timestamp(workspace_cli, capsys, operation):
    record, export, evaluation, child, artifacts, parent = workspace_cli
    assert main(record) == 0
    capsys.readouterr()
    if operation == 'export':
        assert main(export) == 0
        capsys.readouterr()
    command, output = (record, evaluation) if operation == 'record' else (export, child)
    original = output.read_bytes()
    output.unlink()  # Already-persisted artifacts survive an interrupted/lost output publication.
    assert main(command) == 0
    capsys.readouterr()
    assert output.read_bytes() == original
    assert (artifacts / 'experiments' / parent.experiment_id / 'candidates' / parent.candidate_id / 'candidate.json').is_file()
    assert (artifacts / 'experiments' / parent.experiment_id / 'validations' / 'report:cli.json').is_file()
    output.unlink()
    changed = list(command)
    changed[changed.index('--reviewer') + 1] = 'different-reviewer'
    assert main(changed) == 5
    capsys.readouterr()
    assert not output.exists()


def test_export_cli_rejects_forged_applied_workspace_version(workspace_cli, capsys):
    record, export, evaluation, child, artifacts, parent = workspace_cli
    assert main(record) == 0
    capsys.readouterr()
    value = json.loads(evaluation.read_text())
    value['applied_workspace_version'] = 3
    evaluation.write_text(json.dumps(value))
    assert main(export) == 2
    response = json.loads(capsys.readouterr().out)
    assert response['code'] == 'EVALUATION_IDENTITY_MISMATCH'
    assert not child.exists()


@pytest.mark.parametrize('operation', ['record', 'export'])
def test_cli_retries_same_id_after_output_publication_error(workspace_cli, capsys, monkeypatch, operation):
    from leadtrace.ops.ai_prefill import cli
    record, export, evaluation, child, artifacts, parent = workspace_cli
    if operation == 'export':
        assert main(record) == 0
        capsys.readouterr()
    command, output = (record, evaluation) if operation == 'record' else (export, child)
    original = cli._publish_output
    def interrupted(*args):
        raise OSError('simulated disk publication failure')
    monkeypatch.setattr(cli, '_publish_output', interrupted)
    assert main(command) == 5
    capsys.readouterr()
    assert not output.exists()
    monkeypatch.setattr(cli, '_publish_output', original)
    assert main(command) == 0
    capsys.readouterr()
    assert output.is_file()
