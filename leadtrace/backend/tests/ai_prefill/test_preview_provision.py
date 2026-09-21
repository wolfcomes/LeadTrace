"""Provision real fresh databases using only an explicit isolated test cluster."""
import importlib
import json
import stat
import hashlib
import socket
from uuid import uuid4

import psycopg
from psycopg import sql
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ProgrammingError

from app.database import bootstrap_database
from app.config import Settings
from app.main import create_app
from tests.catalog.test_import import _pilot_fixture


@pytest.fixture
def provisioning(postgresql_database_url, tmp_path):
    parent = make_url(postgresql_database_url)
    assert parent.database.endswith('_test')
    instance_id = uuid4()
    database = f'lt_{instance_id.hex}_preview'
    role = f'lt_{instance_id.hex}_runtime'
    admin_database = f'lt_{instance_id.hex}_preview_admin'
    admin_url = parent.set(database=admin_database).render_as_string(hide_password=False)
    with psycopg.connect(postgresql_database_url.replace('postgresql+psycopg:', 'postgresql:'), autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0').format(sql.Identifier(admin_database)))
    source, manifest = _pilot_fixture(tmp_path)
    request = dict(instance_id=instance_id, registry_root=tmp_path / 'instances',
                   manifest_path=manifest, source_root=source, origin='http://127.0.0.1:18080',
                   commit='test-commit', lockfile_sha256='c' * 64)
    yield admin_url, request, database, role
    with psycopg.connect(postgresql_database_url.replace('postgresql+psycopg:', 'postgresql:'), autocommit=True) as admin:
        exists = admin.execute('SELECT 1 FROM pg_database WHERE datname=%s', (database,)).fetchone()
        if exists:
            admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(database)))
        admin.execute(sql.SQL('DROP ROLE IF EXISTS {}').format(sql.Identifier(role)))
        admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(admin_database)))


def provisioner():
    assert importlib.util.find_spec('app.ai_prefill.preview_provision') is not None, 'real Preview provisioner is missing'
    return importlib.import_module('app.ai_prefill.preview_provision')


