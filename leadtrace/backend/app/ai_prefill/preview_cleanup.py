"""Verified native Preview archive and exact database/resource destruction."""
from __future__ import annotations

from contextlib import contextmanager
from functools import wraps
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
from uuid import UUID, uuid4

from psycopg import sql
from sqlalchemy import text
from sqlalchemy.engine import make_url

from app.ai_prefill.preview_identity import _safe_path, verify_preview_connection
from app.ai_prefill.preview_process import _locked, _owned, _record, load_runtime_settings, stop_preview
from app.ai_prefill.preview_provision import _connect, _private_json
from app.ai_prefill.preview_runtime import PreviewRuntime
from app.database import create_database_engine, postgresql_url


class NativePreviewCleanupError(RuntimeError):
    pass


def _safe_operation(function):
    @wraps(function)
    def operation(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except NativePreviewCleanupError:
            raise
        except Exception:
            raise NativePreviewCleanupError('Preview maintenance failed identity or resource verification; inspect the registry phase') from None
    return operation


def _json(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':'), default=str) + '\n').encode()


def _sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _tree(root: Path):
    _safe_path(root, 'archive resource')
    if not root.is_dir():
        raise NativePreviewCleanupError('Preview resource directory is missing')
    result = {}
    for path in sorted(root.rglob('*')):
        _safe_path(path, 'archive member')
        if path.is_file():
            result[str(path.relative_to(root))] = _sha(path)
        elif not path.is_dir():
            raise NativePreviewCleanupError('Archive resources must be regular files or directories')
    return result


def _load(profile):
    profile = Path(profile).absolute()
    settings = load_runtime_settings(profile)
    root = settings.preview_registry_path.parent
    if profile != root / 'runtime.json' or root.name != str(settings.preview_instance_id):
        raise NativePreviewCleanupError('Unmanaged Preview profile location')
    runtime = PreviewRuntime(root.parent)
    registry = runtime.read(settings.preview_instance_id)
    if (registry.get('management') != 'native-v1'
            or registry.get('runtime_role') != f'lt_{settings.preview_instance_id.hex}_runtime'
            or registry.get('database_name') != f'lt_{settings.preview_instance_id.hex}_preview'):
        raise NativePreviewCleanupError('Unmanaged Preview database identity')
    for name, path in [('assets', settings.asset_root), ('sources', settings.source_roots['source_pdfs']), ('artifacts', settings.preview_artifact_root)]:
        if path != root / name:
            raise NativePreviewCleanupError('Unmanaged Preview resource path')
    return profile, settings, runtime, registry


def _write_registry(runtime, settings, registry):
    runtime._write(settings.preview_registry_path, registry, create=False)


@contextmanager
def _identity_settings(settings, registry):
    # Archived instances are intentionally blocked for Web. Only this local
    # maintenance operation verifies an otherwise identical unpublished snapshot.
    with TemporaryDirectory(prefix='.maintenance-', dir=settings.preview_registry_path.parent) as temporary:
        path = Path(temporary) / 'registry.json'
        _private_json(path, {**registry, 'state': 'ready'})
        yield settings.model_copy(update={'preview_registry_path': path})


