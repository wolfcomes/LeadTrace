import importlib
import json
import os
from pathlib import Path
import subprocess
from uuid import uuid4

import psycopg
from psycopg import sql
import pytest
from sqlalchemy.engine import make_url

from .test_preview_provision import provisioning, provisioner


def cleanup_module():
    assert importlib.util.find_spec('app.ai_prefill.preview_cleanup') is not None, 'native database archival is missing'
    return importlib.import_module('app.ai_prefill.preview_cleanup')


def test_archive_preserves_db_artifacts_and_destroy_only_owned_resources(provisioning, tmp_path):
    module = cleanup_module()
    admin_url, request, database, role = provisioning
    created = provisioner().create_preview(provisioning_url=admin_url, **request)
    root = created.registry_path.parent
    artifact = root / 'artifacts' / 'experiments' / 'keep' / 'feedback.json'
    artifact.parent.mkdir(parents=True)
    artifact.write_text('{"review":"preserve"}')
    archived = module.archive_preview(created.profile_path, tmp_path / 'archives')
    archive = Path(archived['archive_path'])
    assert (archive / 'database.dump').stat().st_size > 0
    data = json.loads((archive / 'database.json').read_text())
    assert len(data['papers']) == 20
    assert len(data['users']) == 2
    assert (archive / 'artifacts' / 'experiments' / 'keep' / 'feedback.json').read_text() == artifact.read_text()
    assert json.loads(created.registry_path.read_text())['state'] == 'archived'
    assert admin_url not in (archive / 'archive.json').read_text()
    # Prove the custom archive is restorable, not merely a nonempty file.
    restored_database = f'archive_restore_{uuid4().hex}_test'
    parsed = make_url(admin_url)
    env = {key: value for key, value in os.environ.items() if not key.startswith('PG')}
    env.update(PGHOST=str(parsed.query.get('host', parsed.host)),
               PGPORT=str(parsed.query.get('port', parsed.port or 5432)),
               PGUSER=parsed.username, PGPASSWORD=parsed.password or '', PGDATABASE=restored_database)
    with psycopg.connect(admin_url.replace('postgresql+psycopg:', 'postgresql:'), autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(restored_database)))
        try:
            result = subprocess.run(['pg_restore', '--no-owner', '--no-privileges', '--exit-on-error',
                                     '--dbname', restored_database, str(archive / 'database.dump')],
                                    env=env, capture_output=True, timeout=60)
            assert result.returncode == 0, result.stderr.decode()
            restored_url = parsed.set(database=restored_database).render_as_string(hide_password=False)
            with psycopg.connect(restored_url.replace('postgresql+psycopg:', 'postgresql:')) as restored:
                assert restored.execute('SELECT count(*) FROM papers').fetchone()[0] == 20
                assert restored.execute('SELECT count(*) FROM users').fetchone()[0] == 2
                assert restored.execute('SELECT instance_id FROM preview_markers').fetchone()[0] == request['instance_id']
        finally:
            admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(restored_database)))
    result = module.destroy_preview(created.profile_path, provisioning_url=admin_url,
                                    confirm_instance=request['instance_id'])
    assert result['state'] == 'destroyed'
    assert not (root / 'assets').exists()
    assert not (root / 'sources').exists()
    assert artifact.exists()  # Experiment artifacts are never cleanup targets.
    assert request['source_root'].exists()
    with psycopg.connect(admin_url.replace('postgresql+psycopg:', 'postgresql:')) as admin:
        assert not admin.execute('SELECT 1 FROM pg_database WHERE datname=%s', (database,)).fetchone()
        assert not admin.execute('SELECT 1 FROM pg_roles WHERE rolname=%s', (role,)).fetchone()
    assert module.destroy_preview(created.profile_path, provisioning_url=admin_url,
                                  confirm_instance=request['instance_id'])['state'] == 'destroyed'


@pytest.mark.parametrize('change', ['database', 'artifact', 'archive', 'marker', 'schema'])
def test_destroy_refuses_unarchived_or_mismatched_state(provisioning, tmp_path, change):
    module = cleanup_module()
    admin_url, request, database, role = provisioning
    created = provisioner().create_preview(provisioning_url=admin_url, **request)
    archived = module.archive_preview(created.profile_path, tmp_path / 'archives')
    if change in {'database', 'marker', 'schema'}:
        url = make_url(admin_url).set(database=database).render_as_string(hide_password=False)
        with psycopg.connect(url.replace('postgresql+psycopg:', 'postgresql:')) as connection:
            connection.execute({
                'database': "UPDATE papers SET title=title || ' edited'",
                'marker': "UPDATE preview_markers SET baseline_sha256=repeat('f',64)",
                'schema': "CREATE VIEW unarchived_review AS SELECT id,title FROM papers",
            }[change])
    elif change == 'artifact':
        (created.registry_path.parent / 'artifacts' / 'unarchived-feedback.json').write_text('{}')
    else:
        (Path(archived['archive_path']) / 'database.dump').write_bytes(b'corrupt')
    with pytest.raises(module.NativePreviewCleanupError):
        module.destroy_preview(created.profile_path, provisioning_url=admin_url,
                               confirm_instance=request['instance_id'])
    with psycopg.connect(admin_url.replace('postgresql+psycopg:', 'postgresql:')) as admin:
        assert admin.execute('SELECT 1 FROM pg_database WHERE datname=%s', (database,)).fetchone()