def test_creates_seeded_preview_with_restricted_role_and_private_credentials(provisioning):
    module = provisioner()
    admin_url, request, database, role = provisioning
    result = module.create_preview(provisioning_url=admin_url, **request)
    registry = json.loads(result.registry_path.read_text())
    profile = json.loads(result.profile_path.read_text())
    credentials = json.loads(result.credentials_path.read_text())
    assert registry['state'] == 'ready'
    assert registry['database_name'] == database
    assert registry['runtime_role'] == role
    assert stat.S_IMODE(result.profile_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(result.credentials_path.stat().st_mode) == 0o600
    assert admin_url not in result.profile_path.read_text()
    assert 'prefill_test_admin' not in result.profile_path.read_text()
    assert make_url(profile['database_url']).username == role
    assert len(profile['session_secret']) >= 32
    assert profile['session_secret'] != '**********'
    assert profile['source_roots']['source_pdfs'] != str(request['source_root'])
    settings = Settings(_env_file=None, **profile)
    resources = bootstrap_database(settings)
    try:
        with resources.engine.connect() as connection:
            assert connection.scalar(text('SELECT count(*) FROM papers')) == 20
            assert connection.scalar(text('SELECT count(*) FROM paper_sources')) == 20
            assert connection.scalar(text('SELECT count(*) FROM users')) == 2
            assert connection.scalar(text('SELECT current_user')) == role
            flags = connection.execute(text('SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls FROM pg_roles WHERE rolname=current_user')).one()
            assert not any(flags)
            connection.execute(text('SELECT * FROM preview_markers FOR UPDATE'))
            connection.rollback()
            connection.execution_options(isolation_level='AUTOCOMMIT')
            for forbidden in ['CREATE TABLE forbidden (id int)', 'CREATE DATABASE forbidden_preview',
                              "UPDATE preview_markers SET baseline_sha256=repeat('f',64)",
                              'DELETE FROM preview_markers', 'DELETE FROM alembic_version']:
                with pytest.raises(ProgrammingError) as rejected:
                    connection.execute(text(forbidden))
                assert rejected.value.orig.sqlstate == '42501'
                connection.rollback()
        with resources.engine.connect() as connection:
            paper_id = connection.scalar(text('SELECT id FROM papers ORDER BY paper_key LIMIT 1'))
            digest = connection.scalar(text('SELECT s.sha256 FROM paper_sources s JOIN papers p ON p.source_id=s.id WHERE p.id=:id'), {'id': paper_id})
        with TestClient(create_app(settings=settings), base_url=result.origin) as client:
            assert client.get('/health/ready').status_code == 200
            for account in credentials['accounts']:
                response = client.post('/api/v1/auth/login', json=account)
                assert response.status_code == 200, response.text
                assert response.json()['user']['username'] == account['username']
                if account['username'] == 'preview-admin':
                    pdf = client.get(f'/api/v2/papers/{paper_id}/source-pdf')
                    assert pdf.status_code == 200, pdf.text
                    assert hashlib.sha256(pdf.content).hexdigest() == digest
    finally:
        resources.close()
    with pytest.raises(module.PreviewProvisionError):
        module.create_preview(provisioning_url=admin_url, **request)
    for account in credentials['accounts']:
        assert account['password'] not in result.registry_path.read_text()
        assert account['password'] not in repr(result)


def test_invalid_catalog_creates_no_resources(provisioning):
    module = provisioner()
    admin_url, request, database, role = provisioning
    manifest = json.loads(request['manifest_path'].read_text())
    manifest['entries'].pop()
    request['manifest_path'].write_text(json.dumps(manifest))
    with pytest.raises(module.PreviewProvisionError):
        module.create_preview(provisioning_url=admin_url, **request)
    assert not request['registry_root'].exists()
    with psycopg.connect(admin_url.replace('postgresql+psycopg:', 'postgresql:')) as admin:
        assert not admin.execute('SELECT 1 FROM pg_database WHERE datname=%s', (database,)).fetchone()
        assert not admin.execute('SELECT 1 FROM pg_roles WHERE rolname=%s', (role,)).fetchone()


def test_failed_seed_stays_initializing_and_rolls_back_catalog(provisioning, monkeypatch):
    module = provisioner()
    admin_url, request, database, role = provisioning
    from app.users.service import UserService
    def fail(*args, **kwargs):
        raise RuntimeError('injected seed failure')
    monkeypatch.setattr(UserService, 'bootstrap_admin', fail)
    with pytest.raises(module.PreviewProvisionError, match='initializing'):
        module.create_preview(provisioning_url=admin_url, **request)
    root = request['registry_root'] / str(request['instance_id'])
    assert json.loads((root / 'registry.json').read_text())['state'] == 'initializing'
    assert not (root / 'runtime.json').exists()
    url = make_url(admin_url).set(database=database).render_as_string(hide_password=False)
    with psycopg.connect(url.replace('postgresql+psycopg:', 'postgresql:')) as connection:
        assert connection.execute('SELECT count(*) FROM papers').fetchone()[0] == 0
        assert connection.execute('SELECT count(*) FROM preview_markers').fetchone()[0] == 0


def test_refuses_implicit_or_non_provisioning_database(provisioning):
    module = provisioner()
    admin_url, request, *_ = provisioning
    with pytest.raises(module.PreviewProvisionError):
        module.create_preview(provisioning_url=make_url(admin_url).set(database='production').render_as_string(hide_password=False), **request)
    assert not request['registry_root'].exists()


def test_cli_creates_then_runs_native_backend(provisioning, capsys):
    from leadtrace.ops.ai_prefill.cli import main
    from urllib.request import ProxyHandler, build_opener
    admin_url, request, *_ = provisioning
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    request['origin'] = f'http://127.0.0.1:{port}'
    profile = request['manifest_path'].parent / 'provisioning.json'
    profile.write_text(json.dumps({'database_url': admin_url}))
    profile.chmod(0o600)
    assert main(['preview', 'create', '--registry-root', str(request['registry_root']),
                 '--instance-id', str(request['instance_id']), '--provisioning-profile', str(profile),
                 '--manifest', str(request['manifest_path']), '--source-root', str(request['source_root']),
                 '--origin', request['origin'], '--commit', request['commit'],
                 '--lockfile-sha256', request['lockfile_sha256']]) == 0
    output = capsys.readouterr()
    result = json.loads(output.out)
    assert result['scope'] == 'native_backend'
    assert admin_url not in output.out + output.err
    runtime = result['profile_path']
    try:
        assert main(['preview', 'start', '--profile', runtime]) == 0
        assert json.loads(capsys.readouterr().out)['status'] == 'running'
        with build_opener(ProxyHandler({})).open(request['origin'] + '/health/ready', timeout=5) as response:
            assert response.status == 200
        assert main(['preview', 'status', '--profile', runtime]) == 0
        assert json.loads(capsys.readouterr().out)['status'] == 'running'
    finally:
        assert main(['preview', 'stop', '--profile', runtime]) == 0
        assert json.loads(capsys.readouterr().out)['status'] == 'stopped'


def test_restricted_runtime_applies_and_replays_candidate(provisioning):
    from app.ai_prefill.assistance_contracts import SourceIdentity, with_computed_hashes
    from app.ai_prefill.assistance_validation import validate_candidate
    from app.ai_prefill.preview_application import PreviewApplicationService
    from app.ai_prefill.contracts import AiPrefillPayload
    from .test_preview_application import make_candidate
    admin_url, request, *_ = provisioning
    result = provisioner().create_preview(provisioning_url=admin_url, **request)
    settings = Settings(_env_file=None, **json.loads(result.profile_path.read_text()))
    resources = bootstrap_database(settings)
    try:
        with resources.session_factory() as session:
            row = session.execute(text('SELECT p.id, p.paper_key, s.sha256, s.byte_size, s.page_count FROM papers p JOIN paper_sources s ON p.source_id=s.id ORDER BY p.paper_key LIMIT 1')).one()
            admin_id = session.scalar(text("SELECT id FROM users WHERE username='preview-admin'"))
            reviewer_id = session.scalar(text("SELECT id FROM users WHERE username='preview-reviewer'"))
        candidate = make_candidate(AiPrefillPayload.model_validate({
            'schema_version': 1,
            'compounds': [{'ref': 'c1', 'compound_label': '1', 'structure': {'smiles': 'CCO'}}],
            'structure_locators': [{'ref': 'crop:1', 'compound_ref': 'c1', 'page_number': 1,
                                    'bbox': {'x0': 0.1, 'y0': 0.1, 'x1': 0.5, 'y1': 0.5}}],
        }))
        candidate = with_computed_hashes(candidate.model_copy(update={'source': SourceIdentity(paper_key=row.paper_key,
            source_sha256=row.sha256, byte_size=row.byte_size, page_count=row.page_count), 'hashes': None}))
        report = validate_candidate(candidate)
        service = PreviewApplicationService(settings=settings)
        parameters = dict(instance_id=request['instance_id'], idempotency_key='restricted-role-apply',
                          candidate=candidate, validation_report=report, actor_id=admin_id,
                          reviewer_id=reviewer_id, paper_id=row.id)
        with resources.session_factory.begin() as session:
            applied = service.apply(session, **parameters)
            assert applied.applied
            assert session.scalar(text("SELECT crop_status FROM structure_source_images")) == 'ready'
            application_id = applied.receipt.application_id
        with resources.session_factory.begin() as session:
            replay = service.apply(session, **parameters)
            assert replay.idempotent
            assert replay.receipt.application_id == application_id
            assert session.scalar(text('SELECT count(*) FROM preview_application_receipts')) == 1
    finally:
        resources.close()


def test_creation_ignores_inherited_nested_source_settings(provisioning, monkeypatch):
    monkeypatch.setenv('LEADTRACE_SOURCE_ROOTS', json.dumps({'production_sources': '/production/pdfs'}))
    monkeypatch.setenv('LEADTRACE_SESSION_SECRET', 'do-not-copy-inherited-secret')
    admin_url, request, *_ = provisioning
    result = provisioner().create_preview(provisioning_url=admin_url, **request)
    profile = json.loads(result.profile_path.read_text())
    assert set(profile['source_roots']) == {'source_pdfs'}
    assert profile['session_secret'] != 'do-not-copy-inherited-secret'
    assert json.loads(result.registry_path.read_text())['phase'] == 'ready'


def test_creation_refuses_ambiguous_localhost_origin(provisioning):
    admin_url, request, *_ = provisioning
    request['origin'] = 'http://localhost:18080'
    module = provisioner()
    with pytest.raises(module.PreviewProvisionError):
        module.create_preview(provisioning_url=admin_url, **request)
    assert not request['registry_root'].exists()


def test_creation_accepts_distinct_literal_loopback_host(provisioning):
    admin_url, request, *_ = provisioning
    request['origin'] = 'http://127.74.1.2:18080'
    result = provisioner().create_preview(provisioning_url=admin_url, **request)
    profile = json.loads(result.profile_path.read_text())
    assert profile['allowed_hosts'] == ['127.74.1.2']
