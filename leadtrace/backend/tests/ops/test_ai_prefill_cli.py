from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from app.ai_prefill.assistance_contracts import (
    CandidateEnvelope,
    CandidateRecipe,
    ProducerProvenance,
    SourceIdentity,
)
from app.ai_prefill.contracts import AiPrefillPayload
from leadtrace.ops.ai_prefill.cli import main


def candidate(*, activity_without_evidence: bool = False) -> CandidateEnvelope:
    payload = AiPrefillPayload.model_validate(
        {
            "schema_version": 1,
            "compounds": [
                {"ref": "c1", "compound_label": "1", "structure": {"smiles": "CCO"}}
            ],
            "activities": (
                [
                    {
                        "compound_ref": "c1",
                        "assay_name": "binding",
                        "metric": "IC50",
                        "operator": "=",
                        "value": "1",
                    }
                ]
                if activity_without_evidence
                else []
            ),
        }
    )
    return CandidateEnvelope(
        envelope_version=1,
        candidate_id="candidate:v1",
        experiment_id="experiment:test",
        source=SourceIdentity(
            paper_key="paper-1", source_sha256="a" * 64, byte_size=100, page_count=4
        ),
        producer=ProducerProvenance(
            kind="local",
            engine="test",
            engine_version="1",
            generated_at=datetime(2026, 1, 1, tzinfo=UTC),
        ),
        recipe=CandidateRecipe(guide_version="guide-v1"),
        payload=payload,
    )


def write_candidate(path: Path, value: CandidateEnvelope) -> None:
    path.write_text(value.model_dump_json(), encoding="utf-8")