def _database_rows(connection):
    schemas = connection.scalars(text("SELECT nspname FROM pg_namespace WHERE nspname !~ '^pg_' AND nspname<>'information_schema' ORDER BY nspname")).all()
    if schemas != ['public']:
        raise NativePreviewCleanupError('Unexpected database schema requires explicit reconciliation')
    if connection.scalar(text('SELECT EXISTS (SELECT 1 FROM pg_largeobject_metadata)')) or connection.scalar(text("SELECT EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relkind IN ('m','f'))")):
        raise NativePreviewCleanupError('Unsupported database objects require explicit reconciliation')
    names = connection.scalars(text("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")).all()
    result = {}
    for name in names:
        identifier = connection.dialect.identifier_preparer.quote(name)
        rows = [json.loads(row, parse_float=str) for row in connection.scalars(text(f'SELECT to_jsonb(t)::text FROM public.{identifier} t'))]
        result[name] = sorted(rows, key=lambda row: _json(row))
    definitions = {
        'columns': "SELECT table_name,column_name,ordinal_position,column_default,is_nullable,data_type,udt_name,is_identity,identity_generation,identity_start,identity_increment,is_generated,generation_expression FROM information_schema.columns WHERE table_schema='public'",
        'relations': "SELECT c.relname,c.relkind,c.relrowsecurity,c.relforcerowsecurity,c.reloptions,c.relacl FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public'",
        'constraints': "SELECT c.conname,c.contype,c.conrelid::regclass::text AS relation,pg_get_constraintdef(c.oid) AS definition FROM pg_constraint c JOIN pg_namespace n ON n.oid=c.connamespace WHERE n.nspname='public'",
        'indexes': "SELECT tablename,indexname,indexdef FROM pg_indexes WHERE schemaname='public'",
        'views': "SELECT viewname,definition FROM pg_views WHERE schemaname='public'",
        'functions': "SELECT p.proname,pg_get_functiondef(p.oid) AS definition,p.proacl FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public' AND p.prokind<>'a'",
        'triggers': "SELECT t.tgname,pg_get_triggerdef(t.oid) AS definition,t.tgenabled FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND NOT t.tgisinternal",
        'enums': "SELECT t.typname,e.enumlabel,e.enumsortorder FROM pg_enum e JOIN pg_type t ON t.oid=e.enumtypid JOIN pg_namespace n ON n.oid=t.typnamespace WHERE n.nspname='public'",
        'policies': "SELECT * FROM pg_policies WHERE schemaname='public'",
        'sequences': "SELECT sequencename,data_type::text,start_value,min_value,max_value,increment_by,cycle,cache_size,last_value FROM pg_sequences WHERE schemaname='public'",
    }
    result['__schema__'] = {key: sorted([dict(row) for row in connection.execute(text(query)).mappings()], key=_json)
                            for key, query in definitions.items()}
    return result


def _pg_dump(settings, snapshot_id, output):
    url = make_url(settings.database_url)
    executable = shutil.which('pg_dump')
    if executable is None:
        raise NativePreviewCleanupError('pg_dump is required for native archival')
    env = {key: value for key, value in os.environ.items() if not key.startswith('PG')}
    env.update(PGHOST=str(url.query.get('host', url.host)), PGPORT=str(url.query.get('port', url.port or 5432)),
               PGUSER=url.username, PGPASSWORD=url.password or '', PGDATABASE=url.database,
               PGCONNECT_TIMEOUT='5')
    if 'sslmode' in url.query:
        env['PGSSLMODE'] = url.query['sslmode']
    result = subprocess.run([executable, '--format=custom', '--no-owner', '--no-privileges',
                             '--snapshot', snapshot_id, '--file', str(output)], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=120)
    if result.returncode:
        raise NativePreviewCleanupError('Database archive failed; no resources were deleted')
    output.chmod(0o600)


def _ensure_stopped(profile):
    record = _record(profile)
    if record is not None and _owned(record, profile):
        raise NativePreviewCleanupError('Preview process must be stopped before maintenance')


