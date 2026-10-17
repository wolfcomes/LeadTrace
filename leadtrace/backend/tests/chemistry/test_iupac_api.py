from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api.errors import install_api_error_handling
from app.chemistry.iupac import IupacResult, IupacError
from app.chemistry.iupac_router import create_iupac_router
from app.config import Settings
from app.database import get_db_session
from app.security.csrf import hash_csrf_token
from app.security.permissions import get_authenticated_principal
from app.security.policies import Principal
from app.users.models import UserRole


@pytest.fixture
def app(monkeypatch):
    application = FastAPI()
    install_api_error_handling(application)
    application.include_router(create_iupac_router(Settings()))
    application.dependency_overrides[get_db_session] = lambda: None
    monkeypatch.setattr('app.chemistry.iupac_router.resolve_iupac', lambda *a, **k: IupacResult('CCO', 'molfile'))
    return application


def authenticate(app, role=UserRole.REVIEWER, *, must_change_password=False):
    app.dependency_overrides[get_authenticated_principal] = lambda: Principal(
        user_id=uuid4(), role=role, must_change_password=must_change_password,
        csrf_hash=hash_csrf_token('csrf', Settings().session_secret.get_secret_value()),
    )


def test_requires_authentication(app):
    response = TestClient(app).post('/api/v2/chemistry/resolve-iupac', json={'name': 'ethanol'})
    assert response.status_code == 401


@pytest.mark.parametrize('role', [UserRole.REVIEWER, UserRole.ADMIN])
def test_resolves_for_reviewer_and_admin_with_csrf(app, role):
    authenticate(app, role)
    response = TestClient(app).post('/api/v2/chemistry/resolve-iupac', json={'name': 'ethanol'}, headers={'X-CSRF-Token': 'csrf'})
    assert response.status_code == 200
    assert response.json() == {'smiles': 'CCO', 'molfile': 'molfile', 'resolver': 'OPSIN 2.8.0'}
    assert response.headers['cache-control'] == 'no-store'


@pytest.mark.parametrize('role,password_change,token', [(UserRole.VISITOR, False, 'csrf'), (UserRole.REVIEWER, True, 'csrf'), (UserRole.REVIEWER, False, '')])
def test_rejects_unprivileged_or_unprotected_conversion(app, role, password_change, token):
    authenticate(app, role, must_change_password=password_change)
    response = TestClient(app).post('/api/v2/chemistry/resolve-iupac', json={'name': 'ethanol'}, headers={'X-CSRF-Token': token})
    assert response.status_code == 403


def test_safe_timeout_error(app, monkeypatch):
    authenticate(app)
    def timeout(*a, **k):
        raise IupacError('IUPAC_TIMEOUT')
    monkeypatch.setattr('app.chemistry.iupac_router.resolve_iupac', timeout)
    response = TestClient(app).post('/api/v2/chemistry/resolve-iupac', json={'name': 'ethanol'}, headers={'X-CSRF-Token': 'csrf'})
    assert response.status_code == 503
    assert response.json()['code'] == 'IUPAC_TIMEOUT'