def test_archive_rejects_symlinks_without_altering_live_registry(provisioning, tmp_path):
    module = cleanup_module()
    admin_url, request, *_ = provisioning
    created = provisioner().create_preview(provisioning_url=admin_url, **request)
    (created.registry_path.parent / 'assets' / 'outside').symlink_to(tmp_path)
    with pytest.raises(module.NativePreviewCleanupError):
        module.archive_preview(created.profile_path, tmp_path / 'archives')
    assert json.loads(created.registry_path.read_text())['state'] == 'ready'


def test_destroy_resumes_after_file_cleanup_failure(provisioning, tmp_path, monkeypatch):
    module = cleanup_module()
    admin_url, request, *_ = provisioning
    created = provisioner().create_preview(provisioning_url=admin_url, **request)
    module.archive_preview(created.profile_path, tmp_path / 'archives')
    remove = module.shutil.rmtree
    def fail_assets(path, *args, **kwargs):
        if Path(path) == created.registry_path.parent / 'assets':
            raise OSError('injected file cleanup interruption')
        return remove(path, *args, **kwargs)
    monkeypatch.setattr(module.shutil, 'rmtree', fail_assets)
    with pytest.raises(module.NativePreviewCleanupError):
        module.destroy_preview(created.profile_path, provisioning_url=admin_url, confirm_instance=request['instance_id'])
    assert json.loads(created.registry_path.read_text())['state'] == 'destroying'
    monkeypatch.setattr(module.shutil, 'rmtree', remove)
    assert module.destroy_preview(created.profile_path, provisioning_url=admin_url, confirm_instance=request['instance_id'])['state'] == 'destroyed'


def test_destroy_recovers_when_drop_fails_after_connections_disabled(provisioning, tmp_path, monkeypatch):
    module = cleanup_module()
    admin_url, request, database, *_ = provisioning
    created = provisioner().create_preview(provisioning_url=admin_url, **request)
    module.archive_preview(created.profile_path, tmp_path / 'archives')
    def fail(*args):
        raise OSError('injected database drop interruption')
    monkeypatch.setattr(module, '_drop_database', fail, raising=False)
    with pytest.raises(module.NativePreviewCleanupError):
        module.destroy_preview(created.profile_path, provisioning_url=admin_url, confirm_instance=request['instance_id'])
    with psycopg.connect(admin_url.replace('postgresql+psycopg:', 'postgresql:')) as admin:
        assert admin.execute('SELECT 1 FROM pg_database WHERE datname=%s', (database,)).fetchone()
    monkeypatch.undo()
    assert module.destroy_preview(created.profile_path, provisioning_url=admin_url, confirm_instance=request['instance_id'])['state'] == 'destroyed'


def test_archive_recovers_interrupted_archiving_state(provisioning, tmp_path):
    module=cleanup_module()
    admin_url,request,*_=provisioning
    created=provisioner().create_preview(provisioning_url=admin_url,**request)
    registry=json.loads(created.registry_path.read_text())
    registry['state']='archiving'
    created.registry_path.write_text(json.dumps(registry))
    assert module.archive_preview(created.profile_path,tmp_path/'archives')['state']=='archived'


def test_destroy_resumes_after_partial_directory_removal(provisioning,tmp_path,monkeypatch):
    module=cleanup_module()
    admin_url,request,*_=provisioning
    created=provisioner().create_preview(provisioning_url=admin_url,**request)
    assets=created.registry_path.parent/'assets'
    (assets/'first.png').write_bytes(b'first')
    (assets/'second.png').write_bytes(b'second')
    module.archive_preview(created.profile_path,tmp_path/'archives')
    remove=module.shutil.rmtree
    def partial(path,*args,**kwargs):
        if Path(path)==assets:
            (assets/'first.png').unlink()
            raise OSError('interrupted halfway through directory')
        return remove(path,*args,**kwargs)
    monkeypatch.setattr(module.shutil,'rmtree',partial)
    with pytest.raises(module.NativePreviewCleanupError):
        module.destroy_preview(created.profile_path,provisioning_url=admin_url,confirm_instance=request['instance_id'])
    monkeypatch.setattr(module.shutil,'rmtree',remove)
    assert module.destroy_preview(created.profile_path,provisioning_url=admin_url,confirm_instance=request['instance_id'])['state']=='destroyed'


@pytest.mark.parametrize('statement',["SELECT lo_create(0)","CREATE MATERIALIZED VIEW unsupported_cache AS SELECT id FROM papers"])
def test_archive_refuses_objects_outside_supported_database_fingerprint(provisioning,tmp_path,statement):
    module=cleanup_module(); admin_url,request,database,*_=provisioning
    created=provisioner().create_preview(provisioning_url=admin_url,**request)
    url=make_url(admin_url).set(database=database).render_as_string(hide_password=False)
    with psycopg.connect(url.replace('postgresql+psycopg:','postgresql:')) as connection:
        connection.execute(statement)
    with pytest.raises(module.NativePreviewCleanupError):
        module.archive_preview(created.profile_path,tmp_path/'archives')