def test_doctor_emits_offline_machine_readable_report(capsys) -> None:
    assert main(["doctor"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["ok"] is True
    assert output["offline"] is True
    assert output["database"] == "not checked"
    assert {"candidate export-workspace", "evaluation record"} <= set(output["commands"])


def test_contract_export_writes_schema_without_database_access(tmp_path: Path, capsys) -> None:
    output_path = tmp_path / "candidate-envelope.json"

    assert main(["contract", "export", "--output", str(output_path)]) == 0

    assert output_path.exists()
    schema = json.loads(output_path.read_text(encoding="utf-8"))
    assert schema["title"] == "CandidateEnvelope"
    assert json.loads(capsys.readouterr().out)["title"] == "CandidateEnvelope"


def test_candidate_validate_keeps_needs_review_as_success(tmp_path: Path, capsys) -> None:
    path = tmp_path / "candidate.json"
    write_candidate(path, candidate(activity_without_evidence=True))

    assert main(["candidate", "validate", str(path)]) == 0

    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "needs_review"
    assert any(issue["code"] == "ACTIVITY_WITHOUT_EVIDENCE" for issue in report["issues"])


def test_candidate_validate_returns_contract_error_code_for_invalid_candidate(
    tmp_path: Path, capsys
) -> None:
    path = tmp_path / "candidate.json"
    write_candidate(
        path,
        candidate().model_copy(
            update={
                "payload": AiPrefillPayload.model_validate(
                    {
                        "schema_version": 1,
                        "compounds": [
                            {
                                "ref": "c1",
                                "compound_label": "1",
                                "structure": {"smiles": "not-a-smiles"},
                            }
                        ],
                    }
                )
            }
        ),
    )

    assert main(["candidate", "validate", str(path)]) == 4

    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "invalid"


def test_candidate_export_writes_human_assisted_child(tmp_path: Path, capsys) -> None:
    parent = tmp_path / "parent.json"
    payload = tmp_path / "payload.json"
    output = tmp_path / "child.json"
    write_candidate(parent, candidate())
    payload.write_text(
        json.dumps({"schema_version": 1, "bibliography": {"title": "edited"}}),
        encoding="utf-8",
    )

    assert main(
        [
            "candidate",
            "export",
            str(parent),
            "--payload",
            str(payload),
            "--output",
            str(output),
            "--candidate-id",
            "candidate:v2",
            "--evaluation-id",
            "evaluation:1",
            "--reviewer",
            "reviewer@example.test",
        ]
    ) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["parent_candidate_id"] == "candidate:v1"
    assert json.loads(output.read_text(encoding="utf-8"))["producer"]["kind"] == "human-assisted"


def test_preview_create_requires_explicit_provisioning_profile(tmp_path, capsys):
    assert main(['preview', 'create', '--registry-root', str(tmp_path),
                 '--instance-id', '22222222-2222-4222-8222-222222222222']) == 2
    assert json.loads(capsys.readouterr().out)['code'] == 'PREVIEW_CREATE_OPTIONS_REQUIRED'


def test_preview_lifecycle_requires_explicit_profile(capsys):
    assert main(['preview', 'start']) == 2
    assert json.loads(capsys.readouterr().out)['code'] == 'PREVIEW_PROFILE_REQUIRED'


def test_preview_create_rejects_public_credentials_file_without_disclosing_secret(tmp_path, capsys):
    credentials = tmp_path / 'provisioning.json'
    credentials.write_text(json.dumps({'database_url': 'postgresql://admin:VERY-SECRET@localhost/demo_preview_admin'}))
    credentials.chmod(0o644)
    assert main(['preview', 'create', '--registry-root', str(tmp_path / 'instances'),
                 '--instance-id', '22222222-2222-4222-8222-222222222222',
                 '--provisioning-profile', str(credentials), '--manifest', str(tmp_path / 'manifest.json'),
                 '--source-root', str(tmp_path / 'sources'), '--origin', 'http://127.0.0.1:18080',
                 '--commit', 'abc123', '--lockfile-sha256', 'c' * 64]) == 5
    output = capsys.readouterr()
    assert 'VERY-SECRET' not in output.out + output.err
    assert json.loads(output.out)['code'] == 'PREVIEW_OPERATION_FAILED'


def test_workspace_export_requires_profile_and_bound_evaluation(tmp_path, capsys):
    path=tmp_path/'parent.json'
    write_candidate(path,candidate())
    assert main(['candidate','export-workspace',str(path)]) == 2
    assert json.loads(capsys.readouterr().out)['code']=='WORKSPACE_EXPORT_OPTIONS_REQUIRED'


def test_native_cleanup_requires_profile_and_exact_confirmation(capsys,tmp_path):
    assert main(['preview','destroy','--profile',str(tmp_path/'runtime.json')]) == 2
    assert json.loads(capsys.readouterr().out)['code']=='NATIVE_DESTROY_OPTIONS_REQUIRED'


def test_evaluation_summary_never_invents_review_coverage(tmp_path,capsys):
    path=tmp_path/'feedback.json'
    path.write_text(json.dumps({'evaluation_id':'review:1','experiment_id':'experiment:test','candidate_id':'candidate:v1',
        'reviewer':'operator','created_at':'2026-09-20T00:00:00Z','decision':'accepted'}))
    assert main(['evaluation','summary',str(path)])==2
    assert json.loads(capsys.readouterr().out)['code']=='EVALUATION_CONTEXT_REQUIRED'


def test_evaluation_record_requires_explicit_bound_context(tmp_path,capsys):
    path=tmp_path/'parent.json'
    write_candidate(path,candidate())
    assert main(['evaluation','record',str(path)])==2
    assert json.loads(capsys.readouterr().out)['code']=='EVALUATION_RECORD_OPTIONS_REQUIRED'


def test_evaluation_existing_output_is_rejected_before_database_or_artifact_writes(tmp_path,capsys):
    output=tmp_path/'existing.json'; output.write_text('keep')
    assert main(['evaluation','record',str(tmp_path/'parent.json'),'--profile',str(tmp_path/'missing-profile.json'),
                 '--report',str(tmp_path/'report.json'),'--application-id','22222222-2222-4222-8222-222222222222',
                 '--expected-workspace-version','1','--evaluation-id','eval:1','--reviewer','operator',
                 '--decision','needs_revision','--coverage',str(tmp_path/'coverage.json'),'--output',str(output)])==2
    assert json.loads(capsys.readouterr().out)['code']=='OUTPUT_EXISTS'
    assert output.read_text()=='keep'


def test_candidate_export_preserves_parent_payload_and_existing_output(tmp_path, capsys):
    parent, payload, existing = [tmp_path / n for n in ['parent.json', 'payload.json', 'existing.json']]
    write_candidate(parent, candidate())
    payload.write_text('{"schema_version": 1}')
    existing.write_text('existing candidate must survive')
    originals = {p: p.read_bytes() for p in [parent, payload, existing]}
    for output in [parent, payload, existing]:
        code = main(['candidate', 'export', str(parent), '--payload', str(payload),
                     '--output', str(output), '--candidate-id', 'candidate:v2',
                     '--evaluation-id', 'evaluation:1', '--reviewer', 'reviewer'])
        assert code != 0
        capsys.readouterr()
        assert all(p.read_bytes() == content for p, content in originals.items())