@_safe_operation
def archive_preview(profile_path: Path, archive_root: Path) -> dict:
    profile, settings, runtime, registry = _load(profile_path)
    if registry.get('state') not in {'ready', 'archived', 'archiving'}:
        raise NativePreviewCleanupError('Only ready or archived instances can be archived')
    archive_root = Path(archive_root).absolute()
    _safe_path(archive_root, 'archive root')
    if archive_root.is_relative_to(profile.parent) or profile.parent.is_relative_to(archive_root):
        raise NativePreviewCleanupError('Archive root must be disjoint from the instance')
    resources = {key: profile.parent / key for key in ('assets', 'sources', 'artifacts')}
    before = {key: _tree(path) for key, path in resources.items()}
    stop_preview(profile)
    with _locked(profile):
        _ensure_stopped(profile)
        # Refresh after obtaining the same lock used by start/stop.
        registry = runtime.read(settings.preview_instance_id)
        if registry.get('state') not in {'ready', 'archived', 'archiving'}:
            raise NativePreviewCleanupError('Preview lifecycle state changed')
        original = dict(registry)
        engine = create_database_engine(settings.database_url)
        try:
            with _identity_settings(settings, registry) as checked, engine.connect() as connection:
                connection.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY'))
                verify_preview_connection(checked, connection)
                rows = _database_rows(connection)
                role_oid = connection.scalar(text('SELECT oid FROM pg_roles WHERE rolname=:role'), {'role': registry['runtime_role']})
                database_oid = connection.scalar(text('SELECT oid FROM pg_database WHERE datname=current_database()'))
                if role_oid is None:
                    raise NativePreviewCleanupError('Runtime role is missing')
                registry['state'] = 'archiving'
                _write_registry(runtime, settings, registry)
                archive_root.mkdir(parents=True, exist_ok=True, mode=0o700)
                destination = archive_root / f'{settings.preview_instance_id}-{uuid4().hex}'
                with TemporaryDirectory(prefix='.archive-', dir=archive_root) as temporary:
                    stage = Path(temporary)
                    _private_json(stage / 'database.json', rows)
                    snapshot_id = connection.scalar(text('SELECT pg_export_snapshot()'))
                    _pg_dump(settings, snapshot_id, stage / 'database.dump')
                    for name, source in resources.items():
                        shutil.copytree(source, stage / name)
                    after = {key: _tree(path) for key, path in resources.items()}
                    if before != after or any(_tree(stage / key) != before[key] for key in resources):
                        raise NativePreviewCleanupError('Preview files changed during archival')
                    files = _tree(stage)
                    manifest = {'schema_version': 1, 'instance_id': str(settings.preview_instance_id),
                                'registry': original, 'database_sha256': hashlib.sha256(_json(rows)).hexdigest(),
                                'runtime_role_oid': role_oid, 'database_oid': database_oid, 'resources': before, 'files': files}
                    _private_json(stage / 'archive.json', manifest)
                    digest = _sha(stage / 'archive.json')
                    os.rename(stage, destination)
                registry.update(state='archived', archive_path=str(destination), archive_sha256=digest,
                                runtime_role_oid=role_oid, phase='archived')
                _write_registry(runtime, settings, registry)
                return {'state': 'archived', 'instance_id': str(settings.preview_instance_id),
                        'archive_path': str(destination), 'archive_sha256': digest}
        except Exception as error:
            if registry.get('state') == 'archiving':
                _write_registry(runtime, settings, original)
            if isinstance(error, NativePreviewCleanupError):
                raise
            raise NativePreviewCleanupError('Native Preview archival failed; resources were preserved') from None
        finally:
            engine.dispose()


def _verify_archive(registry, settings):
    path = Path(registry.get('archive_path', ''))
    _safe_path(path, 'archive')
    manifest_path = path / 'archive.json'
    _safe_path(manifest_path, 'archive manifest')
    if not manifest_path.is_file() or _sha(manifest_path) != registry.get('archive_sha256'):
        raise NativePreviewCleanupError('Archive manifest is missing or changed')
    value = json.loads(manifest_path.read_bytes())
    if value.get('instance_id') != str(settings.preview_instance_id):
        raise NativePreviewCleanupError('Archive instance identity differs')
    for name in ('instance_id', 'database_name', 'database_host', 'database_port', 'baseline_sha256',
                 'schema_revision', 'runtime_role', 'asset_root', 'source_root', 'artifact_root'):
        if value['registry'].get(name) != registry.get(name):
            raise NativePreviewCleanupError('Registry changed after archive')
    files = _tree(path)
    files.pop('archive.json', None)
    if files != value['files']:
        raise NativePreviewCleanupError('Archive files are missing or changed')
    return value


def _drop_database(admin, database):
    admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(database)))


