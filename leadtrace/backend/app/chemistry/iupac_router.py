from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, Field, ConfigDict

from app.api.errors import APIError
from app.chemistry.iupac import IupacError, resolve_iupac
from app.config import Settings
from app.security.permissions import RouteAccess, declare_route_access, get_authenticated_principal, require_request_csrf
from app.security.policies import Principal
from app.users.models import UserRole


class IupacRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=1000)


class IupacResponse(BaseModel):
    smiles: str
    molfile: str
    resolver: str


def create_iupac_router(settings: Settings) -> APIRouter:
    router = APIRouter(tags=['chemistry'])

    @router.post('/api/v2/chemistry/resolve-iupac', response_model=IupacResponse)
    @declare_route_access(RouteAccess.AUTHENTICATED)
    def convert_name(
        payload: IupacRequest,
        response: Response,
        csrf_token: str | None = Header(default=None, alias='X-CSRF-Token'),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> IupacResponse:
        if principal.must_change_password:
            raise HTTPException(403, 'Password change required')
        if principal.role not in {UserRole.REVIEWER, UserRole.ADMIN}:
            raise HTTPException(403, 'Permission denied')
        require_request_csrf(principal, csrf_token, settings.session_secret.get_secret_value())
        try:
            result = resolve_iupac(payload.name, jar_path=settings.opsin_jar)
        except IupacError as error:
            status = 503 if error.code in {'IUPAC_TIMEOUT', 'IUPAC_UNAVAILABLE', 'IUPAC_BUSY'} else 422
            raise APIError(status, error.code, 'Local name conversion could not be completed') from None
        response.headers['Cache-Control'] = 'no-store'
        return IupacResponse(smiles=result.smiles, molfile=result.molfile, resolver=result.resolver)

    return router
