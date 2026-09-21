"""Create a fresh native Preview in an explicitly selected isolated PostgreSQL cluster.

Provisioning credentials never enter the runtime profile. Failed initialization
is retained for diagnosis; this module never adopts or deletes existing resources.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from ipaddress import IPv4Address
import json
import os
from pathlib import Path
import secrets
import shutil
import stat
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit
from uuid import UUID

from alembic import command
from alembic.config import Config
import psycopg
from psycopg import sql
from sqlalchemy.engine import URL

from app.ai_prefill.preview_identity import _safe_path, _schema_head, verify_preview_connection
from app.ai_prefill.preview_models import PreviewMarker
from app.ai_prefill.preview_runtime import PreviewRuntime, _digest
from app.assets.storage import LocalAssetStore
from app.catalog.service import CatalogImportService
from app.config import Settings
from app.database import DEFAULT_ALEMBIC_CONFIG_PATH, create_database_engine, create_session_factory, postgresql_url
from app.users.models import UserRole
from app.users.service import UserService


class PreviewProvisionError(RuntimeError):
    pass


class _ProvisionSettings(Settings):
    @classmethod
    def settings_customise_sources(cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings):
        return (init_settings,)


def load_provisioning_url(path: Path) -> str:
    """Privileged endpoint is accepted only from an owned private regular file."""
    try:
        _safe_path(path, 'provisioning profile')
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
                raise ValueError
            data = stream.read(65_537)
        if len(data) > 65_536:
            raise ValueError
        value = json.loads(data)
        if not isinstance(value, dict) or set(value) != {'database_url'} or not isinstance(value['database_url'], str):
            raise ValueError
        return value['database_url']
    except Exception:
        raise PreviewProvisionError('Provisioning profile must be an owned mode-0600 regular JSON file containing database_url') from None


@dataclass(frozen=True)
class ProvisionedPreview:
    instance_id: UUID
    registry_path: Path
    profile_path: Path
    credentials_path: Path
    origin: str
    catalog_count: int = 20


def _connect(url: URL, **kwargs):
    return psycopg.connect(url.set(drivername='postgresql').render_as_string(hide_password=False), connect_timeout=5, **kwargs)


def _private_json(path: Path, value: dict) -> None:
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(value, stream, sort_keys=True)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def _settings_json(settings: Settings) -> dict:
    value = settings.model_dump(mode='json')
    for name in ('session_secret', 'default_account_password', 'metrics_bearer_token'):
        secret = getattr(settings, name)
        value[name] = secret.get_secret_value() if secret is not None else None
    return value


def _record_phase(runtime: PreviewRuntime, instance_id: UUID, phase: str) -> None:
    registry = runtime.read(instance_id)
    registry['phase'] = phase
    runtime._write(runtime._path(instance_id), registry, create=False)


def _grant_runtime(url: URL, database: str, role: str) -> None:
    ident = sql.Identifier(role)
    with _connect(url, autocommit=True) as connection:
        connection.execute(sql.SQL('REVOKE ALL ON DATABASE {} FROM PUBLIC').format(sql.Identifier(database)))
        connection.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO {}').format(sql.Identifier(database), ident))
        connection.execute('REVOKE ALL ON SCHEMA public FROM PUBLIC')
        connection.execute(sql.SQL('GRANT USAGE ON SCHEMA public TO {}').format(ident))
        tables = connection.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'").fetchall()
        for (name,) in tables:
            table = sql.Identifier('public', name)
            if name in {'alembic_version', 'preview_markers', 'preview_application_receipts'}:
                connection.execute(sql.SQL('GRANT SELECT ON {} TO {}').format(table, ident))
                if name != 'alembic_version':
                    # PostgreSQL requires an UPDATE privilege for SELECT FOR UPDATE.
                    connection.execute(sql.SQL('GRANT UPDATE (id) ON {} TO {}').format(table, ident))
                if name == 'preview_application_receipts':
                    connection.execute(sql.SQL('GRANT INSERT ON {} TO {}').format(table, ident))
            else:
                connection.execute(sql.SQL('GRANT SELECT, INSERT, UPDATE, DELETE ON {} TO {}').format(table, ident))
        connection.execute(sql.SQL('GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {}').format(ident))


def create_preview(*, provisioning_url: str, instance_id: UUID, registry_root: Path,
                   manifest_path: Path, source_root: Path, origin: str,
                   commit: str, lockfile_sha256: str) -> ProvisionedPreview:
    """Preflight, snapshot, migrate and seed a new instance; publish ready last."""
    phase = 'preflight'
    reserved = False
    try:
        instance_id = UUID(str(instance_id))
        parent = postgresql_url(provisioning_url)
        host = parent.query.get('host', parent.host)
        port = int(parent.query.get('port', parent.port or 5432))
        if (not parent.database or not parent.database.endswith('_preview_admin')
                or not parent.username or not isinstance(host, str) or not host
                or not 1 <= port <= 65535
                or set(parent.query) - {'host', 'port', 'sslmode'}):
            raise ValueError('explicit provisioning endpoint required')
        if parent.host and parent.query.get('host') and parent.host != parent.query['host']:
            raise ValueError('ambiguous host')
        parsed = urlsplit(origin)
        address = IPv4Address(parsed.hostname)
        if (parsed.scheme != 'http' or not address.is_loopback or str(address) != parsed.hostname
                or parsed.username or parsed.password or parsed.path not in {'', '/'}
                or parsed.query or parsed.fragment or not parsed.port):
            raise ValueError('native Preview requires a loopback HTTP origin with explicit port')
        if not commit.strip():
            raise ValueError('commit required')
        _digest(lockfile_sha256, 'lockfile_sha256')
        _safe_path(registry_root, 'registry root')
        _safe_path(source_root, 'input source root')
        _safe_path(manifest_path, 'manifest path')
        instance_root = registry_root / str(instance_id)
        if instance_root.exists() or instance_root.is_symlink():
            raise ValueError('Preview instance directory already exists')
        manifest_bytes = manifest_path.read_bytes()
        baseline = hashlib.sha256(manifest_bytes).hexdigest()
        database = f'lt_{instance_id.hex}_preview'
        role = f'lt_{instance_id.hex}_runtime'
        head = _schema_head()
        with TemporaryDirectory(prefix='leadtrace-preview-preflight-') as temporary:
            stage = Path(temporary)
            frozen_manifest = stage / 'manifest.json'
            frozen_manifest.write_bytes(manifest_bytes)
            source_store = LocalAssetStore(stage / 'scratch', source_roots={'source_pdfs': source_root})
            importer = CatalogImportService(frozen_manifest, source_store)
            if importer.root_key != 'source_pdfs':
                raise ValueError('unsupported source root key')
            frozen_source = stage / 'sources'
            frozen_source.mkdir()
            for entry in importer.entries:
                source = source_root / entry['source_key']
                _safe_path(source, 'source PDF')
                if not source.is_file():
                    raise ValueError('source PDF missing')
                target = frozen_source / entry['source_key']
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
                target.chmod(0o444)
            importer = CatalogImportService(frozen_manifest, LocalAssetStore(stage / 'scratch', source_roots={'source_pdfs': frozen_source}))
            importer.preview()
            # The admin database is explicit and must already exist in a dedicated cluster.
            with _connect(parent, autocommit=True) as admin:
                if admin.info.dbname != parent.database or admin.info.host != host or admin.info.port != port:
                    raise ValueError('provisioning connection identity mismatch')
                if admin.execute('SELECT 1 FROM pg_database WHERE datname=%s', (database,)).fetchone():
                    raise ValueError('Preview database already exists')
                if admin.execute('SELECT 1 FROM pg_roles WHERE rolname=%s', (role,)).fetchone():
                    raise ValueError('Preview role already exists')
                registry_root.mkdir(parents=True, exist_ok=True)
                instance_root.mkdir(mode=0o700)  # Exclusive reservation across processes.
                reserved = True
                runtime = PreviewRuntime(registry_root)
                assets, sources, artifacts = (instance_root / name for name in ('assets', 'sources', 'artifacts'))
                registry_path = runtime.create(instance_id=instance_id, database_name=database,
                    database_host=host, database_port=port, baseline_sha256=baseline,
                    schema_revision=head, asset_root=assets, source_root=sources,
                    artifact_root=artifacts, origin=origin.rstrip('/'))
                registry = runtime.read(instance_id)
                registry.update(runtime_role=role, management='native-v1', phase='reserved')
                runtime._write(registry_path, registry, create=False)
                shutil.move(str(frozen_source), sources)
                shutil.copyfile(frozen_manifest, instance_root / 'manifest.json')
                assets.mkdir()
                artifacts.mkdir()
                phase = 'database creation'
                _record_phase(runtime, instance_id, phase)
                # The provisioning role owns schema objects; runtime receives only grants.
                admin.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0').format(sql.Identifier(database)))
                password = secrets.token_urlsafe(36)
                admin.execute(sql.SQL('CREATE ROLE {} LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}').format(sql.Identifier(role), sql.Literal(password)))
                registry.update(phase='database_created')
                runtime._write(registry_path, registry, create=False)
            database_url = parent.set(database=database)
            phase = 'migration'
            _record_phase(runtime, instance_id, phase)
            config = Config(str(DEFAULT_ALEMBIC_CONFIG_PATH))
            config.attributes['leadtrace_database_url'] = database_url.render_as_string(hide_password=False)
            config.attributes['leadtrace_expected_database_name'] = database
            command.upgrade(config, 'head')
            phase = 'catalog and account seed'
            _record_phase(runtime, instance_id, phase)
            accounts = [{'username': name, 'password': secrets.token_urlsafe(24)} for name in ('preview-admin', 'preview-reviewer')]
            engine = create_database_engine(database_url.render_as_string(hide_password=False))
            try:
                with create_session_factory(engine).begin() as session:
                    CatalogImportService(instance_root / 'manifest.json', LocalAssetStore(assets, source_roots={'source_pdfs': sources})).apply(session)
                    users = UserService()
                    admin_user = users.bootstrap_admin(session, username=accounts[0]['username'], display_name='Preview Admin',
                        default_password=accounts[0]['password'], request_id=f'preview-create-{instance_id}')
                    users.create_managed_user(session, actor_id=admin_user.id, username=accounts[1]['username'], display_name='Preview Reviewer',
                        role=UserRole.REVIEWER, default_password=accounts[1]['password'], request_id=f'preview-create-{instance_id}')
                    session.add(PreviewMarker(instance_id=instance_id, baseline_sha256=baseline, schema_revision=head))
            finally:
                engine.dispose()
            phase = 'runtime grants and verification'
            _record_phase(runtime, instance_id, phase)
            _grant_runtime(database_url, database, role)
            runtime_url = database_url.set(username=role, password=password)
            # Explicit values for every field prevent accidental inherited production settings.
            defaults = {name: field.get_default(call_default_factory=True) for name, field in Settings.model_fields.items()}
            defaults.update(environment='preview', database_url=runtime_url.render_as_string(hide_password=False),
                session_secret=secrets.token_urlsafe(48), default_account_password=None, metrics_bearer_token=None,
                allowed_hosts=[parsed.hostname], source_roots={'source_pdfs': sources}, asset_root=assets,
                preview_instance_id=instance_id, preview_baseline_sha256=baseline, preview_artifact_root=artifacts,
                preview_registry_path=registry_path, deployment_profile='ai-prefill-preview-native')
            settings = _ProvisionSettings(**defaults)
            # Verify using an unpublished ready snapshot; public registry stays initializing.
            verification_path = instance_root / '.verify-registry.json'
            ready = {**runtime.read(instance_id), 'state': 'ready', 'commit': commit, 'lockfile_sha256': lockfile_sha256}
            _private_json(verification_path, ready)
            runtime_engine = create_database_engine(settings.database_url)
            try:
                with runtime_engine.connect() as connection:
                    verify_preview_connection(settings.model_copy(update={'preview_registry_path': verification_path}), connection, lock=True)
            finally:
                runtime_engine.dispose()
                verification_path.unlink(missing_ok=True)
            phase = 'profile publication'
            _record_phase(runtime, instance_id, phase)
            profile_path, credentials_path = instance_root / 'runtime.json', instance_root / 'credentials.json'
            _private_json(credentials_path, {'accounts': accounts})
            _private_json(profile_path, _settings_json(settings))
            runtime.complete(instance_id, commit=commit, lockfile_sha256=lockfile_sha256)
            return ProvisionedPreview(instance_id, registry_path, profile_path, credentials_path, origin.rstrip('/'))
    except Exception:
        # Never surface driver/validation exceptions: they may embed privileged DSNs.
        state = '; owned resources remain initializing for inspection' if reserved else '; no instance initialized'
        raise PreviewProvisionError(f'Preview creation failed during {phase}{state}') from None