@_safe_operation
def destroy_preview(profile_path: Path, *, provisioning_url: str, confirm_instance: UUID) -> dict:
    profile, settings, runtime, registry = _load(profile_path)
    if str(confirm_instance) != str(settings.preview_instance_id):
        raise NativePreviewCleanupError('Exact instance confirmation is required')
    if registry.get('state') == 'destroyed':
        _verify_archive(registry, settings)
        return {'state': 'destroyed', 'instance_id': str(settings.preview_instance_id)}
    if registry.get('state') not in {'archived', 'destroying'}:
        raise NativePreviewCleanupError('Complete archive is required before destroy')
    archive = _verify_archive(registry, settings)
    parent = postgresql_url(provisioning_url)
    expected = make_url(settings.database_url)
    if (not parent.database.endswith('_preview_admin')
            or parent.query.get('host', parent.host) != expected.query.get('host', expected.host)
            or str(parent.query.get('port', parent.port or 5432)) != str(expected.query.get('port', expected.port or 5432))
            or set(parent.query) - {'host', 'port', 'sslmode'}):
        raise NativePreviewCleanupError('Provisioning endpoint differs from archived Preview')
    with _locked(profile):
        _ensure_stopped(profile)
        registry = runtime.read(settings.preview_instance_id)
        if registry.get('state') not in {'archived', 'destroying'}:
            raise NativePreviewCleanupError('Preview lifecycle state changed')
        archive = _verify_archive(registry, settings)
        with _connect(parent, autocommit=True) as admin:
            database = registry['database_name']
            role = registry['runtime_role']
            role_row = admin.execute('SELECT oid FROM pg_roles WHERE rolname=%s', (role,)).fetchone()
            if role_row and role_row[0] != archive['runtime_role_oid']:
                raise NativePreviewCleanupError('Runtime role identity changed after archival')
            exists = admin.execute('SELECT oid, datallowconn FROM pg_database WHERE datname=%s', (database,)).fetchone()
            if exists:
                if exists[0] != archive['database_oid']:
                    raise NativePreviewCleanupError('Database was replaced after archival')
                if not exists[1]:
                    if registry.get('state') != 'destroying':
                        raise NativePreviewCleanupError('Unexpected disabled database')
                    admin.execute(sql.SQL('ALTER DATABASE {} ALLOW_CONNECTIONS true').format(sql.Identifier(database)))
                for name in ('assets', 'sources', 'artifacts'):
                    if _tree(profile.parent / name) != archive['resources'][name]:
                        raise NativePreviewCleanupError('Unarchived resource changes prevent destruction')
                engine = create_database_engine(parent.set(database=database).render_as_string(hide_password=False))
                try:
                    with _identity_settings(settings, registry) as checked, engine.connect() as connection:
                        connection.execute(text("SET LOCAL lock_timeout='5s'"))
                        tables = connection.scalars(text("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")).all()
                        names = ', '.join('public.' + connection.dialect.identifier_preparer.quote(name) for name in tables)
                        connection.execute(text(f'LOCK TABLE {names} IN ACCESS EXCLUSIVE MODE'))
                        verify_preview_connection(checked, connection)
                        if hashlib.sha256(_json(_database_rows(connection))).hexdigest() != archive['database_sha256']:
                            raise NativePreviewCleanupError('Unarchived database edits prevent destruction')
                        registry.update(state='destroying', phase='database_drop')
                        _write_registry(runtime, settings, registry)
                        # Block new connections while table locks prevent writes.
                        admin.execute(sql.SQL('ALTER DATABASE {} ALLOW_CONNECTIONS false').format(sql.Identifier(database)))
                        own_pid = connection.scalar(text('SELECT pg_backend_pid()'))
                        admin.execute('SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s AND pid<>%s', (database, own_pid))
                finally:
                    engine.dispose()
                _drop_database(admin, database)
            elif registry.get('state') != 'destroying':
                raise NativePreviewCleanupError('Database missing without a verified destruction journal')
            if role_row:
                admin.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))
            registry.update(state='destroying', phase='files')
            _write_registry(runtime, settings, registry)
            # Preserve registry, profile and experiments; delete only owned source/asset copies.
            for name in ('assets', 'sources'):
                path = profile.parent / name
                if path.exists():
                    remaining = _tree(path)
                    if any(archive['resources'][name].get(key) != digest for key, digest in remaining.items()):
                        raise NativePreviewCleanupError('Resource changed before deletion')
                    shutil.rmtree(path)
            registry.update(state='destroyed', phase='destroyed')
            _write_registry(runtime, settings, registry)
            return {'state': 'destroyed', 'instance_id': str(settings.preview_instance_id), 'archive_path': registry['archive_path']}
